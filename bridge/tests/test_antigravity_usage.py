"""Antigravity quotas from Telemetry appear in the cockpit without a second probe."""
import json

import pytest

from test_cockpit_tour import tour_browser
from test_deepseek_usage import QUOTAS, Dashboard, balance_entry, get_usage, request_for, usage_dom

ANTIGRAVITY = {
    "provider": "antigravity", "status": "ok", "observed_at": 1792370000,
    "buckets": [
        {"id": "gemini-5h", "label": "Gemini Models · 5h", "remaining_percent": 100,
         "window_seconds": 18000, "resets_at": 1792388000},
        {"id": "gemini-weekly", "label": "Gemini Models · 7d", "remaining_percent": 82.2,
         "window_seconds": 604800, "resets_at": 1792832964},
        {"id": "third-party-weekly", "label": "Claude and GPT models · 7d", "remaining_percent": 100,
         "window_seconds": 604800, "resets_at": 1793296417},
        {"id": "gemini-argon-weekly", "label": "Gemini 4 Argon · 7d", "remaining_percent": 69.9,
         "window_seconds": 604800, "resets_at": 1792954509},
    ],
}


def test_antigravity_catalog_is_forwarded_only_when_telemetry_reports_it():
    dashboard = Dashboard({"providers": QUOTAS + [ANTIGRAVITY]})
    request = request_for(dashboard)
    providers = get_usage(request)
    assert [p["provider"] for p in providers] == ["claude", "codex", "antigravity"]
    assert [w["limit"] for w in providers[-1]["windows"]] == [
        "Gemini Models", "Gemini Models", "Claude and GPT models", "Gemini 4 Argon"
    ]
    assert all(w["extra"] for w in providers[-1]["windows"])
    assert get_usage(request) == providers
    assert len(dashboard.urls) == 1

    dashboard.payload = {"providers": QUOTAS}
    request.query = {"refresh": "1"}
    assert [p["provider"] for p in get_usage(request)] == ["claude", "codex"]


def test_antigravity_dials_match_other_providers_and_settings(tour_browser):
    import usage_probe as up
    _, evaluate = tour_browser
    payload = {"providers": [up.provider_from_quota_payload(e).to_json()
                             for e in QUOTAS + [ANTIGRAVITY]]}
    usage_dom(evaluate, payload)
    result = evaluate("""(()=>({
      pill:document.querySelector('#usageBtn [data-provider="antigravity"] b').textContent,
      title:document.querySelector('#usageBtn [data-provider="antigravity"]').title,
      headings:[...document.querySelectorAll('#usageDials .up-head .up-name')].map(e=>e.textContent),
      names:[...document.querySelectorAll('#usageDials .up-prov:last-of-type .up-subname')].map(e=>e.textContent),
      labels:[...document.querySelectorAll('#usageDials .up-prov:last-of-type .up-sub > span:first-child')].map(e=>e.textContent),
      dials:document.querySelectorAll('#usageDials .up-prov:last-of-type .dial').length,
      dialLabels:[...document.querySelectorAll('#usageDials .up-prov:last-of-type .dial .lab')].map(e=>e.textContent),
      foreign:document.querySelector('#usageDials .up-prov:last-of-type').textContent.includes('Claude and GPT models'),
      untouched:document.querySelector('#usageDials .up-prov:last-of-type').textContent.includes('untouched'),
      source:document.querySelector('#usageDials .up-foot').textContent
    }))()""")
    assert result["pill"] == "70%"
    assert "Gemini 4 Argon · 7d" in result["title"]
    assert result["headings"] == ["Claude", "Codex", "Antigravity (Gemini)"]
    assert result["names"] == []
    assert result["labels"] == []
    assert result["dialLabels"] == ["5H", "7D", "ARGON"]
    assert result["foreign"] is False
    assert result["untouched"] is False
    assert result["dials"] == 3
    assert "Antigravity quotas from ORRERY Telemetry" in result["source"]
    positions = evaluate("""(()=>{
      const pop=document.getElementById('usagePopover');pop.showPopover();
      const rects=[...document.querySelectorAll('#usageDials .up-prov:last-of-type .dial')]
        .map(e=>e.getBoundingClientRect());
      pop.hidePopover();
      return rects.map(r=>({x:r.left,y:r.top,width:r.width,height:r.height}));
    })()""")
    assert len(positions) == 3
    assert all(abs(rect["y"] - positions[0]["y"]) < 1 for rect in positions)
    assert all(left["x"] + left["width"] <= right["x"]
               for left, right in zip(positions, positions[1:]))

    result = evaluate("""(()=>{
      renderUsageSettings();
      const toggle=document.querySelector('#usageProviderRows [data-provider="antigravity"]');
      toggle.click();
      return {hidden:document.querySelector('#usageBtn [data-provider="antigravity"]').hidden,
        shown:[...document.querySelectorAll('#usageDials .up-head .up-name')].some(e=>e.textContent==='Antigravity (Gemini)')};
    })()""")
    assert result == {"hidden": True, "shown": False}

    usage_dom(evaluate, {"providers": payload["providers"][:2]})
    assert evaluate("document.querySelector('#usageBtn [data-provider=\"antigravity\"]')===null")


