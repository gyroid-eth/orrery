"""Account-level usage windows for the cockpit's USAGE ledger.

Two providers, two very different transports:

* Claude: ``GET https://api.anthropic.com/api/oauth/usage`` with the OAuth
  token Claude Code itself keeps (``~/.claude/.credentials.json`` or the
  ``Claude Code-credentials`` Keychain item). This is the same request the
  ClaudeBar menu-bar app makes. It is **read-only**: the probe never refreshes
  or writes the token back. Claude Code refreshes its own token while it runs,
  so a stale token just reads as ``sign_in_required`` until the next session.
* Codex: ``codex app-server`` on stdio, JSON-RPC ``account/rateLimits/read``.
  The App Server is a short-lived subprocess per read; ``windowDurationMins``
  decides the label, never the primary/secondary position.

Only windows the provider actually returned are reported. Nothing is
fabricated when a window is missing, and provider error text never reaches
the browser: ``reason`` is a stable code, the exception type goes to the log.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from queue import Empty, Queue
from typing import Any, Mapping

log = logging.getLogger("orrery.usage")

CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CLAUDE_KEYCHAIN_SERVICE = "Claude Code-credentials"
CLAUDE_CREDS_PATH = os.path.expanduser("~/.claude/.credentials.json")
# The usage endpoint rate-limits polite pollers too. After a 429 we stay quiet
# at least this long, whatever Retry-After said.
CLAUDE_BACKOFF_SECONDS = 300


@dataclass(frozen=True)
class UsageWindow:
    id: str
    label: str
    remaining_percent: float
    window_seconds: int | None
    resets_at: int | None  # unix seconds, None when the provider gave none
    extra: bool = False  # a named additional limit (Codex Spark …), not the account's ordinary window
    limit: str = ""  # the additional limit's display name; "" for the ordinary windows


@dataclass(frozen=True)
class ProviderUsage:
    provider: str
    status: str  # ok | unavailable
    observed_at: int | None
    windows: tuple[UsageWindow, ...] = ()
    reason: str = ""  # stable code, only when status != ok
    retry_after_seconds: int = 0  # > 0 when the provider asked us to back off (HTTP 429)

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["windows"] = [asdict(w) for w in self.windows]
        return data


def _clamp_remaining(used_percent: Any) -> float | None:
    try:
        used = float(used_percent)
    except (TypeError, ValueError):
        return None
    if used != used:  # NaN
        return None
    return round(max(0.0, min(100.0, 100.0 - used)), 1)


def _iso_to_unix(value: Any) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


# ---------------------------------------------------------------- Claude ---

def parse_claude_usage(payload: Mapping[str, Any], *, observed_at: int) -> ProviderUsage:
    """Turn the ``/api/oauth/usage`` body into windows, in display order.

    ``five_hour`` and ``seven_day`` are the account windows; the per-model
    weekly limits (Fable, Opus, Sonnet …) live in ``limits[]`` with
    ``kind == "weekly_scoped"`` and carry their own ``display_name``.
    """
    windows: list[UsageWindow] = []
    for key, label, seconds in (("five_hour", "5h", 5 * 3600), ("seven_day", "7d", 7 * 86400)):
        entry = payload.get(key)
        if not isinstance(entry, Mapping):
            continue
        remaining = _clamp_remaining(entry.get("utilization"))
        if remaining is None:
            continue
        windows.append(UsageWindow(key, label, remaining, seconds, _iso_to_unix(entry.get("resets_at"))))

    seen = {w.id for w in windows}
    limits = payload.get("limits")
    for entry in limits if isinstance(limits, list) else []:
        if not isinstance(entry, Mapping) or entry.get("kind") != "weekly_scoped":
            continue
        scope = entry.get("scope")
        model = scope.get("model") if isinstance(scope, Mapping) else None
        name = model.get("display_name") if isinstance(model, Mapping) else None
        if not isinstance(name, str) or not name.strip():
            continue
        remaining = _clamp_remaining(entry.get("percent"))
        if remaining is None:
            continue
        wid = "model:" + name.strip().lower().replace(" ", "-")
        if wid in seen:
            continue
        seen.add(wid)
        windows.append(UsageWindow(wid, name.strip(), remaining, 7 * 86400, _iso_to_unix(entry.get("resets_at"))))

    if not windows:
        return ProviderUsage("claude", "unavailable", observed_at, reason="no_windows_returned")
    return ProviderUsage("claude", "ok", observed_at, tuple(windows))


def _claude_token_from_file(path: str = CLAUDE_CREDS_PATH) -> str | None:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    oauth = data.get("claudeAiOauth") if isinstance(data, Mapping) else None
    token = oauth.get("accessToken") if isinstance(oauth, Mapping) else None
    return token.strip() if isinstance(token, str) and token.strip() else None


def _claude_token_from_keychain() -> str | None:
    try:
        done = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", CLAUDE_KEYCHAIN_SERVICE, "-w"],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    try:
        data = json.loads(done.stdout.decode("utf-8", "replace"))
    except ValueError:
        return None
    oauth = data.get("claudeAiOauth") if isinstance(data, Mapping) else None
    token = oauth.get("accessToken") if isinstance(oauth, Mapping) else None
    return token.strip() if isinstance(token, str) and token.strip() else None


def claude_access_token() -> str | None:
    env = (os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or "").strip()
    return env or _claude_token_from_file() or _claude_token_from_keychain()


class _AuthRequired(Exception):
    pass


class _RateLimited(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("rate_limited")
        self.retry_after = retry_after


def _claude_fetch(token: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        CLAUDE_USAGE_URL,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": "orrery-cockpit",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise _AuthRequired() from exc
        if exc.code == 429:
            try:
                retry = int(exc.headers.get("Retry-After") or 0)
            except ValueError:
                retry = 0
            raise _RateLimited(max(retry, CLAUDE_BACKOFF_SECONDS)) from exc
        raise RuntimeError(f"http_{exc.code}") from exc
    data = json.loads(body)
    if not isinstance(data, dict):
        raise RuntimeError("non_object")
    return data


def probe_claude(*, timeout: float = 8.0, now: float | None = None) -> ProviderUsage:
    observed = int(now if now is not None else time.time())
    token = claude_access_token()
    if not token:
        return ProviderUsage("claude", "unavailable", None, reason="sign_in_required")
    try:
        payload = _claude_fetch(token, timeout)
    except _AuthRequired:
        return ProviderUsage("claude", "unavailable", None, reason="sign_in_required")
    except _RateLimited as exc:
        log.info("claude usage probe rate limited; backing off %ss", exc.retry_after)
        return ProviderUsage("claude", "unavailable", None, reason="rate_limited",
                             retry_after_seconds=exc.retry_after)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        log.info("claude usage probe failed: %s", type(exc).__name__)
        return ProviderUsage("claude", "unavailable", None, reason="probe_failed")
    return parse_claude_usage(payload, observed_at=observed)


# ----------------------------------------------------------------- Codex ---

def _duration_label(minutes: int) -> str:
    if minutes % 10080 == 0:
        return f"{minutes // 10080}w" if minutes != 10080 else "7d"
    if minutes % 1440 == 0:
        return f"{minutes // 1440}d"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def _codex_windows(limit_id: str, limit_name: Any, record: Mapping[str, Any]) -> list[UsageWindow]:
    out: list[UsageWindow] = []
    name = limit_name.strip() if isinstance(limit_name, str) and limit_name.strip() else ""
    for slot in ("primary", "secondary"):
        entry = record.get(slot)
        if not isinstance(entry, Mapping):
            continue
        minutes = entry.get("windowDurationMins")
        if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
            continue
        remaining = _clamp_remaining(entry.get("usedPercent"))
        if remaining is None:
            continue
        resets = entry.get("resetsAt")
        resets_at = resets if isinstance(resets, int) and not isinstance(resets, bool) else None
        base = _duration_label(minutes)
        out.append(UsageWindow(f"{limit_id}-{minutes}m", base, remaining, minutes * 60, resets_at,
                               extra=bool(name), limit=name))
    out.sort(key=lambda w: w.window_seconds or 0)
    return out


def parse_codex_rate_limits(payload: Mapping[str, Any], *, observed_at: int) -> ProviderUsage:
    """``account/rateLimits/read`` → windows. The plain ``codex`` limit (the
    account's ordinary usage) comes first; named extra limits follow."""
    by_id = payload.get("rateLimitsByLimitId")
    records: list[tuple[str, Any, Mapping[str, Any]]] = []
    if isinstance(by_id, Mapping) and by_id:
        for key, record in by_id.items():
            if isinstance(record, Mapping):
                records.append((str(record.get("limitId") or key), record.get("limitName"), record))
    legacy = payload.get("rateLimits")
    if isinstance(legacy, Mapping):
        legacy_id = str(legacy.get("limitId") or "codex")
        if legacy_id not in {r[0] for r in records}:
            records.append((legacy_id, legacy.get("limitName"), legacy))
    records.sort(key=lambda r: (r[0] != "codex", r[0]))

    windows: list[UsageWindow] = []
    for limit_id, limit_name, record in records:
        windows.extend(_codex_windows(limit_id, None if limit_id == "codex" else limit_name, record))
    if not windows:
        return ProviderUsage("codex", "unavailable", observed_at, reason="no_windows_returned")
    return ProviderUsage("codex", "ok", observed_at, tuple(windows))


def _pump(stream: Any, lines: "Queue[str | None]") -> None:
    try:
        for line in stream:
            lines.put(line)
    except (OSError, UnicodeError):
        pass
    finally:
        lines.put(None)


def _await_response(lines: "Queue[str | None]", request_id: int, deadline: float) -> dict[str, Any]:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("app-server timeout")
        try:
            line = lines.get(timeout=remaining)
        except Empty as exc:
            raise TimeoutError("app-server timeout") from exc
        if line is None:
            raise RuntimeError("app-server closed")
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if not isinstance(message, dict) or message.get("id") != request_id:
            continue
        if "error" in message:
            raise RuntimeError("app-server error")
        result = message.get("result")
        return result if isinstance(result, dict) else {}


def read_codex_rate_limits(codex_bin: str, *, timeout: float = 20.0) -> dict[str, Any]:
    """One short-lived ``codex app-server`` round trip. The wire format is
    JSON-RPC without the ``jsonrpc`` member, one message per line."""
    process = subprocess.Popen(
        [codex_bin, "app-server"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", bufsize=1,
        start_new_session=True,  # the PATH entry may be a shim: end the whole group below
    )
    assert process.stdin is not None and process.stdout is not None
    lines: "Queue[str | None]" = Queue()
    threading.Thread(target=_pump, args=(process.stdout, lines), daemon=True, name="codex-usage-stdout").start()
    deadline = time.monotonic() + timeout

    def send(message: Mapping[str, Any]) -> None:
        process.stdin.write(json.dumps(dict(message), separators=(",", ":")) + "\n")
        process.stdin.flush()

    try:
        send({"id": 1, "method": "initialize",
              "params": {"clientInfo": {"name": "orrery-cockpit", "title": "ORRERY", "version": "1"}}})
        _await_response(lines, 1, deadline)
        send({"method": "initialized"})
        send({"id": 2, "method": "account/rateLimits/read"})
        return _await_response(lines, 2, deadline)
    finally:
        try:
            process.stdin.close()
        except OSError:
            pass
        _end_process_group(process)


def _end_process_group(process: subprocess.Popen[str]) -> None:
    """SIGTERM the app-server's whole session, then SIGKILL stragglers. A shim
    in front of the real binary would otherwise leave an orphan per probe."""
    import signal
    for sig, wait in ((signal.SIGTERM, 1.0), (signal.SIGKILL, 1.0)):
        if process.poll() is not None:
            break
        try:
            os.killpg(process.pid, sig)
        except (ProcessLookupError, PermissionError):
            process.send_signal(sig)
        try:
            process.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            continue


def probe_codex(codex_bin: str | None, *, timeout: float = 20.0, now: float | None = None) -> ProviderUsage:
    observed = int(now if now is not None else time.time())
    if not codex_bin:
        return ProviderUsage("codex", "unavailable", None, reason="codex_not_found")
    try:
        payload = read_codex_rate_limits(codex_bin, timeout=timeout)
    except (OSError, ValueError, RuntimeError, TimeoutError, subprocess.SubprocessError) as exc:
        log.info("codex usage probe failed: %s", type(exc).__name__)
        return ProviderUsage("codex", "unavailable", None, reason="probe_failed")
    return parse_codex_rate_limits(payload, observed_at=observed)


# ----------------------------------------------------------------- cache ---

@dataclass
class UsageCache:
    """Per-provider memo with a TTL. A failed probe keeps the last good
    snapshot (marked stale by ``observed_at``) instead of blanking the ledger."""
    ttl_seconds: float = 60.0
    entries: dict[str, tuple[float, ProviderUsage]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    blocked_until: dict[str, float] = field(default_factory=dict)

    def get(self, provider: str, now: float) -> ProviderUsage | None:
        with self.lock:
            hit = self.entries.get(provider)
            blocked = self.blocked_until.get(provider, 0.0)
        if hit and (now - hit[0] < self.ttl_seconds or now < blocked):
            return hit[1]
        return None

    def last(self, provider: str) -> ProviderUsage | None:
        """The last snapshot for a provider, however old — marked stale.

        The source can go away (the dashboard is not running); showing what was
        last seen, dated, beats blanking the ledger.
        """
        with self.lock:
            hit = self.entries.get(provider)
        if not hit:
            return None
        kept = hit[1]
        if kept.status == "ok" and kept.windows:
            return ProviderUsage(kept.provider, "stale", kept.observed_at, kept.windows,
                                 "telemetry_unavailable", kept.retry_after_seconds)
        return kept

    def put(self, snapshot: ProviderUsage, now: float) -> ProviderUsage:
        with self.lock:
            previous = self.entries.get(snapshot.provider)
            if snapshot.retry_after_seconds > 0:
                self.blocked_until[snapshot.provider] = now + snapshot.retry_after_seconds
            if snapshot.status != "ok" and previous and previous[1].status in ("ok", "stale"):
                kept = ProviderUsage(snapshot.provider, "stale", previous[1].observed_at,
                                     previous[1].windows, snapshot.reason, snapshot.retry_after_seconds)
                self.entries[snapshot.provider] = (now, kept)
                return kept
            self.entries[snapshot.provider] = (now, snapshot)
            return snapshot


# ------------------------------------------------------- telemetry source ---
# Both apps used to ask the provider endpoints themselves, and on one machine
# that was enough to be rate limited: the account endpoint answered 429 and the
# cockpit lost the windows it had. The dashboard already reads them on a budget
# it manages, so read its answer instead of opening a second mouth. When the
# dashboard cannot answer we keep the last observation rather than reaching for
# the endpoint, which would put the two mouths back.

def windows_from_quota_buckets(buckets: Any) -> tuple[UsageWindow, ...]:
    """`/api/quotas` buckets → cockpit windows, preserving the extra grouping."""
    windows: list[UsageWindow] = []
    for bucket in buckets if isinstance(buckets, list) else []:
        if not isinstance(bucket, Mapping):
            continue
        remaining = bucket.get("remaining_percent")
        if not isinstance(remaining, (int, float)) or isinstance(remaining, bool):
            continue  # a window whose current value is unknown carries no ring
        label = str(bucket.get("label") or "").strip()
        identity = str(bucket.get("id") or "").strip()
        if not label or not identity:
            continue
        # The dashboard names an extra limit "<limit> · <window>"; the ordinary
        # one carries the provider's own name.
        limit, _, tail = label.partition(" · ")
        extra = bool(tail) and limit.strip().lower() != str(bucket.get("provider") or "").lower()
        windows.append(UsageWindow(
            identity,
            (tail or label).strip(),
            round(max(0.0, min(100.0, float(remaining))), 1),
            bucket.get("window_seconds") if isinstance(bucket.get("window_seconds"), int) else None,
            bucket.get("resets_at") if isinstance(bucket.get("resets_at"), int) else None,
            extra,
            limit.strip() if extra else "",
        ))
    return tuple(windows)


def provider_from_quota_payload(entry: Mapping[str, Any]) -> ProviderUsage:
    provider = str(entry.get("provider") or "").strip() or "unknown"
    buckets = entry.get("buckets")
    for bucket in buckets if isinstance(buckets, list) else []:
        if isinstance(bucket, Mapping):
            bucket.setdefault("provider", provider)
    windows = windows_from_quota_buckets(buckets)
    status = str(entry.get("status") or "unavailable")
    observed_at = entry.get("observed_at")
    if not windows:
        return ProviderUsage(provider, "unavailable",
                             observed_at if isinstance(observed_at, int) else None,
                             reason=str(entry.get("reason") or "no_windows_returned"))
    return ProviderUsage(
        provider,
        "ok" if status in {"ok", "degraded"} else status,
        observed_at if isinstance(observed_at, int) else None,
        windows,
        reason=str(entry.get("reason") or ""),
    )
