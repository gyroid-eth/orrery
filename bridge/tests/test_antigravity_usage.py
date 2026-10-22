"""Antigravity quotas from Telemetry appear in the cockpit without a second probe."""
import json

from test_cockpit_tour import tour_browser
from test_deepseek_usage import QUOTAS, Dashboard, get_usage, request_for, usage_dom

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
        shown:!!document.querySelector('#usageDials .up-name')?.textContent.includes('Antigravity')};
    })()""")
    assert result == {"hidden": True, "shown": False}

    usage_dom(evaluate, {"providers": payload["providers"][:2]})
    assert evaluate("document.querySelector('#usageBtn [data-provider=\"antigravity\"]')===null")
