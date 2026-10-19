"""USAGE has no balance row until telemetry explicitly returns one.

All observations are synthetic. These tests never read credentials or contact
providers; the DOM fixture uses the shared CDP browser and a static checkout.
"""
import json
from pathlib import Path

from test_cockpit_tour import tour_browser

FIXTURE = Path(__file__).parent / 'fixtures' / 'usage_without_deepseek.json'
QUOTAS = [
    dict(provider='claude', status='ok', observed_at=1792370000,
         buckets=[dict(id='five_hour', label='5h', remaining_percent=64,
                       window_seconds=18000, resets_at=None)]),
    dict(provider='codex', status='ok', observed_at=1792370000,
         buckets=[dict(id='weekly', label='codex · 7d', remaining_percent=47,
                       window_seconds=604800, resets_at=None)]),
]


def usage_dom(evaluate, payload):
    return evaluate("""(()=>{
      // Fix local clock formatting, so the byte comparison is portable.
      usageClock=()=> '12:00';
      usageData=PAYLOAD;
      renderUsagePill();renderUsagePopover();
      return {pill:document.getElementById('usageBtn').outerHTML,
        kicker:document.getElementById('usageKicker').textContent,
        body:document.getElementById('usageDials').innerHTML};
    })()""".replace('PAYLOAD', json.dumps(payload)))


def test_absent_balance_preserves_existing_api_and_dom(tour_browser):
    import usage_probe as up
    _, evaluate = tour_browser
    payload = dict(ts=1792370000, providers=[up.provider_from_quota_payload(e).to_json() for e in QUOTAS])
    assert dict(payload=payload, dom=usage_dom(evaluate, payload)) == json.loads(FIXTURE.read_text())


def balance_entry(total='12.3400', available=True, status='ok'):
    return dict(provider='dsh', measurement_kind='balance', status=status,
                observed_at=1792370000, buckets=[],
                balance=dict(currency='USD', total_balance=total, is_available=available)
                if status == 'ok' else None,
                **({} if status == 'ok' else dict(reason='balance_key_unavailable')))


def test_balance_projection_preserves_decimal_text_zero_missing_usd_and_failure():
    import usage_probe as up
    for total, available in [('12.3400', True), ('0.0000', False), (None, True)]:
        wire = up.provider_from_quota_payload(balance_entry(total, available)).to_json()
        assert wire['measurement_kind'] == 'balance'
        assert wire['balance'] == dict(currency='USD', total_balance=total, is_available=available)
        assert wire['status'] == 'ok' and wire['windows'] == []
        assert wire['observed_at'] == 1792370000
    failed = up.provider_from_quota_payload(balance_entry(status='unavailable'))
    assert failed.to_json()['balance'] is None
    assert failed.status == 'unavailable' and failed.reason == 'balance_key_unavailable'


def test_balance_read_failure_never_reuses_a_previous_success_as_current():
    import usage_probe as up
    cache = up.UsageCache()
    good = up.provider_from_quota_payload(balance_entry())
    cache.put(good, 1000)
    absent_dashboard = cache.last('dsh')
    assert absent_dashboard.status == 'unavailable' and absent_dashboard.balance is None
    failed = cache.put(up.provider_from_quota_payload(balance_entry(status='unavailable')), 1001)
    assert failed.status == 'unavailable' and failed.balance is None


class Dashboard:
    def __init__(self, payload):
        self.payload = payload
        self.urls = []

    def get(self, url):
        import orrery_backend as ob
        self.urls.append(url)
        if self.payload is None:
            raise ob.ClientError('fixture offline')
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    status = 200

    async def json(self, **kwargs):
        return self.payload


def request_for(dashboard):
    from types import SimpleNamespace
    import usage_probe as up
    import orrery_backend as ob
    return SimpleNamespace(app={ob.HTTP_SESSION_KEY: dashboard, ob.USAGE_CACHE_KEY: up.UsageCache(),
                                ob.USAGE_LOCKS_KEY: {}}, query={})


def get_usage(request):
    import asyncio
    import orrery_backend as ob
    return json.loads(asyncio.run(ob.serve_usage(request)).body)['providers']