def test_antigravity_dashboard_failure_keeps_last_windows_as_stale():
    dashboard = Dashboard({"providers": QUOTAS + [ANTIGRAVITY]})
    request = request_for(dashboard)
    good = get_usage(request)[-1]
    dashboard.payload = None
    request.query = {"refresh": "1"}
    failed = get_usage(request)[-1]
    assert failed["provider"] == "antigravity"
    assert failed["status"] == "stale"
    assert failed["reason"] == "telemetry_unavailable"
    assert failed["windows"] == good["windows"]
    assert failed["observed_at"] == good["observed_at"]
    assert len(dashboard.urls) == 2
    assert all(url.endswith("/api/quotas") for url in dashboard.urls)


@pytest.mark.parametrize("provider", ["claude", "codex", "antigravity"])
@pytest.mark.parametrize("recovery", ["refresh", "ttl"])
def test_failed_refresh_stays_stale_until_a_successful_read(monkeypatch, provider, recovery):
    import orrery_backend as ob

    clock = [1000.0]
    monkeypatch.setattr(ob.time, "time", lambda: clock[0])
    entries = QUOTAS + [ANTIGRAVITY]
    dashboard = Dashboard({"providers": entries})
    request = request_for(dashboard)

    def read_provider():
        return next(p for p in get_usage(request) if p["provider"] == provider)

    good = read_provider()
    assert good["status"] == "ok"
    assert read_provider() == good
    assert len(dashboard.urls) == 1

    clock[0] += 1  # force a read while the successful cache is still within TTL
    dashboard.payload = None
    request.query = {"refresh": "1"}
    failed = read_provider()
    assert failed["status"] == "stale"
    assert failed["reason"] == "telemetry_unavailable"
    assert failed["windows"] == good["windows"]
    assert failed["observed_at"] == good["observed_at"]
    assert len(dashboard.urls) == 2

    request.query = {}
    assert read_provider() == failed
    assert len(dashboard.urls) == 2

    dashboard.payload = {"providers": [
        {**entry, "observed_at": entry["observed_at"] + 10,
         "buckets": [{**bucket, "remaining_percent": 23} for bucket in entry["buckets"]]}
        for entry in entries
    ]}
    if recovery == "refresh":
        request.query = {"refresh": "1"}
    else:
        clock[0] += 60  # a normal request retries at the cache TTL boundary
    recovered = read_provider()
    assert recovered["status"] == "ok"
    assert recovered["reason"] == ""
    assert recovered["observed_at"] == good["observed_at"] + 10
    assert all(w["remaining_percent"] == 23 for w in recovered["windows"])
    assert len(dashboard.urls) == 3
    request.query = {}
    assert read_provider() == recovered
    assert len(dashboard.urls) == 3


@pytest.mark.parametrize("payload, reason", [
    (None, "telemetry_unavailable"),
    ({"providers": []}, "provider_not_reported"),
])
def test_cold_failure_retries_on_the_next_normal_request(monkeypatch, payload, reason):
    import orrery_backend as ob

    clock = [1000.0]
    monkeypatch.setattr(ob.time, "time", lambda: clock[0])
    dashboard = Dashboard(payload)
    request = request_for(dashboard)
    failed = get_usage(request)
    assert [p["provider"] for p in failed] == ["claude", "codex"]
    assert all(p["status"] == "unavailable" and p["reason"] == reason for p in failed)
    assert len(dashboard.urls) == 1

    clock[0] += 1  # retry before the TTL when there was no old observation
    dashboard.payload = {"providers": QUOTAS}
    recovered = get_usage(request)
    assert all(p["status"] == "ok" and p["reason"] == "" for p in recovered)
    assert [p["observed_at"] for p in recovered] == [e["observed_at"] for e in QUOTAS]
    assert all(p["windows"] for p in recovered)
    assert len(dashboard.urls) == 2
    assert get_usage(request) == recovered
    assert len(dashboard.urls) == 2


def test_unavailable_antigravity_does_not_invent_windows():
    entry = {"provider": "antigravity", "status": "unavailable",
             "reason": "sign_in_required", "buckets": []}
    providers = get_usage(request_for(Dashboard({"providers": QUOTAS + [entry]})))
    assert providers[-1]["provider"] == "antigravity"
    assert providers[-1]["status"] == "unavailable"
    assert providers[-1]["reason"] == "sign_in_required"
    assert providers[-1]["windows"] == []
    assert providers[-1]["observed_at"] is None


