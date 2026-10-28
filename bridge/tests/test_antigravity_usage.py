"""Antigravity quotas from Telemetry appear in the cockpit without a second probe."""
import json

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


def test_antigravity_pill_groups_and_settings(tour_browser):
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
      source:document.querySelector('#usageDials .up-foot').textContent
    }))()""")
    assert result["pill"] == "70%"
    assert "Gemini 4 Argon · 7d" in result["title"]
    assert result["headings"] == ["Claude", "Codex", "Antigravity (Gemini)"]
    assert result["names"] == ["Gemini Models", "Claude and GPT models", "Gemini 4 Argon"]
    assert result["labels"] == ["MODEL GROUP"] * 3
    assert result["dials"] == 3
    assert "Antigravity quotas from ORRERY Telemetry" in result["source"]

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
      name:document.querySelector('#usageDials .up-subname').textContent,
      markup:document.querySelector('#usageDials .up-subname').children.length,
      executed:window.__usageInjected===true
    }))()""") == {"name": name, "markup": 0, "executed": False}