def test_existing_backend_endpoint_is_unchanged_without_opt_in_and_uses_one_cache():
    dashboard = Dashboard(dict(providers=QUOTAS))
    request = request_for(dashboard)
    before = json.loads(FIXTURE.read_text())['payload']['providers']
    assert get_usage(request) == before
    assert get_usage(request) == before
    assert len(dashboard.urls) == 1 and dashboard.urls[0].endswith('/api/quotas')


def test_optional_balance_survives_cache_hits_and_disappears_after_opt_out():
    dashboard = Dashboard(dict(providers=QUOTAS + [balance_entry()]))
    request = request_for(dashboard)
    assert get_usage(request)[-1]['balance']['total_balance'] == '12.3400'
    assert get_usage(request)[-1]['provider'] == 'dsh'
    assert len(dashboard.urls) == 1
    dashboard.payload = dict(providers=QUOTAS)
    request.query = dict(refresh='1')
    assert [p['provider'] for p in get_usage(request)] == ['claude', 'codex']
    request.query = {}
    assert [p['provider'] for p in get_usage(request)] == ['claude', 'codex']
    assert len(dashboard.urls) == 2


def test_dashboard_failure_makes_a_cached_balance_unknown():
    import orrery_backend as ob
    dashboard = Dashboard(dict(providers=QUOTAS + [balance_entry()]))
    request = request_for(dashboard)
    get_usage(request)
    dashboard.payload = None
    request.query = dict(refresh='1')
    failed = get_usage(request)[-1]
    assert failed['provider'] == 'dsh' and failed['status'] == 'unavailable'
    assert failed['balance'] is None and failed['measurement_kind'] == 'balance'
    request.query = {}
    assert get_usage(request)[-1]['balance'] is None
    assert all(url == ob.DASHBOARD_URL + '/api/quotas' for url in dashboard.urls)


def test_balance_dom_uses_currency_not_percentage_and_renders_unknown(tour_browser):
    import usage_probe as up
    _, evaluate = tour_browser
    old = [up.provider_from_quota_payload(e).to_json() for e in QUOTAS]
    for entry, amount, note in [
        (balance_entry(), 'USD 12.3400', 'Account available'),
        (balance_entry('0.0000', False), 'USD 0.0000', 'Account unavailable'),
        (balance_entry(None), 'No USD balance', 'Account available'),
        (balance_entry(status='unavailable'), 'Unknown', 'Balance unavailable'),
    ]:
        result = usage_dom(evaluate, dict(providers=old + [up.provider_from_quota_payload(entry).to_json()]))
        last = evaluate("""(()=>{const s=document.querySelector('#usageDials .up-prov:last-of-type');return {
          text:s.textContent,dials:s.querySelectorAll('.dial').length,
          warning:!!s.querySelector('.up-balance-warning'),
          pill:document.querySelector('#usageBtn [data-provider="dsh"]').textContent};})()""")
        assert amount in last['text'] and note in last['text']
        assert last['dials'] == 0 and '%' not in last['text']
        assert last['warning'] == (entry.get('balance') is not None and not entry['balance']['is_available'])
        assert 'cockpit-assets/deepseek.svg' in result['body']
    # Removing the optional API row also removes the dynamic pill slot.
    assert usage_dom(evaluate, dict(providers=old)) == json.loads(FIXTURE.read_text())['dom']


def test_failed_cockpit_poll_clears_only_the_balance_amount(tour_browser):
    import usage_probe as up
    _, evaluate = tour_browser
    providers = [up.provider_from_quota_payload(e).to_json() for e in QUOTAS + [balance_entry()]]
    usage_dom(evaluate, dict(providers=providers))
    after = evaluate("""(async()=>{
      const saved=fetch;fetch=async()=>{throw Error('fixture offline')};
      try{await pollUsage(false);return usageData.providers;}finally{fetch=saved;}
    })()""")
    assert after[:2] == providers[:2]
    assert after[-1]['balance'] is None and after[-1]['status'] == 'unavailable'