def test_antigravity_and_balance_slots_are_independent(tour_browser):
    import usage_probe as up
    _, evaluate = tour_browser
    providers = [up.provider_from_quota_payload(e).to_json()
                 for e in QUOTAS + [ANTIGRAVITY, balance_entry()]]
    usage_dom(evaluate, {"providers": providers})
    assert evaluate("""[...document.querySelectorAll('#usageBtn .up-p')]
      .map(e=>[e.dataset.provider,e.querySelector('b').textContent])""") == [
        ["claude", "64%"], ["codex", "47%"], ["antigravity", "70%"], ["dsh", "$12"]]
    usage_dom(evaluate, {"providers": [p for p in providers if p["provider"] != "antigravity"]})
    assert evaluate("""!document.querySelector('#usageBtn [data-provider="antigravity"]')
      && document.querySelector('#usageBtn [data-provider="dsh"] b').textContent==='$12'""")


def test_named_pool_binding_does_not_change_other_providers(tour_browser):
    import usage_probe as up
    _, evaluate = tour_browser
    windows = up.provider_from_quota_payload(ANTIGRAVITY).to_json()["windows"]
    expression = """(()=>{
      const windows=WINDOWS;
      const third=windows.find(w=>w.limit==='Claude and GPT models');
      third.remaining_percent=1;
      const before=JSON.stringify(windows);
      const ag=usageBinding({provider:'antigravity',windows});
      const codex=usageBinding({provider:'codex',windows:[
        {id:'main',remaining_percent:90,extra:false},...windows]});
      return {ag:ag.id,codex:codex.id,unchanged:JSON.stringify(windows)===before};
    })()""".replace('WINDOWS', json.dumps(windows))
    assert evaluate(expression) == {"ag": "gemini-argon-weekly", "codex": "main", "unchanged": True}


def test_antigravity_model_group_is_rendered_as_text(tour_browser):
    import usage_probe as up
    _, evaluate = tour_browser
    name = '<img src=x onerror="window.__usageInjected=true">'
    entry = {"provider": "antigravity", "status": "ok", "buckets": [
        {"id": "named", "label": name + " · 7d", "remaining_percent": 42}]}
    usage_dom(evaluate, {"providers": [up.provider_from_quota_payload(entry).to_json()]})
    assert evaluate("""(()=>({
      name:document.querySelector('#usageDials .dial .lab').textContent,
      markup:document.querySelector('#usageDials .dial .lab').children.length,
      executed:window.__usageInjected===true
    }))()""") == {"name": name.upper(), "markup": 0, "executed": False}


def test_antigravity_main_windows_are_ordered_and_third_party_is_not_binding(tour_browser):
    import usage_probe as up
    _, evaluate = tour_browser
    entry = {**ANTIGRAVITY, "buckets": [
        {**ANTIGRAVITY["buckets"][1], "remaining_percent": 95},
        {**ANTIGRAVITY["buckets"][2], "remaining_percent": 1},
        {**ANTIGRAVITY["buckets"][0], "remaining_percent": 100},
        {**ANTIGRAVITY["buckets"][3], "remaining_percent": 76},
    ]}
    usage_dom(evaluate, {"providers": [up.provider_from_quota_payload(entry).to_json()]})
    result = evaluate("""(()=>({
        pill:document.querySelector('#usageBtn [data-provider="antigravity"] b').textContent,
        title:document.querySelector('#usageBtn [data-provider="antigravity"]').title,
        labels:[...document.querySelectorAll('#usageDials .dial .lab')].map(e=>e.textContent),
        mainReset:document.querySelector('#usageDials .up-reset').textContent,
        foreign:document.querySelector('#usageDials').textContent.includes('Claude and GPT models')
    }))()""")
    assert result["pill"] == "76%"
    assert "Gemini 4 Argon · 7d" in result["title"]
    assert result["labels"] == ["5H", "7D", "ARGON"]
    assert result["mainReset"].startswith("next reset 5h · ")
    assert result["foreign"] is False



def test_antigravity_zero_use_still_displays_numeric_dials(tour_browser):
    import usage_probe as up
    _, evaluate = tour_browser
    entry = {**ANTIGRAVITY, "buckets": [
        {**bucket, "remaining_percent": 100} for bucket in ANTIGRAVITY["buckets"]
    ]}
    usage_dom(evaluate, {"providers": [up.provider_from_quota_payload(entry).to_json()]})
    result = evaluate("""(()=>({
        dials:[...document.querySelectorAll('#usageDials .dial .n')].map(e=>e.textContent),
        text:document.querySelector('#usageDials').textContent
    }))()""")
    assert result["dials"] == ["100%", "100%", "100%"]
    assert "untouched" not in result["text"]


def test_antigravity_only_third_party_buckets_cannot_fake_gemini_quota(tour_browser):
    import usage_probe as up
    _, evaluate = tour_browser
    entry = {**ANTIGRAVITY, "buckets": [ANTIGRAVITY["buckets"][2]]}
    usage_dom(evaluate, {"providers": [up.provider_from_quota_payload(entry).to_json()]})
    result = evaluate("""(()=>({
        value:document.querySelector('#usageBtn [data-provider="antigravity"] b').textContent,
        dials:document.querySelectorAll('#usageDials .dial').length,
        body:document.querySelector('#usageDials').textContent
    }))()""")
    assert result["value"] == "—"
    assert result["dials"] == 0
    assert "Claude and GPT models" not in result["body"]
