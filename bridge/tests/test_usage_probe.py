"""Parser and cache contracts for the USAGE ledger (bridge/usage_probe.py).

Run from bridge/: ``python -m pytest tests/test_usage_probe.py``.
Fixtures are synthetic; no account values, no credentials.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import usage_probe as up  # noqa: E402


CLAUDE_BODY = {
    "five_hour": {"utilization": 8.0, "resets_at": "2026-01-01T05:00:00Z"},
    "seven_day": {"utilization": 34.5, "resets_at": "2026-01-04T00:00:00+00:00"},
    "seven_day_opus": {"utilization": None},
    "limits": [
        {"kind": "weekly_scoped", "scope": {"model": {"display_name": "Fable"}},
         "percent": 63, "resets_at": "2026-01-04T00:00:00Z"},
        {"kind": "weekly_scoped", "scope": {"model": {"display_name": "Fable"}}, "percent": 1},
        {"kind": "monthly", "scope": {"model": {"display_name": "Other"}}, "percent": 5},
        {"kind": "weekly_scoped", "scope": {}, "percent": 5},
    ],
}


def test_claude_windows_follow_the_body_and_keep_model_scoped_names():
    snap = up.parse_claude_usage(CLAUDE_BODY, observed_at=100)
    assert snap.status == "ok" and snap.provider == "claude"
    assert [(w.id, w.label, w.remaining_percent, w.extra) for w in snap.windows] == [
        ("five_hour", "5h", 92.0, False),
        ("seven_day", "7d", 65.5, False),
        ("model:fable", "Fable", 37.0, False),
    ]
    assert snap.windows[0].resets_at == 1767243600
    assert snap.windows[2].window_seconds == 7 * 86400


def test_claude_reports_unavailable_instead_of_inventing_windows():
    snap = up.parse_claude_usage({"five_hour": {"utilization": "n/a"}}, observed_at=1)
    assert snap.status == "unavailable" and snap.reason == "no_windows_returned"
    assert snap.windows == ()


def test_claude_clamps_overuse_to_zero_remaining():
    snap = up.parse_claude_usage({"five_hour": {"utilization": 130}}, observed_at=1)
    assert snap.windows[0].remaining_percent == 0.0


CODEX_BODY = {
    "rateLimits": {"limitId": "codex", "limitName": None,
                   "primary": {"usedPercent": 10, "windowDurationMins": 10080, "resetsAt": 1789859084},
                   "secondary": None},
    "rateLimitsByLimitId": {
        "codex_bengalfox": {"limitId": "codex_bengalfox", "limitName": "Spark",
                            "primary": {"usedPercent": 0, "windowDurationMins": 300, "resetsAt": 1789380520},
                            "secondary": {"usedPercent": 25.5, "windowDurationMins": 10080, "resetsAt": True}},
        "broken": {"limitId": "broken", "primary": {"usedPercent": 1, "windowDurationMins": "300"}},
    },
}


def test_codex_labels_come_from_window_duration_and_extras_are_marked():
    snap = up.parse_codex_rate_limits(CODEX_BODY, observed_at=5)
    assert snap.status == "ok"
    assert [(w.id, w.label, w.remaining_percent, w.extra, w.limit, w.resets_at) for w in snap.windows] == [
        ("codex-10080m", "7d", 90.0, False, "", 1789859084),
        ("codex_bengalfox-300m", "5h", 100.0, True, "Spark", 1789380520),
        ("codex_bengalfox-10080m", "7d", 74.5, True, "Spark", None),
    ]


def test_codex_without_any_valid_window_is_unavailable():
    snap = up.parse_codex_rate_limits({"rateLimits": {"primary": {"usedPercent": 3}}}, observed_at=5)
    assert snap.status == "unavailable" and snap.reason == "no_windows_returned"


def test_duration_labels():
    assert [up._duration_label(m) for m in (300, 1440, 10080, 20160, 90)] == ["5h", "1d", "7d", "2w", "90m"]


def test_cache_keeps_the_last_good_snapshot_as_stale_on_failure():
    cache = up.UsageCache(ttl_seconds=60)
    good = up.parse_codex_rate_limits(CODEX_BODY, observed_at=5)
    assert cache.put(good, now=100) is good
    assert cache.get("codex", now=150) is good
    assert cache.get("codex", now=161) is None
    failed = up.ProviderUsage("codex", "unavailable", None, reason="probe_failed")
    kept = cache.put(failed, now=200)
    assert kept.status == "stale" and kept.windows == good.windows
    assert kept.observed_at == 5 and kept.reason == "probe_failed"
    # a failure with nothing to fall back on is reported as-is
    first = up.ProviderUsage("claude", "unavailable", None, reason="sign_in_required")
    assert cache.put(first, now=200) is first


def test_to_json_is_plain_data():
    snap = up.parse_claude_usage(CLAUDE_BODY, observed_at=100).to_json()
    assert snap["provider"] == "claude" and isinstance(snap["windows"], list)
    assert set(snap["windows"][0]) == {"id", "label", "remaining_percent", "window_seconds", "resets_at", "extra", "limit"}


def test_cache_honours_a_back_off_and_keeps_the_stale_snapshot_meanwhile():
    cache = up.UsageCache(ttl_seconds=60)
    good = up.parse_claude_usage(CLAUDE_BODY, observed_at=5)
    cache.put(good, now=100)
    limited = up.ProviderUsage("claude", "unavailable", None, reason="rate_limited", retry_after_seconds=300)
    kept = cache.put(limited, now=200)
    assert kept.status == "stale" and kept.reason == "rate_limited" and kept.windows == good.windows
    # well past the TTL but inside the back-off: still served from cache, no probe
    assert cache.get("claude", now=450) is kept
    assert cache.get("claude", now=501) is None
    # a second failure keeps the stale windows rather than dropping to unavailable
    again = cache.put(up.ProviderUsage("claude", "unavailable", None, reason="probe_failed"), now=502)
    assert again.status == "stale" and again.windows == good.windows


# --- reading the dashboard instead of the provider endpoints ---------------

def _quota_entry(provider, buckets, **kwargs):
    entry = {"provider": provider, "status": "ok", "observed_at": 1000, "buckets": buckets}
    entry.update(kwargs)
    return entry


def test_quota_buckets_become_windows_with_the_extra_grouping_intact():
    entry = _quota_entry("codex", [
        {"id": "codex", "label": "codex · 7d", "remaining_percent": 54.0,
         "window_seconds": 604800, "resets_at": 9000},
        {"id": "spark-5h", "label": "GPT-5.3-Codex-Spark · 5h", "remaining_percent": 100.0,
         "window_seconds": 18000, "resets_at": 1200},
    ])

    usage = up.provider_from_quota_payload(entry)

    assert usage.status == "ok"
    assert [(w.label, w.extra, w.limit) for w in usage.windows] == [
        ("7d", False, ""),
        ("5h", True, "GPT-5.3-Codex-Spark"),
    ]


def test_a_window_whose_current_value_is_unknown_draws_no_ring():
    """The dashboard keeps such a window by name; a ring would invent a number."""
    entry = _quota_entry("claude", [
        {"id": "five_hour", "label": "5h", "remaining_percent": 95.0,
         "window_seconds": 18000, "resets_at": 1200},
        {"id": "model-fable", "label": "Fable", "window_seconds": 604800, "resets_at": 9000},
    ])

    usage = up.provider_from_quota_payload(entry)

    assert [w.id for w in usage.windows] == ["five_hour"]


def test_a_provider_with_nothing_to_show_keeps_its_reason():
    entry = _quota_entry("claude", [], status="unavailable", reason="sign_in_required")

    usage = up.provider_from_quota_payload(entry)

    assert usage.status == "unavailable"
    assert usage.reason == "sign_in_required"


def test_the_last_observation_survives_the_dashboard_going_away():
    cache = up.UsageCache()
    live = up.ProviderUsage("claude", "ok", 1000, (up.UsageWindow(
        "five_hour", "5h", 95.0, 18000, 1200),))
    cache.put(live, 1000.0)

    kept = cache.last("claude")

    assert kept is not None
    assert kept.status == "stale", "an old number must not read as current"
    assert kept.observed_at == 1000
    assert [w.id for w in kept.windows] == ["five_hour"]
    assert kept.reason == "telemetry_unavailable"


def test_nothing_was_ever_observed_and_nothing_is_invented():
    assert up.UsageCache().last("claude") is None
