#!/usr/bin/env python3
"""Unified HTTP, telemetry, and multi-session tmux backend for ORRERY."""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
import os
import re
import shutil
import socket
import sqlite3
import stat
import pathlib
import subprocess
import tempfile
import urllib.parse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, urlencode

from aiohttp import ClientError, ClientSession, ClientTimeout, WSMsgType, web
from control_server import (
    ControlConfig,
    TmuxControlBridge,
    history_directory,
    prune_history_files,
    tmux_session_exists,
)
from usage_probe import (
    ProviderUsage,
    UsageCache,
    provider_from_quota_payload,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8791
DASHBOARD_URL = (
    os.environ.get("ORRERY_DASHBOARD_URL", "").strip()
    or "http://127.0.0.1:8770"
).rstrip("/")
GHOSTTY_BIN = "/Applications/Ghostty.app/Contents/MacOS/ghostty"
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
MAX_CLIENT_SESSIONS = 12
RECORDER_ROSTER_SECONDS = 5
SESSION_FORMAT = (
    "#{session_name}\t#{session_attached}\t#{session_windows}\t#{session_created}"
)
CLIENT_CONTROL_MODE_FORMAT = "#{client_control_mode}"

CONFIG_PATH = Path(os.path.expanduser("~/.orrery/config.json"))
CONFIG_KEYS = frozenset(
    {"project_key", "mail_db", "annotations_path", "orrery_root"}
)


def load_user_config(path: Path = CONFIG_PATH) -> dict[str, str]:
    """Read the optional shared ORRERY config without making startup fragile."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        key: value.strip()
        for key, value in raw.items()
        if key in CONFIG_KEYS and isinstance(value, str) and value.strip()
    }


USER_CONFIG = load_user_config()


def configured_value(env_names: tuple[str, ...], config_key: str) -> str | None:
    """Resolve non-empty environment values before the shared config file."""
    for env_name in env_names:
        value = os.environ.get(env_name)
        if isinstance(value, str) and value.strip():
            return os.path.expanduser(value.strip())
    value = USER_CONFIG.get(config_key)
    return os.path.expanduser(value) if value is not None else None


def default_mail_db() -> str:
    """The ORRERY Mail state root is the only mail database ORRERY reads.

    The third-party mcp_agent_mail layout was retired on 2026-09-03; its
    fallback was the last code path tying ORRERY to that implementation.
    """
    return os.path.expanduser("~/.agentstack/mail/storage.sqlite3")


MAIL_DB = Path(
    os.path.expanduser(configured_value(("ORRERY_MAIL_DB",), "mail_db") or default_mail_db())
)
MAIL_PROJECT_KEY = configured_value(
    ("ORRERY_PROJECT_KEY", "AGENTSTACK_PROJECT_KEY"),
    "project_key",
)
PORTRAIT_DIR = Path(
    os.path.expanduser(
        os.environ.get(
            "ORRERY_PORTRAIT_DIR",
            str(REPO_ROOT / "assets" / "portraits_64"),
        )
    )
)
PORTRAIT_DIR_HI = Path(
    os.path.expanduser(
        os.environ.get(
            "ORRERY_PORTRAIT_DIR_HI",
            str(REPO_ROOT / "assets" / "portraits"),
        )
    )
)
PORTRAIT_DIR_PX = Path(
    os.path.expanduser(
        os.environ.get(
            "ORRERY_PORTRAIT_DIR_PX",
            str(REPO_ROOT / "assets" / "portraits_px"),
        )
    )
)
_configured_annotations_path = configured_value(
    ("AGENTSTACK_ANNOTATIONS",),
    "annotations_path",
)
ANNOTATIONS_PATHS = tuple(
    Path(os.path.expanduser(path))
    for path in (
        (_configured_annotations_path,)
        if _configured_annotations_path
        else (
            "~/.agentstack/runtime/annotations.json",
            "~/.claude/tools/agent-dashboard/annotations.json",
        )
    )
)
SPAWN_CATALOG_PATH = HERE / "spawn_catalog.json"

# The dashboard recognises only interactive AskUserQuestion widgets.  ORRERY
# also needs to surface a normal prose question when the agent has returned to
# its idle prompt (for example, a push confirmation).  Keep this deliberately
# narrow: only the *last* substantive line before the idle prompt counts.  The
# TUI hard-wraps prose at pane width, so a "?" mid-paragraph can end a rendered
# line; requiring the final substantive line kills that false positive while a
# message that visually ends with "?" still reads as a question to the human.
_PENDING_QUESTION_LINE_RE = re.compile(r"^\s*\S[^\n]{6,258}[?？]\s*$")
_SUBSTANTIVE_LINE_RE = re.compile(r"[0-9A-Za-z぀-ヿ一-鿿]")
_IDLE_PROMPT_RE = re.compile(r"(?m)^\s*[❯>]\s*$")
_QUESTION_PROBE_TTL = 4.0
_question_probe_cache: dict[str, tuple[float, bool]] = {}

SCIENTIST_PORTRAITS = tuple(
    sorted(
        (
            "Leeuwenhoek",
            "Boltzmann",
            "Arrhenius",
            "Ramanujan",
            "Langmuir",
            "Guericke",
            "Vesalius",
            "Faraday",
            "Feynman",
            "Einstein",
            "Pasteur",
            "Linnaeus",
            "Ostwald",
            "Maxwell",
            "Pascal",
            "Newton",
            "Planck",
            "Kepler",
            "Mendel",
            "Turing",
            "Hubble",
            "Darwin",
            "Tesla",
            "Curie",
            "Euler",
            "Gauss",
            "Hooke",
            "Bohr",
            "Fabre",
            "Copernicus",
            "Archimedes",
            "Mendeleev",
            "Franklin",
            "Galileo",
            "Edison",
            "Dirac",
            "Fermi",
            "Koch",
            "Bell",
            "Somerville",
            "Lavoisier",
            "Lovelace",
            "Goodall",
            "Pauling",
            "Noether",
            "Yukawa",
            "Hopper",
            "Lamarr",
            "Bose",
            "Watt",
            "McClintock",
            "Meitner",
            "Chandrasekhar",
            "Jemison",
            "Carson",
            "Sagan",
            "Raman",
            "Galilei",
        ),
        key=len,
        reverse=True,
    )
)
PORTRAIT_ALIASES = {"Galilei": "Galileo"}
BODY_HEAD_STRIP_RE = re.compile(r"^[#>*\-\s`]+")

# telemetry path -> (dashboard path, allowed query keys)
PROXY_ROUTES = {
    "/telemetry/agents": ("/api/agents", ()),
    "/telemetry/messages": ("/api/messages-since", ("since", "limit")),
    "/telemetry/graph": ("/api/graph", ("all", "days", "spawn_only")),
    "/telemetry/spawn-catalog": ("/api/spawn-names", ()),
    "/telemetry/spawn-status": ("/api/spawn-status", ("name",)),
}


_ANNOTATIONS_CACHE_SECONDS = 4.5
_annotations_cache: tuple[float, dict[str, dict[str, str]]] = (0.0, {})


def normalize_annotations(raw: Any) -> dict[str, dict[str, str]]:
    """Normalize the dashboard's public annotation response."""
    if isinstance(raw, dict):
        for key in ("annotations", "agents"):
            if isinstance(raw.get(key), dict):
                raw = raw[key]
                break
    if not isinstance(raw, dict):
        return {}
    labels: dict[str, dict[str, str]] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not isinstance(value, dict):
            continue
        annot = {
            "role": str(value.get("role", "")).strip()[:40],
            "emoji": str(value.get("emoji", "")).strip()[:8],
            "group": str(value.get("group", "")).strip()[:24],
        }
        if any(annot.values()):
            labels[name] = annot
    return labels


def annotations_from_file() -> dict[str, dict[str, str]]:
    """Read the first available annotation fallback when the dashboard is down."""
    for path in ANNOTATIONS_PATHS:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        return normalize_annotations(raw)
    return {}


async def annotations_by_agent(
    http_session: ClientSession,
) -> dict[str, dict[str, str]]:
    """Fetch the dashboard's optional labels without owning them.

    The dashboard API is the public contract for both live and OSS installs.
    Keep the environment-configurable local file as a compatibility fallback,
    but only use it when the dashboard cannot be reached.
    """
    global _annotations_cache
    now = time.monotonic()
    if now - _annotations_cache[0] < _ANNOTATIONS_CACHE_SECONDS:
        return _annotations_cache[1]
    try:
        async with http_session.get(DASHBOARD_URL + "/api/annotations") as response:
            body = await response.read()
            if response.status == 200:
                try:
                    labels = normalize_annotations(json.loads(body))
                except (TypeError, json.JSONDecodeError, UnicodeDecodeError):
                    labels = {}
            else:
                labels = {}
    except (ClientError, asyncio.TimeoutError):
        labels = annotations_from_file()
    _annotations_cache = (time.monotonic(), labels)
    return labels


def pane_has_pending_user_question(session: str) -> bool:
    """Detect a recent prose question followed by Claude's idle prompt."""
    now = time.monotonic()
    cached = _question_probe_cache.get(session)
    if cached and now - cached[0] < _QUESTION_PROBE_TTL:
        return cached[1]
    pending = False
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-p", "-J", "-t", session, "-S", "-36"],
            capture_output=True, text=True, timeout=2,
        )
        tail = "\n".join(result.stdout.splitlines()[-32:]) if result.returncode == 0 else ""
        prompts = list(_IDLE_PROMPT_RE.finditer(tail))
        if prompts:
            before_prompt = tail[: prompts[-1].start()].splitlines()
            for line in reversed(before_prompt):
                if not _SUBSTANTIVE_LINE_RE.search(line):
                    continue  # skip blanks / box-drawing chrome
                pending = bool(_PENDING_QUESTION_LINE_RE.match(line))
                break
    except (OSError, subprocess.SubprocessError):
        pending = False
    _question_probe_cache[session] = (now, pending)
    return pending


def merge_agent_annotations(
    payload: bytes,
    labels: dict[str, dict[str, str]],
) -> bytes:
    """Add cockpit annotations and conservative prose-question state."""
    try:
        data = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return payload
    agents = data.get("agents") if isinstance(data, dict) else None
    if not isinstance(agents, list):
        return payload
    changed = False
    for agent in agents:
        if isinstance(agent, dict) and isinstance(agent.get("name"), str):
            annot = labels.get(agent["name"])
            if annot:
                agent["annot"] = annot
                changed = True
            if agent.get("running") and agent.get("act_state") == "wait" \
                    and pane_has_pending_user_question(agent["name"]):
                agent["act_state"] = "question"
                changed = True
    return json.dumps(data, ensure_ascii=False).encode("utf-8") if changed else payload


def normalize_spawn_catalog(remote: Any) -> dict[str, Any] | None:
    """Convert ``/api/spawn-names`` output to the cockpit catalog contract."""
    if not isinstance(remote, dict):
        return None

    providers = remote.get("providers")
    if isinstance(providers, list):
        normalized_providers: list[Any] = []
        for provider in providers:
            if not isinstance(provider, dict):
                normalized_providers.append(provider)
                continue
            normalized = dict(provider)
            models = provider.get("models")
            default_model = provider.get("default_model")
            # Previous models the dashboard names from the Claude catalog; the
            # cockpit folds them away. The default model is never one of them.
            overflow = provider.get("overflow_models")
            overflow_ids: list[str] = []
            if isinstance(overflow, list):
                for model in overflow:
                    if isinstance(model, str) and model != default_model \
                            and model not in overflow_ids:
                        overflow_ids.append(model)
                normalized["overflow_models"] = overflow_ids
            if isinstance(models, list):
                normalized["models"] = [
                    {
                        "id": model,
                        "label": model,
                        **({"default": True} if model == default_model else {}),
                        **({"overflow": True} if model in overflow_ids else {}),
                    }
                    if isinstance(model, str)
                    else model
                    for model in models
                ]
            normalized_providers.append(normalized)
        remote["providers"] = normalized_providers

    dirs = remote.get("dirs")
    if isinstance(dirs, list):
        remote["dirs"] = [
            {"path": path, "label": path}
            if isinstance(path, str)
            else path
            for path in dirs
        ]

    naming = remote.get("naming")
    if not isinstance(naming, dict):
        names = remote.get("names")
        scientists = (
            [
                entry["name"]
                for entry in names
                if isinstance(entry, dict)
                and isinstance(entry.get("name"), str)
                and entry.get("status") != "occupied"
            ]
            if isinstance(names, list)
            else []
        )
        adjectives = remote.get("adjectives")
        remote["naming"] = {
            "scientists": scientists,
            "adjectives": adjectives if isinstance(adjectives, list) else [],
            # The compact API exposes per-scientist availability rather than
            # the full historical identity set. Exact collisions remain
            # authoritative at POST /api/spawn.
            "taken": [],
        }
    remote.setdefault("schema", 1)
    return remote


# What the local spawn_catalog.json may contribute: how a provider, a model or
# an effort level is *shown*. Which models exist, which is the default, which
# efforts a model takes and any configuration error belong to the telemetry.
LOCAL_PROVIDER_ANNOTATIONS = ("label",)
LOCAL_MODEL_ANNOTATIONS = ("label", "hint", "title", "badge")


def merge_spawn_catalog(payload: bytes) -> bytes:
    """Decorate the dashboard's spawn catalog with the cockpit's own wording.

    The dashboard (/api/spawn-names) is authoritative for providers, models,
    the default model, overflow_models, efforts and model errors. The local
    file used to replace whole providers, so the telemetry's Codex default,
    efforts and overflow list never reached the cockpit (2026-09-28 review).
    It now only annotates ids the telemetry already sent: it never adds or
    removes a provider or a model, and never fills an empty or failed list.
    """
    try:
        remote = normalize_spawn_catalog(json.loads(payload))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return payload
    if remote is None:
        return payload
    # From here the normalized telemetry is what the cockpit gets: a missing
    # or broken local file only means "no annotations", never the raw
    # payload whose bare-string models the page cannot render.
    normalized = json.dumps(remote, ensure_ascii=False).encode("utf-8")
    try:
        local = json.loads(SPAWN_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"[spawn-catalog] local annotations unavailable: {exc}", file=sys.stderr, flush=True)
        return normalized
    remote_providers = remote.get("providers")
    local_providers = local.get("providers") if isinstance(local, dict) else None
    if not isinstance(remote_providers, list) or not isinstance(local_providers, list):
        return normalized
    notes = {
        provider.get("id"): provider
        for provider in local_providers
        if isinstance(provider, dict) and isinstance(provider.get("id"), str)
    }
    for provider in remote_providers:
        if not isinstance(provider, dict):
            continue
        note = notes.get(provider.get("id"))
        if not note:
            continue
        for key in LOCAL_PROVIDER_ANNOTATIONS:
            if isinstance(note.get(key), str) and note[key]:
                provider[key] = note[key]
        model_notes = {
            model.get("id"): model
            for model in note.get("models") or []
            if isinstance(model, dict) and isinstance(model.get("id"), str)
        }
        for model in provider.get("models") or []:
            if not isinstance(model, dict):
                continue
            model_note = model_notes.get(model.get("id"))
            if not model_note:
                continue
            for key in LOCAL_MODEL_ANNOTATIONS:
                if isinstance(model_note.get(key), str) and model_note[key]:
                    model[key] = model_note[key]
        hints = note.get("effort_hints")
        if isinstance(hints, dict):
            offered = set(provider.get("efforts") or [])
            for efforts in (provider.get("model_efforts") or {}).values():
                if isinstance(efforts, list):
                    offered.update(efforts)
            merged_hints = {
                effort: hint for effort, hint in hints.items()
                if effort in offered and isinstance(hint, str)
            }
            if isinstance(provider.get("effort_hints"), dict):
                merged_hints.update(provider["effort_hints"])
            if merged_hints:
                provider["effort_hints"] = merged_hints
    return json.dumps(remote, ensure_ascii=False).encode("utf-8")


HTTP_SESSION_KEY = web.AppKey("http_session", ClientSession)
TMUX_BIN_KEY = web.AppKey("tmux_bin", str)
USAGE_CACHE_KEY = web.AppKey("usage_cache", UsageCache)
USAGE_LOCKS_KEY = web.AppKey("usage_locks", dict)
PREFS_PATH = Path(os.path.expanduser(os.environ.get("ORRERY_PREFS_PATH") or "~/.orrery/prefs.json"))
PREFS_LOCK_KEY = web.AppKey("prefs_lock", asyncio.Lock)
PROXY_INFLIGHT_KEY = web.AppKey("proxy_inflight", dict)
# Identifies this backend process. The page compares it on every poll and
# reloads itself when it changes, so a restarted backend never sits behind a
# window still running the page it served hours ago.
BACKEND_BOOT_ID = f"{int(time.time())}-{os.getpid()}"
# Which localStorage keys are cockpit preferences worth sharing between the
# app window and browser tabs. Drafts, histories and caches stay per window.
# Mirrors SYNC_RE in bridge/prefs_sync.js.
PREFS_KEY_RE = re.compile(
    r"^(oc-(term-|mini-|split-|pinned-)|orrery\.(color-theme|spawn-advanced)"
    r"|agentstack\.theme-profile\.v1\.state$|agentdash\.(netparams|netctl|holdMs))"
)
PREFS_MAX_VALUE = 16 * 1024
PREFS_MAX_KEYS = 200


def prefs_key_ok(key: object) -> bool:
    return (
        isinstance(key, str)
        and len(key) <= 120
        and bool(PREFS_KEY_RE.match(key))
        and "history" not in key.lower()
    )


def read_prefs(path: Path = PREFS_PATH) -> dict[str, str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    prefs = raw.get("prefs") if isinstance(raw, dict) else None
    if not isinstance(prefs, dict):
        return {}
    return {k: v for k, v in prefs.items() if prefs_key_ok(k) and isinstance(v, str)}


def merge_prefs(current: dict[str, str], body: object) -> dict[str, str]:
    """Apply a ``{"set": {...}, "remove": [...]}`` request. Unknown keys and
    non-string values are ignored rather than rejected, so an older or newer
    cockpit never breaks the exchange."""
    merged = dict(current)
    if not isinstance(body, dict):
        return merged
    updates = body.get("set")
    if isinstance(updates, dict):
        for key, value in updates.items():
            if prefs_key_ok(key) and isinstance(value, str) and len(value) <= PREFS_MAX_VALUE:
                merged[key] = value
    removals = body.get("remove")
    if isinstance(removals, list):
        for key in removals:
            if isinstance(key, str):
                merged.pop(key, None)
    if len(merged) > PREFS_MAX_KEYS:
        merged = dict(sorted(merged.items())[:PREFS_MAX_KEYS])
    return merged


def write_prefs(prefs: dict[str, str], path: Path = PREFS_PATH) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"version": 1, "prefs": prefs}, ensure_ascii=False, indent=2, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, path)
    return prefs_rev(path)


def prefs_rev(path: Path = PREFS_PATH) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def prefs_response(path: Path = PREFS_PATH) -> web.Response:
    return web.json_response({"rev": prefs_rev(path), "prefs": read_prefs(path)},
                             headers={"Cache-Control": "no-store"})


async def serve_prefs(request: web.Request) -> web.Response:
    return prefs_response()


async def update_prefs(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except ValueError:
        return web.json_response({"error": "invalid_json"}, status=400)
    async with request.app[PREFS_LOCK_KEY]:
        merged = merge_prefs(read_prefs(), body)
        try:
            await asyncio.to_thread(write_prefs, merged)
        except OSError:
            return web.json_response({"error": "write_failed"}, status=500)
    return prefs_response()
USAGE_PROVIDERS = ("claude", "codex")


def resolve_codex_bin() -> str | None:
    """The Codex CLI the App Server probe should start. ``AGENTSTACK_CODEX_BIN``
    wins so a pinned binary (Air's nodebrew install) is used; otherwise PATH."""
    pinned = (os.environ.get("AGENTSTACK_CODEX_BIN") or "").strip()
    if pinned and os.access(pinned, os.X_OK):
        return pinned
    return shutil.which("codex")


async def serve_usage(request: web.Request) -> web.Response:
    """Account usage windows for the roster's USAGE ledger.

    The dashboard already reads these on a budget it manages, so this asks the
    dashboard rather than the providers. Two mouths on one account is how the
    Claude usage endpoint came to answer 429, and the cost fell on the numbers
    themselves: the account source dropped out and its per-model window went
    with it.

    When the dashboard cannot answer, keep the last observation instead of
    probing directly — reaching for the endpoint here is exactly what would
    put the second mouth back.
    """
    cache = request.app[USAGE_CACHE_KEY]
    locks = request.app[USAGE_LOCKS_KEY]
    now = time.time()
    force = request.query.get("refresh") == "1"

    cached = {p: cache.get(p, now) for p in USAGE_PROVIDERS}
    if not force and all(hit is not None for hit in cached.values()):
        snapshots = [cached[p] for p in USAGE_PROVIDERS]
    else:
        # single flight: a second page (the app and a browser tab, say) polling
        # at the same moment waits for the read in progress instead of opening
        # another one
        async with locks.setdefault("dashboard", asyncio.Lock()):
            fresh = None if force else {p: cache.get(p, time.time()) for p in USAGE_PROVIDERS}
            if fresh is not None and all(hit is not None for hit in fresh.values()):
                snapshots = [fresh[p] for p in USAGE_PROVIDERS]
            else:
                snapshots = await _usage_from_dashboard(request, cache)

    return web.json_response(
        {"ts": int(now), "providers": [s.to_json() for s in snapshots]},
        headers={"Cache-Control": "no-store"},
    )


async def _usage_from_dashboard(request: web.Request, cache) -> list[ProviderUsage]:
    """Read `/api/quotas`, or answer from what was last seen."""
    http_session = request.app[HTTP_SESSION_KEY]
    payload: Any = None
    try:
        async with http_session.get(DASHBOARD_URL + "/api/quotas") as response:
            if response.status == 200:
                payload = await response.json(content_type=None)
    except (ClientError, asyncio.TimeoutError, ValueError):
        payload = None

    entries = payload.get("providers") if isinstance(payload, Mapping) else None
    by_provider = {
        str(entry.get("provider")): entry
        for entry in (entries if isinstance(entries, list) else [])
        if isinstance(entry, Mapping)
    }

    snapshots: list[ProviderUsage] = []
    for provider in USAGE_PROVIDERS:
        entry = by_provider.get(provider)
        if entry is not None:
            snapshots.append(cache.put(provider_from_quota_payload(entry), time.time()))
            continue
        last = cache.last(provider) if hasattr(cache, "last") else None
        snapshots.append(last if last is not None else ProviderUsage(
            provider, "unavailable", None,
            reason="telemetry_unavailable" if payload is None else "provider_not_reported"))
    return snapshots


def _interactive_sessions(tmux_bin: str) -> set[str]:
    """Sessions with at least one non-control (human terminal) client."""
    result = subprocess.run(
        [tmux_bin, "list-clients", "-F",
         "#{session_name}\t#{client_control_mode}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return set()
    names: set[str] = set()
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) == 2 and fields[1].strip() == "0":
            names.add(fields[0])
    return names


# A GUI launch (Finder / launchd / Tauri sidecar) inherits only
# /usr/bin:/bin:/usr/sbin:/sbin, so a bare "tmux" cannot be resolved and every
# tmux call raises FileNotFoundError.  The old code caught that as OSError and
# reported an empty roster, which is indistinguishable from "no sessions" — the
# terminal pane simply stayed dead with no explanation.  Resolve the binary once
# at startup, searching PATH first and then the usual install prefixes.
TMUX_FALLBACK_PATHS = (
    "/opt/homebrew/bin/tmux",
    "/usr/local/bin/tmux",
    "/opt/local/bin/tmux",
    "/usr/bin/tmux",
)


def resolve_tmux_bin(preferred: str) -> str:
    """Return an executable tmux path, or raise with what was searched."""
    if os.path.sep in preferred:
        if os.access(preferred, os.X_OK):
            return preferred
        raise SystemExit(f"ORRERY: tmux not executable at {preferred}")
    found = shutil.which(preferred)
    if found:
        return found
    for candidate in TMUX_FALLBACK_PATHS:
        if os.access(candidate, os.X_OK):
            return candidate
    searched = os.environ.get("PATH", "") or "(empty PATH)"
    raise SystemExit(
        f"ORRERY: cannot find '{preferred}'.\n"
        f"  PATH searched: {searched}\n"
        f"  also tried: {', '.join(TMUX_FALLBACK_PATHS)}\n"
        "  Install tmux, or set TMUX_BIN to its absolute path.\n"
        "  (A GUI launch inherits a minimal PATH — this is the usual cause.)"
    )


def list_tmux_sessions(tmux_bin: str) -> list[dict[str, Any]]:
    """Return the protocol-v2 session roster from tmux."""
    result = subprocess.run(
        [tmux_bin, "list-sessions", "-F", SESSION_FORMAT],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        # An empty tmux server reports an error rather than an empty result.
        # Treat that ordinary state as an empty roster.
        if not result.stdout.strip():
            return []
        raise RuntimeError(result.stderr.strip() or "tmux list-sessions failed")

    interactive = _interactive_sessions(tmux_bin)
    sessions: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) != 4:
            continue
        session, attached, windows, created = fields
        try:
            sessions.append(
                {
                    "session": session,
                    "attached": int(attached) > 0,
                    "windows": int(windows),
                    "created": int(created),
                    # AUTO claim signal: without a human terminal attached the
                    # tmux size is a meaningless default, so the cockpit fits
                    # the pane to its own viewport; a Ghostty appearing flips
                    # this and the cockpit auto-releases back to follow.
                    "interactive": session in interactive,
                }
            )
        except ValueError:
            continue
    return sessions


def pane_tmux_session(tmux_bin: str, pane_id: str) -> str | None:
    """Resolve a pane's current session name for destructive-op checks."""
    result = subprocess.run(
        [
            tmux_bin,
            "display-message",
            "-p",
            "-t",
            pane_id,
            "#{session_name}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    session = result.stdout.strip()
    return session or None


class WebSocketPeer:
    """Small adapter giving aiohttp websockets the send API used by the bridge."""

    def __init__(self, response: web.WebSocketResponse) -> None:
        self.response = response
        self._send_lock = asyncio.Lock()

    async def send(self, data: str) -> None:
        async with self._send_lock:
            await self.response.send_str(data)

    async def send_json(self, payload: dict[str, Any]) -> None:
        await self.send(json.dumps(payload, ensure_ascii=False))


@dataclass(frozen=True)
class WindowSizeSnapshot:
    """tmux window state captured immediately before ORRERY first claims it."""

    local_option: str | None
    width: int
    height: int


class SessionTmuxBridge(TmuxControlBridge):
    """The proven v1 bridge, scoped to one named v2 session."""

    async def broadcast(self, payload: dict[str, Any]) -> None:
        event = dict(payload)
        event.setdefault("session", self.config.session)
        await super().broadcast(event)

    async def send_json(self, websocket: Any, payload: dict[str, Any]) -> None:
        event = dict(payload)
        event.setdefault("session", self.config.session)
        await super().send_json(websocket, event)

    async def capture_window_size(self, window_id: str) -> WindowSizeSnapshot | None:
        """Capture local policy presence/value and exact grid before a claim."""
        option = await self.send_command(
            ["show-window-options", "-v", "-t", window_id, "window-size"],
            wait=True,
        )
        size = await self.send_command(
            [
                "display-message",
                "-p",
                "-t",
                window_id,
                "#{window_width}\t#{window_height}",
            ],
            wait=True,
        )
        if option is None or not option.ok or size is None or not size.ok or not size.lines:
            return None
        fields = size.lines[0].split("\t")
        if len(fields) != 2:
            return None
        try:
            width, height = int(fields[0]), int(fields[1])
        except ValueError:
            return None
        local_option = option.lines[0].strip() if option.lines else None
        return WindowSizeSnapshot(local_option or None, width, height)

    async def restore_window_size(
        self,
        window_id: str,
        snapshot: WindowSizeSnapshot,
    ) -> bool:
        """Restore one ORRERY-owned window to its exact pre-claim state."""
        resized = await self.send_command(
            [
                "resize-window",
                "-t",
                window_id,
                "-x",
                str(snapshot.width),
                "-y",
                str(snapshot.height),
            ],
            wait=True,
        )
        if resized is None or not resized.ok:
            return False

        refreshed = await self.send_command(
            [
                "refresh-client",
                "-C",
                f"{window_id}:{snapshot.width}x{snapshot.height}",
            ],
            wait=True,
        )
        if refreshed is None or not refreshed.ok:
            return False

        option_args = ["set-option", "-w", "-t", window_id]
        if snapshot.local_option is None:
            option_args.extend(["-u", "window-size"])
        else:
            option_args.extend(["window-size", snapshot.local_option])
        restored = await self.send_command(option_args, wait=True)
        if restored is None or not restored.ok:
            return False

        for pane in self.panes.values():
            if pane.window_id == window_id:
                self._schedule_pane_resync(pane.pane_id)
        return True


@dataclass
class SessionState:
    bridge: SessionTmuxBridge
    claimed_windows: dict[str, WindowSizeSnapshot] = field(default_factory=dict)
    claim_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SessionBridgeManager:
    """Keep one recording tmux control connection alive per live session."""

    def __init__(
        self,
        tmux_bin: str,
        history_dir: Path | None = None,
    ) -> None:
        self.tmux_bin = tmux_bin
        self.history_dir = history_dir or history_directory()
        self.states: dict[str, SessionState] = {}
        self._lock = asyncio.Lock()
        self._closed = False
        self._roster_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self._prune_history()
        await self._reconcile_sessions()
        async with self._lock:
            if not self._closed and self._roster_task is None:
                self._roster_task = asyncio.create_task(self._roster_loop())

    async def _prune_history(self) -> None:
        live_sessions: set[str] | None
        try:
            sessions = await asyncio.to_thread(list_tmux_sessions, self.tmux_bin)
            live_sessions = {item["session"] for item in sessions}
        except (OSError, RuntimeError):
            live_sessions = None
        try:
            await asyncio.to_thread(
                prune_history_files,
                self.history_dir,
                live_sessions,
            )
        except Exception as exc:
            print(
                f"ORRERY history retention failed: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )

    async def _roster_loop(self) -> None:
        while True:
            await asyncio.sleep(RECORDER_ROSTER_SECONDS)
            await self._reconcile_sessions()

    async def _reconcile_sessions(self) -> None:
        try:
            sessions = await asyncio.to_thread(list_tmux_sessions, self.tmux_bin)
        except (OSError, RuntimeError):
            return
        live_sessions = {
            item["session"]: item["created"]
            for item in sessions
        }

        async with self._lock:
            if self._closed:
                return
            stale_states = [
                self.states.pop(session)
                for session, state in list(self.states.items())
                if session not in live_sessions
                or state.bridge.process is None
                or state.bridge.process.poll() is not None
            ]

        if stale_states:
            await asyncio.gather(
                *(self._stop_bridge(state) for state in stale_states),
                return_exceptions=True,
            )

        for session, session_created in sorted(live_sessions.items()):
            try:
                await self._ensure_bridge(session, session_created)
            except Exception as exc:
                print(
                    f"ORRERY recorder failed to attach {session!r}: "
                    f"{type(exc).__name__}",
                    file=sys.stderr,
                    flush=True,
                )

    async def _ensure_bridge(
        self,
        session: str,
        session_created: int | None = None,
    ) -> SessionState | None:
        async with self._lock:
            if self._closed:
                return None
            state = self.states.get(session)
            if state is not None:
                return state

            bridge = SessionTmuxBridge(
                ControlConfig(
                    host=DEFAULT_HOST,
                    port=0,
                    session=session,
                    tmux_bin=self.tmux_bin,
                    session_created=session_created,
                    history_dir=self.history_dir,
                )
            )
            try:
                await bridge.start()
            except BaseException:
                await bridge.stop()
                raise
            state = SessionState(bridge=bridge)
            self.states[session] = state
            return state

    async def attach(
        self,
        peer: WebSocketPeer,
        attached: set[str],
        session: str,
    ) -> None:
        if session in attached:
            state = self.states.get(session)
            if state is not None and peer in state.bridge.clients:
                await state.bridge.send_snapshot(peer)
                return
            attached.discard(session)

        if len(attached) >= MAX_CLIENT_SESSIONS:
            await send_error(
                peer,
                session,
                f"maximum {MAX_CLIENT_SESSIONS} attached sessions per client",
            )
            return

        try:
            exists = await asyncio.to_thread(
                tmux_session_exists, self.tmux_bin, session
            )
        except OSError:
            exists = False
        if not exists:
            await send_error(peer, session, f"tmux session not found: {session}")
            return

        try:
            state = await self._ensure_bridge(session)
        except Exception as exc:
            await send_error(
                peer,
                session,
                f"failed to attach tmux session: {type(exc).__name__}",
            )
            return
        if state is None:
            await send_error(peer, session, "backend is shutting down")
            return

        async with self._lock:
            if self.states.get(session) is not state:
                await send_error(peer, session, f"tmux session not found: {session}")
                return
            state.bridge.clients.add(peer)
            state.bridge.client_locks.setdefault(peer, asyncio.Lock())
            attached.add(session)

        try:
            await state.bridge.send_snapshot(peer)
        except Exception:
            await self.detach(peer, attached, session)
            raise

    async def detach(
        self,
        peer: WebSocketPeer,
        attached: set[str],
        session: str,
    ) -> None:
        # The recorder survives browser detach, so restore only windows that
        # this ORRERY session actually claimed before removing its final peer.
        async with self._lock:
            state = self.states.get(session)
        if (
            state is not None
            and peer in state.bridge.clients
            and len(state.bridge.clients) == 1
        ):
            await self._restore_claimed_windows(state)

        attached.discard(session)
        async with self._lock:
            if state is not None and self.states.get(session) is state:
                state.bridge.clients.discard(peer)
                state.bridge.client_locks.pop(peer, None)

    async def disconnect(
        self,
        peer: WebSocketPeer,
        attached: set[str],
    ) -> None:
        for session in list(attached):
            await self.detach(peer, attached, session)

    async def handle_message(
        self,
        peer: WebSocketPeer,
        attached: set[str],
        payload: dict[str, Any],
    ) -> None:
        message_type = payload.get("type")

        if message_type in {"attach", "detach", "refresh"}:
            session = payload.get("session")
            if not isinstance(session, str) or not session:
                await send_error(peer, None, "session must be a non-empty string")
                return
            if message_type == "attach":
                await self.attach(peer, attached, session)
            elif message_type == "detach":
                await self.detach(peer, attached, session)
            else:
                state = self.states.get(session)
                if session not in attached or state is None:
                    await send_error(peer, session, "session is not attached")
                    return
                await state.bridge.refresh_panes(send_captures=True)
            return

        if message_type not in {"input", "resize", "release", "split", "close"}:
            await send_error(peer, None, "unsupported message type")
            return

        pane_id = payload.get("paneId")
        if not isinstance(pane_id, str):
            await send_error(peer, None, "paneId must be a string")
            return

        state = self._find_attached_pane(attached, pane_id)
        if state is None:
            await send_error(peer, None, f"pane is not attached: {pane_id}")
            return

        session = state.bridge.config.session
        if message_type in {"split", "close"}:
            try:
                current_session = await asyncio.to_thread(
                    pane_tmux_session, self.tmux_bin, pane_id
                )
            except OSError:
                current_session = None
            if current_session is None:
                await send_error(peer, session, f"pane no longer exists: {pane_id}")
                return
            session = current_session
            if not session.startswith("orrery-"):
                await send_error(
                    peer,
                    session,
                    "refusing destructive op on non-test session",
                )
                return

        if message_type == "resize":
            cols = payload.get("cols")
            rows = payload.get("rows")
            pane = state.bridge.panes.get(pane_id)
            if pane is not None and isinstance(cols, int) and isinstance(rows, int):
                claimed = await self._claim_window(
                    state,
                    payload,
                    pane.window_id,
                    cols,
                    rows,
                )
                if not claimed:
                    await send_error(peer, session, "failed to claim tmux window")
                return

        if message_type == "release":
            pane = state.bridge.panes.get(pane_id)
            if pane is not None:
                await self._restore_claimed_windows(state, {pane.window_id})
            return

        await state.bridge.handle_client_message(payload)

    @staticmethod
    async def _claim_window(
        state: SessionState,
        payload: dict[str, Any],
        window_id: str,
        cols: int,
        rows: int,
    ) -> bool:
        async with state.claim_lock:
            created_snapshot = window_id not in state.claimed_windows
            if created_snapshot:
                snapshot = await state.bridge.capture_window_size(window_id)
                if snapshot is None:
                    return False
                state.claimed_windows[window_id] = snapshot

            await state.bridge.handle_client_message(payload)
            result = await state.bridge.send_command(
                [
                    "resize-window",
                    "-t",
                    window_id,
                    "-x",
                    str(max(1, cols)),
                    "-y",
                    str(max(1, rows)),
                ],
                wait=True,
            )
            if result is not None and result.ok:
                return True

            if created_snapshot:
                snapshot = state.claimed_windows[window_id]
                try:
                    restored = await state.bridge.restore_window_size(
                        window_id,
                        snapshot,
                    )
                except (OSError, RuntimeError, asyncio.TimeoutError):
                    restored = False
                if restored:
                    state.claimed_windows.pop(window_id, None)
            return False

    @staticmethod
    async def _restore_claimed_windows(
        state: SessionState,
        window_ids: set[str] | None = None,
    ) -> None:
        async with state.claim_lock:
            targets = [
                (window_id, snapshot)
                for window_id, snapshot in state.claimed_windows.items()
                if window_ids is None or window_id in window_ids
            ]
            for window_id, snapshot in targets:
                try:
                    restored = await state.bridge.restore_window_size(
                        window_id,
                        snapshot,
                    )
                except (OSError, RuntimeError, asyncio.TimeoutError):
                    restored = False
                if restored:
                    state.claimed_windows.pop(window_id, None)

    def _find_attached_pane(
        self,
        attached: set[str],
        pane_id: str,
    ) -> SessionState | None:
        for session in attached:
            state = self.states.get(session)
            if state is not None and pane_id in state.bridge.panes:
                return state
        return None

    @staticmethod
    async def _stop_bridge(state: SessionState) -> None:
        # Restore only ORRERY-owned windows while the control client is alive.
        await SessionBridgeManager._restore_claimed_windows(state)
        if state.claimed_windows:
            remaining = ", ".join(sorted(state.claimed_windows))
            print(
                f"ORRERY window-size restore incomplete for "
                f"{state.bridge.config.session!r}: {remaining}",
                file=sys.stderr,
                flush=True,
            )
        await state.bridge.stop()

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            roster_task = self._roster_task
            self._roster_task = None
            states = list(self.states.values())
            self.states.clear()
        if roster_task is not None:
            roster_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await roster_task
        await asyncio.gather(
            *(self._stop_bridge(state) for state in states),
            return_exceptions=True,
        )


BRIDGE_MANAGER_KEY = web.AppKey("bridge_manager", SessionBridgeManager)


async def send_error(
    peer: WebSocketPeer,
    session: str | None,
    message: str,
) -> None:
    payload: dict[str, Any] = {"type": "error", "message": message}
    if session is not None:
        payload["session"] = session
    await peer.send_json(payload)


# The polled routes: every cockpit tab and pane window asks for these every few
# seconds with the same query. While one is on its way to the dashboard, the
# same request from another tab shares its answer instead of starting a second
# computation there (the dashboard computes these in seconds, and computations
# that overlap slow each other down). Nothing is kept once the answer is in:
# a request that comes after it goes to the dashboard as before.
COALESCED_ROUTES = frozenset({"/telemetry/agents", "/telemetry/graph", "/telemetry/messages"})


async def fetch_proxied(
    http_session: ClientSession, path: str, url: str
) -> tuple[bytes, int, str]:
    """One upstream GET for proxy_dashboard: (body, status, content type).
    Raises ClientError / asyncio.TimeoutError when the dashboard does not answer."""
    async with http_session.get(url) as response:
        body = await response.read()
        status = response.status
        content_type = response.headers.get("Content-Type", "application/octet-stream")
    if path == "/telemetry/agents" and status == 200:
        labels = await annotations_by_agent(http_session)
        body = merge_agent_annotations(body, labels)
    if path == "/telemetry/spawn-catalog" and status == 200:
        body = merge_spawn_catalog(body)
    return body, status, content_type


def shared_fetch(
    inflight: dict[str, "asyncio.Task[tuple[bytes, int, str]]"],
    http_session: ClientSession,
    path: str,
    url: str,
) -> "asyncio.Task[tuple[bytes, int, str]]":
    """The fetch for `url` already on its way, or a new one. The task is not
    tied to the request that started it, so a tab that closes mid-request
    does not cancel the answer the others wait for."""
    task = inflight.get(url)
    if task is None:
        task = asyncio.create_task(fetch_proxied(http_session, path, url))
        inflight[url] = task

        def done(finished: asyncio.Task) -> None:
            if inflight.get(url) is finished:
                del inflight[url]
            if not finished.cancelled():
                finished.exception()  # retrieved, even when every waiter has gone

        task.add_done_callback(done)
    return task


async def proxy_dashboard(request: web.Request) -> web.Response:
    dash_path, allowed = PROXY_ROUTES[request.path]
    kept = {
        key: request.query[key]
        for key in allowed
        if key in request.query and request.query[key]
    }
    url = DASHBOARD_URL + dash_path
    if kept:
        url += "?" + urlencode(kept)

    http_session = request.app[HTTP_SESSION_KEY]
    try:
        if request.path in COALESCED_ROUTES:
            task = shared_fetch(request.app[PROXY_INFLIGHT_KEY], http_session, request.path, url)
            body, status, content_type = await asyncio.shield(task)
        else:
            body, status, content_type = await fetch_proxied(http_session, request.path, url)
        return web.Response(
            body=body,
            status=status,
            headers={
                "Content-Type": content_type,
                "Cache-Control": "no-store",
            },
        )
    except asyncio.TimeoutError:
        # it is there but did not answer in time (a heavy graph, many tabs):
        # the cockpit says "slow" rather than sending people to restart it
        return web.json_response(
            {"error": "dashboard slow"},
            status=502,
        )
    except ClientError:
        return web.json_response(
            {"error": "dashboard offline"},
            status=502,
        )


async def proxy_spawn(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response(
            {"error": "body must be a JSON object"},
            status=400,
        )
    if not isinstance(payload, dict):
        return web.json_response(
            {"error": "body must be a JSON object"},
            status=400,
        )

    http_session = request.app[HTTP_SESSION_KEY]
    try:
        # The shared session's 6-second budget fits status polls, not spawns:
        # preregister + tmux + Ghostty routinely run longer, and cutting the
        # response off mid-spawn showed the user "offline" while the dashboard
        # went on to finish the spawn successfully (2026-08-13, IcyOstwald).
        async with http_session.post(
            DASHBOARD_URL + "/api/spawn",
            json=payload,
            timeout=ClientTimeout(total=90),
        ) as response:
            body = await response.read()
            content_type = response.headers.get(
                "Content-Type", "application/octet-stream"
            )
            return web.Response(
                body=body,
                status=response.status,
                headers={
                    "Content-Type": content_type,
                    "Cache-Control": "no-store",
                },
            )
    except asyncio.TimeoutError:
        return web.json_response(
            {"error": "spawn still running after 90s — check the roster before retrying"},
            status=504,
        )
    except ClientError:
        return web.json_response(
            {"error": "dashboard offline"},
            status=502,
        )


# Let static responses (portraits, logos) keep the upstream Cache-Control.
# Stamping no-store on everything threw away the max-age=86400 the dashboard
# sets, so the embedded UI re-fetched every 38KB portrait on each repaint.
# API responses stay no-store.
_CACHEABLE_PREFIXES = ("/assets/", "/portrait")


def cache_control_for(request: web.Request, response: Any) -> str:
    path = request.path
    if request.method == "GET" and any(
        path == prefix.rstrip("/") or path.startswith(prefix)
        for prefix in _CACHEABLE_PREFIXES
    ):
        upstream = response.headers.get("Cache-Control")
        if upstream:
            return upstream
    return "no-store"


async def proxy_dashboard_passthrough(request: web.Request) -> web.Response:
    """Same-origin embed support: forward /network/*, /api/*, /assets/* to :8770.

    The NETWORK tab iframes `/network/?embed=1`; the dashboard page fetches
    absolute `/api/...` + `/assets/...` paths, which land here and are relayed
    verbatim so the embedded UI is fully same-origin with the cockpit.
    """
    tail = request.match_info.get("tail", "")
    if request.path == "/network" or request.path.startswith("/network/"):
        target = "/" + tail
    else:
        target = request.path
    url = DASHBOARD_URL + target
    if request.query_string:
        url += "?" + request.query_string
    body = await request.read() if request.method == "POST" else None
    headers = {}
    content_type = request.headers.get("Content-Type")
    if content_type:
        headers["Content-Type"] = content_type
    http_session = request.app[HTTP_SESSION_KEY]
    try:
        async with http_session.request(
            request.method, url, data=body, headers=headers
        ) as response:
            payload = await response.read()
            content_type = response.headers.get(
                "Content-Type", "application/octet-stream"
            )
            payload = inject_telemetry_light(payload, content_type)
            return web.Response(
                body=payload,
                status=response.status,
                headers={
                    "Content-Type": content_type,
                    "Cache-Control": cache_control_for(request, response),
                },
            )
    except (ClientError, asyncio.TimeoutError):
        return web.json_response({"error": "dashboard offline"}, status=502)


# The cockpit has always posted its colour theme at the NETWORK iframe and
# waited for an acknowledgement.  Whether anything answers depends on which
# dashboard clone is running behind the proxy, and the one in daily use has no
# theme system at all — so light mode stopped at the iframe boundary.
#
# Injecting the receiver here rather than shipping it in the dashboard means it
# reaches whichever clone is behind the proxy.  The sentinel is the contract the
# cockpit already speaks: a clone that answers for itself contains the reply
# type, and is left alone.
_TELEMETRY_LIGHT_SENTINEL = b"orrery-color-theme-ready"
_TELEMETRY_LIGHT_TAG = (
    b'<link rel="stylesheet" href="/telemetry_light.css">'
    b'<script src="/telemetry_light.js"></script>'
)


def inject_telemetry_light(payload: bytes, content_type: str) -> bytes:
    if "html" not in content_type.lower():
        return payload
    if _TELEMETRY_LIGHT_SENTINEL in payload:
        return payload
    # Appended at </body> so the dashboard's own scripts have defined whatever
    # they define first; the receiver only touches custom properties on :root.
    marker = b"</body>"
    index = payload.rfind(marker)
    if index == -1:
        return payload + _TELEMETRY_LIGHT_TAG
    return payload[:index] + _TELEMETRY_LIGHT_TAG + payload[index:]


# The two CLIs invoke a skill differently, and the composer must not offer one
# vocabulary while talking to the other: Claude reads `/log`, Codex reads
# `$log` and treats a leading `/` as one of its own builtins — so `/log` sent
# to Codex lands on /logout. Same name, opposite meaning, no warning.
SKILL_SOURCES = {
    "claude": {"dir": os.path.expanduser("~/.claude/skills"), "prefix": "/"},
    "codex": {"dir": os.path.expanduser("~/.codex/skills"), "prefix": "$"},
    # Gemini CLI keeps Agent Skills as ~/.gemini/skills/<name>/SKILL.md and
    # runs them with the same slash as Claude.
    "gemini": {"dir": os.path.expanduser("~/.gemini/skills"), "prefix": "/"},
}
SKILLS_DIR = SKILL_SOURCES["claude"]["dir"]  # kept: older callers import this
# Composer autocomplete: REPL builtins each TUI understands besides skills.
# Both CLIs take builtins with a leading slash; only the skill prefix differs.
_BUILTIN_SLASH = {
    "claude": (
        {"name": "compact", "kind": "builtin", "description": "コンテキストを要約して圧縮"},
        {"name": "clear", "kind": "builtin", "description": "会話をクリアして新規開始"},
        {"name": "model", "kind": "builtin", "description": "モデルを切り替え"},
        {"name": "mcp", "kind": "builtin", "description": "MCP 接続の状態・再接続"},
        {"name": "resume", "kind": "builtin", "description": "過去セッションを再開"},
        {"name": "help", "kind": "builtin", "description": "ヘルプ"},
    ),
    "codex": (
        {"name": "compact", "kind": "builtin", "description": "コンテキストを要約して圧縮"},
        {"name": "new", "kind": "builtin", "description": "新しい会話を開始"},
        {"name": "model", "kind": "builtin", "description": "モデル・推論強度を切り替え"},
        {"name": "approvals", "kind": "builtin", "description": "承認モードを切り替え"},
        {"name": "status", "kind": "builtin", "description": "セッションの状態を表示"},
        {"name": "help", "kind": "builtin", "description": "ヘルプ"},
    ),
    "gemini": (
        {"name": "compress", "kind": "builtin", "description": "コンテキストを要約して圧縮"},
        {"name": "clear", "kind": "builtin", "description": "画面と履歴をクリア"},
        {"name": "model", "kind": "builtin", "description": "モデルを切り替え"},
        {"name": "mcp", "kind": "builtin", "description": "MCP サーバーの状態"},
        {"name": "stats", "kind": "builtin", "description": "セッションの統計を表示"},
        {"name": "help", "kind": "builtin", "description": "ヘルプ"},
    ),
}
_SKILLS_CACHE_SECONDS = 30.0
_skills_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}


def _read_skill_description(md_path: str) -> str:
    """First `description:` frontmatter line (or first h1) from a SKILL.md."""
    try:
        with open(md_path, encoding="utf-8", errors="replace") as handle:
            head = [handle.readline() for _ in range(30)]
    except OSError:
        return ""
    for line in head:
        stripped = line.strip()
        if stripped.lower().startswith("description:"):
            return stripped.split(":", 1)[1].strip().strip('"')
    for line in head:
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


async def serve_fs_dirs(request: web.Request) -> web.Response:
    """List subdirectories for the spawn modal's directory browser.

    Localhost-only convenience: lets the NEW AGENT modal navigate the
    filesystem like a file manager instead of hand-typing absolute paths.
    Directories only, hidden entries skipped, capped at 200.
    """
    raw = request.query.get("path", "~")
    path = os.path.realpath(os.path.expanduser(raw))
    if not os.path.isdir(path):
        return web.json_response({"error": f"not a directory: {path}"}, status=400)
    dirs: list[dict[str, str]] = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                if entry.name.startswith("."):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=True):
                        dirs.append({"name": entry.name, "path": entry.path})
                except OSError:
                    continue
    except OSError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    dirs.sort(key=lambda d: d["name"].lower())
    parent = os.path.dirname(path)
    return web.json_response({
        "path": path,
        "parent": parent if parent != path else None,
        "dirs": dirs[:200],
        "truncated": len(dirs) > 200,
    })


def _collect_skills(root: str) -> list[dict[str, str]]:
    """`<root>/<name>/SKILL.md` entries, plus Codex's bundled `.system/<name>`."""
    found: list[dict[str, str]] = []
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return found
    for entry in entries:
        if entry == ".system":
            for builtin in sorted(os.listdir(os.path.join(root, entry)) or []):
                md_path = os.path.join(root, entry, builtin, "SKILL.md")
                if os.path.isfile(md_path):
                    found.append({
                        "name": builtin,
                        "kind": "bundled",
                        "description": _read_skill_description(md_path),
                    })
            continue
        if entry.startswith("."):
            continue
        md_path = os.path.join(root, entry, "SKILL.md")
        if os.path.isfile(md_path):
            found.append({
                "name": entry,
                "kind": "skill",
                "description": _read_skill_description(md_path),
            })
    return found


async def serve_skills(request: web.Request) -> web.Response:
    """Slash-completions for the composer, for one program's vocabulary.

    `?program=claude|codex`. The response carries the prefix the caller must
    put in front of a skill name, so the composer never has to hardcode which
    CLI uses which sigil.
    """
    program = str(request.query.get("program") or "claude").lower()
    if program not in SKILL_SOURCES:
        program = "claude"
    source = SKILL_SOURCES[program]
    now = time.monotonic()
    cached = _skills_cache.get(program)
    if cached and now - cached[0] < _SKILLS_CACHE_SECONDS:
        items = cached[1]
    else:
        items = [dict(entry) for entry in _BUILTIN_SLASH[program]]
        items.extend(_collect_skills(source["dir"]))
        _skills_cache[program] = (now, items)
    return web.json_response({
        "program": program,
        "prefix": source["prefix"],
        "skills": items,
    })


# A browser never learns where a pasted file lives — the File object carries a
# name and bytes, never a path — so a Finder copy cannot become something an
# agent can open. The backend is on the same machine as the Finder that did the
# copying, and the pasteboard does carry the path, so it reads it here.
#
# Per-item `public.file-url`, not NSFilenamesPboardType: the latter is the
# deprecated route and returns nils on macOS 15 (measured 2026-08-06), and
# `readObjectsForClasses:` collapsed a two-file copy to one.
# The reply carries `changeCount` as well as the paths, because "no files on
# the pasteboard" and "this process cannot see the pasteboard" otherwise
# arrive as the same empty list. A process that has lost its window-server
# session reports no change count at all; a live one reports a large
# monotonic integer. A backend orphaned by the app that spawned it drifts into
# the first state and then quietly answers "clipboard is empty" forever
# (2026-08-24: an 8-day-old sidecar returned [] for a pasteboard that a fresh
# one read correctly).
_CLIPBOARD_FILES_JXA = """
ObjC.import("AppKit");
const pb = $.NSPasteboard.generalPasteboard;
const items = pb.pasteboardItems;
const out = [];
if (!items.isNil()) {
  for (let i = 0; i < items.count; i++) {
    const s = items.objectAtIndex(i).stringForType("public.file-url");
    if (!s.isNil()) {
      const p = $.NSURL.URLWithString(s).path;
      if (!p.isNil()) out.push(ObjC.unwrap(p));
    }
  }
}
JSON.stringify({changeCount: Number(pb.changeCount) || 0, files: out});
"""


# --- the Windows clipboard, read from WSL (2026-09-29) ------------------------
# Under WSL the cockpit is shown in a Windows browser, so the file or the
# screenshot was copied on Windows and the agent that must open it lives in
# the distro. Windows PowerShell (always present, unlike pwsh) reads the
# clipboard: a file copy comes back as Windows paths that `wslpath -u` turns
# into paths the agent can open; image data (Win+Shift+S) is saved as a PNG in
# the distro and its path is what gets pasted, because the TUI inside WSL
# cannot read the Windows clipboard the way it reads the Mac's on ^V.
#
# The script travels as -EncodedCommand (UTF-16LE base64) because the WSL
# interop re-quotes arguments, and it answers in tab-separated lines with the
# console forced to UTF-8, since the default code page (cp932 on a Japanese
# Windows) mangles non-ASCII file names. SessionId 0 is the non-interactive
# service session a backend started over ssh ends up in: its clipboard is not
# the user's, so an empty answer from there is "cannot see", not "empty".
# (It is a hint, not proof of how the backend was started: ssh is the case
# seen so far.) A clipboard that holds neither files nor an image answers
# empty; a failure inside the script exits non-zero with its message.
_WINDOWS_CLIPBOARD_PS = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try {
  [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
  Add-Type -AssemblyName System.Drawing
  Write-Output ("S`t" + [System.Diagnostics.Process]::GetCurrentProcess().SessionId)
  $files = @(Get-Clipboard -Format FileDropList | ForEach-Object { $_.FullName })
  foreach ($f in $files) { if ($f) { Write-Output ("F`t" + $f) } }
  if ($files.Count -eq 0) {
    $img = Get-Clipboard -Format Image
    if ($img) {
      $ms = New-Object System.IO.MemoryStream
      $img.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
      Write-Output ("I`t" + [Convert]::ToBase64String($ms.ToArray()))
    }
  }
} catch {
  [Console]::Error.WriteLine($_.Exception.Message)
  exit 1
}
"""
WINDOWS_CLIPBOARD_TIMEOUT = 10.0
CLIPBOARD_IMAGE_KEEP = 50
POWERSHELL_FALLBACK = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"


def windows_powershell() -> str | None:
    found = windows_exe("powershell.exe")
    if found:
        return found
    return POWERSHELL_FALLBACK if os.path.isfile(POWERSHELL_FALLBACK) else None


def windows_clipboard_problem() -> str | None:
    """Why the Windows clipboard cannot be read from here, or None if it can."""
    if not windows_powershell():
        return "powershell.exe is not reachable from WSL (Windows interop is off?)"
    if not shutil.which("wslpath"):
        return "wslpath is not on PATH"
    return None


def clipboard_image_dir() -> Path:
    configured = os.environ.get("ORRERY_CLIPBOARD_DIR", "").strip()
    if configured:
        folder = Path(configured).expanduser()
        if not folder.is_absolute():
            # the agent's cwd is not the backend's, so a relative path it is
            # handed would name a different file (or none)
            raise OSError(f"ORRERY_CLIPBOARD_DIR must be an absolute path: {configured}")
        return folder
    return Path(tempfile.gettempdir()) / f"orrery-clipboard-{os.getuid()}"


def private_clipboard_dir() -> Path:
    """The image folder, made or confirmed to be this user's own 0700 dir.

    A screenshot can hold anything on screen. The default name under /tmp is
    predictable, so an existing entry must be a real directory owned by us
    (never a symlink, never someone else's) and is tightened to 0700.
    """
    folder = clipboard_image_dir()
    folder.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(FileExistsError):
        folder.mkdir(mode=0o700)
    st = os.lstat(folder)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise OSError(f"{folder} is not a directory (a symlink?); refusing to save there")
    if st.st_uid != os.getuid():
        raise OSError(f"{folder} belongs to another user; refusing to save there")
    if stat.S_IMODE(st.st_mode) & 0o077:
        os.chmod(folder, 0o700)
    return folder


def save_clipboard_image(png: bytes) -> str:
    """Write a pasted image (0600) where the agent can open it; keep the newest."""
    folder = private_clipboard_dir()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = folder / f"clipboard-{stamp}-{os.urandom(3).hex()}.png"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(png)
    old = sorted(folder.glob("clipboard-*.png"), key=lambda p: p.stat().st_mtime,
                 reverse=True)[CLIPBOARD_IMAGE_KEEP:]
    for stale in old:
        with contextlib.suppress(OSError):
            stale.unlink()
    return str(target)


async def _run_reader(argv: list[str], timeout: float) -> tuple[int, bytes, bytes]:
    """Run a helper to completion; on timeout or cancel, kill and reap it.

    wait_for cancelling communicate() leaves the OS process running, so a hung
    PowerShell would otherwise stay behind and pile up with every retry.
    """
    proc = await asyncio.create_subprocess_exec(
        *argv, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except BaseException:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), timeout=2)
        raise
    return proc.returncode, stdout, stderr


async def _wslpath_u(windows_path: str) -> str | None:
    try:
        rc, stdout, stderr = await _run_reader(
            [shutil.which("wslpath") or "wslpath", "-u", windows_path], 4)
    except (OSError, asyncio.TimeoutError) as exc:
        print(f"[clipboard] wslpath could not run: {exc!r}", file=sys.stderr, flush=True)
        return None
    converted = stdout.decode("utf-8", "replace").strip()
    if rc != 0 or not converted:
        print(f"[clipboard] wslpath -u {windows_path!r} failed: "
              f"{stderr.decode('utf-8', 'replace').strip()!r}", file=sys.stderr, flush=True)
        return None
    return converted


async def read_windows_clipboard() -> dict[str, Any]:
    """The /telemetry/clipboard/files answer on WSL (same shape as the Mac's)."""
    problem = windows_clipboard_problem()
    if problem:
        return {"files": [], "error": "clipboard_unsupported", "detail": problem}
    script = base64.b64encode(_WINDOWS_CLIPBOARD_PS.encode("utf-16-le")).decode("ascii")
    try:
        rc, stdout, stderr = await _run_reader(
            [windows_powershell(), "-NoProfile", "-NonInteractive", "-STA",
             "-EncodedCommand", script],
            WINDOWS_CLIPBOARD_TIMEOUT)
    except (OSError, asyncio.TimeoutError) as exc:
        print(f"[clipboard] powershell could not run: {exc!r}", file=sys.stderr, flush=True)
        return {"files": [], "error": "clipboard_unavailable"}
    detail = stderr.decode("utf-8", "replace").strip()
    if rc != 0:
        print(f"[clipboard] powershell failed rc={rc} stderr={detail!r}",
              file=sys.stderr, flush=True)
        return {"files": [], "error": "clipboard_unreadable", "detail": detail[:400]}
    session, windows_paths, image = None, [], ""
    for line in stdout.decode("utf-8-sig", "replace").splitlines():
        tag, _, value = line.rstrip("\r").partition("\t")
        if tag == "S":
            session = value.strip()
        elif tag == "F" and value:
            windows_paths.append(value)
        elif tag == "I" and value:
            image = value.strip()
    files, skipped = [], []
    for windows_path in windows_paths:
        converted = await _wslpath_u(windows_path)
        if converted:
            files.append(converted)
        else:
            skipped.append(windows_path)
    if files:
        return {"files": files, "skipped": skipped} if skipped else {"files": files}
    if windows_paths:
        return {"files": [], "error": "clipboard_unreadable",
                "detail": "wslpath could not convert: " + "; ".join(windows_paths)[:300]}
    if image:
        try:
            saved = save_clipboard_image(base64.b64decode(image, validate=True))
        except (ValueError, OSError) as exc:
            print(f"[clipboard] could not save the pasted image: {exc}",
                  file=sys.stderr, flush=True)
            return {"files": [], "error": "clipboard_unreadable",
                    "detail": f"could not save the image: {exc}"[:400]}
        return {"files": [saved], "image": True}
    if session == "0":
        print("[clipboard] powershell runs in Windows session 0 (no desktop) — "
              "start the backend from WSL in the logged-in Windows desktop "
              "(e.g. Windows Terminal), not over ssh",
              file=sys.stderr, flush=True)
        return {"files": [], "error": "clipboard_no_session"}
    return {"files": []}


async def serve_clipboard_files(request: web.Request) -> web.Response:
    """Absolute paths of files on the macOS pasteboard or, under WSL, the
    Windows clipboard (may be []).

    "the reader failed" and "the clipboard holds no files" are different
    answers and must not share a response: the old code sent stderr to
    /dev/null and read empty stdout as ``[]``, so a reader that could not
    reach the pasteboard at all looked exactly like an empty clipboard, and
    the composer told the user there was nothing to paste (2026-08-24).
    """
    if host_kind() == "wsl":
        return web.json_response(await read_windows_clipboard())
    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-l", "JavaScript", "-e", _CLIPBOARD_FILES_JXA,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=4)
    except (OSError, asyncio.TimeoutError) as exc:
        print(f"[clipboard] reader could not run: {exc}", file=sys.stderr,
              flush=True)
        return web.json_response({"files": [], "error": "clipboard_unavailable"})
    detail = stderr.decode("utf-8", "replace").strip()
    raw = stdout.decode("utf-8", "replace").strip()
    if proc.returncode != 0 or not raw:
        print(f"[clipboard] reader failed rc={proc.returncode} "
              f"stdout={raw!r} stderr={detail!r}", file=sys.stderr, flush=True)
        return web.json_response(
            {"files": [], "error": "clipboard_unreadable", "detail": detail[:400]},
            status=200,
        )
    try:
        parsed = json.loads(raw)
    except ValueError:
        print(f"[clipboard] reader returned non-JSON: {raw!r}", file=sys.stderr,
              flush=True)
        return web.json_response({"files": [], "error": "clipboard_unreadable"})
    if isinstance(parsed, list):          # older reader, no change count
        paths, change_count = parsed, None
    else:
        paths = parsed.get("files") or []
        change_count = parsed.get("changeCount")
    files = [p for p in paths if isinstance(p, str) and p]
    if not files and change_count == 0:
        print("[clipboard] pasteboard reports no change count — this process "
              "has no window-server session; restart the backend",
              file=sys.stderr, flush=True)
        return web.json_response({"files": [], "error": "clipboard_no_session"})
    return web.json_response({"files": files})


def tmux_has_non_control_client(tmux_bin: str, session: str) -> bool:
    """Return whether an interactive client is already attached to a session."""
    result = subprocess.run(
        [
            tmux_bin,
            "list-clients",
            "-t",
            session,
            "-F",
            CLIENT_CONTROL_MODE_FORMAT,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "tmux list-clients failed")
    return any(line.strip() == "0" for line in result.stdout.splitlines())


# --- where the backend runs -------------------------------------------------
# One place decides the host, and every Mac-only feature asks it. "Is this
# WSL" and "can this WSL reach Windows programs" are separate answers: a WSL
# distro with interop or Windows' PATH turned off is still WSL, and must fail
# with a reason rather than fall through to the Mac or plain-Linux path. The
# checks mirror orrery-telemetry's dashboard (server.py _is_wsl/_auto_terminal)
# so the two never disagree about which terminal opens.

WINDOWS_EXE_FALLBACKS = {
    "explorer.exe": "/mnt/c/Windows/explorer.exe",
    "cmd.exe": "/mnt/c/Windows/System32/cmd.exe",
}


def _sys_platform() -> str:
    return sys.platform


def _proc_version() -> str:
    try:
        with open("/proc/version", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def is_wsl() -> bool:
    """True inside a WSL distro (the kernel string carries 'microsoft')."""
    return _sys_platform() == "linux" and "microsoft" in _proc_version().lower()


def wsl_distro() -> str:
    return os.environ.get("WSL_DISTRO_NAME", "").strip()


def windows_exe(name: str) -> str | None:
    """Path of a Windows program reachable from this WSL distro, or None."""
    found = shutil.which(name)
    if found:
        return found
    fallback = WINDOWS_EXE_FALLBACKS.get(name)
    if fallback and os.path.isfile(fallback):
        return fallback
    return None


def host_kind() -> str:
    """'mac', 'wsl' or 'linux'."""
    if _sys_platform() == "darwin":
        return "mac"
    return "wsl" if is_wsl() else "linux"


def wsl_terminal_problem() -> str | None:
    """Why a Windows Terminal tab cannot be opened from here, or None if it can."""
    if not wsl_distro():
        return "WSL_DISTRO_NAME is not set, so wsl.exe cannot be pointed back at this distro"
    if not shutil.which("wt.exe"):
        return "wt.exe (Windows Terminal) is not on PATH; install Windows Terminal or enable appendWindowsPath"
    return None


def host_platform() -> dict[str, Any]:
    """What the cockpit needs to know to label and route host features."""
    kind = host_kind()
    if kind == "wsl":
        problem = wsl_terminal_problem()
        terminal = {"kind": "wt", "label": "Windows Terminal",
                    "available": problem is None, "reason": problem}
        interop = bool(windows_exe("explorer.exe") or shutil.which("wslview"))
    else:
        # Mac and plain Linux keep the Ghostty route they always had.
        terminal = {"kind": "ghostty", "label": "Ghostty",
                    "available": True, "reason": None}
        interop = False
    return {
        "host": kind,
        "distro": wsl_distro() if kind == "wsl" else None,
        "windows_interop": interop,
        "terminal": terminal,
        # The macOS pasteboard reader, or Windows PowerShell under WSL.
        "file_paste": kind == "mac" or (kind == "wsl" and windows_clipboard_problem() is None),
    }


async def serve_platform(request: web.Request) -> web.Response:
    return web.json_response(host_platform())


_windows_user_cache: list[str] = []


def windows_user() -> str:
    """The Windows account name under WSL (its /mnt/c/Users/<name> shows up
    in paths), or "" elsewhere or when interop does not answer."""
    if _windows_user_cache:
        return _windows_user_cache[0]
    name = ""
    cmd = windows_exe("cmd.exe") if host_kind() == "wsl" else None
    if cmd:
        try:
            done = subprocess.run([cmd, "/d", "/c", "echo %USERNAME%"], capture_output=True,
                                  text=True, timeout=3, cwd="/")
            value = done.stdout.strip()
            if done.returncode == 0 and value and "%" not in value:
                name = value
        except (OSError, subprocess.SubprocessError):
            name = ""
    _windows_user_cache.append(name)
    return name


def demo_identity() -> dict[str, Any]:
    """The names demo mode hides on screen: the user name from $HOME (and the
    login name, and the Windows account under WSL) and the host name. Only the
    cockpit's own page asks for this, and only in demo mode."""
    home = os.environ.get("HOME") or str(Path.home())
    users = [Path(home).name]
    with contextlib.suppress(Exception):
        import getpass
        users.append(getpass.getuser())
    users.append(windows_user())
    import socket
    full = socket.gethostname()
    hosts = [full, full.split(".", 1)[0]]
    return {
        "home": home,
        "users": [u for u in dict.fromkeys(users) if u],
        "hosts": [h for h in dict.fromkeys(hosts) if h and h not in ("localhost", "")],
    }


async def serve_identity(request: web.Request) -> web.Response:
    return web.json_response(demo_identity(), headers={"Cache-Control": "no-store"})


def launch_ghostty(tmux_bin: str, session: str) -> None:
    """Launch a detached Ghostty client attached to the requested tmux session."""
    subprocess.Popen(
        [
            GHOSTTY_BIN,
            f"--title={session}",
            "-e",
            tmux_bin,
            "attach",
            "-t",
            session,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


WT_UNSAFE_SESSION_RE = re.compile(r"[;\s\"'`$\\]")


def launch_windows_terminal(tmux_bin: str, session: str) -> None:
    """Open a Windows Terminal tab that attaches back into this distro's tmux.

    wt.exe splits its own command line on ';' and the WSL interop re-quotes
    arguments, so a session name that either could reinterpret is refused
    with a reason instead of opening a tab that attaches to something else.
    """
    problem = wsl_terminal_problem()
    if problem:
        raise OSError(problem)
    if WT_UNSAFE_SESSION_RE.search(session):
        raise OSError(f"session name {session!r} cannot be passed through wt.exe")
    run_opener([
        "wt.exe", "-w", "0", "new-tab", "--title", session,
        "wsl.exe", "-d", wsl_distro(), "--exec", tmux_bin, "attach", "-t", session,
    ])


def launch_terminal(tmux_bin: str, session: str) -> None:
    """Open an interactive client on the session with the host's terminal."""
    if host_kind() == "wsl":
        launch_windows_terminal(tmux_bin, session)
    else:
        launch_ghostty(tmux_bin, session)


OPENER_WAIT_SECONDS = 5.0

# --- reaching Windows programs from WSL --------------------------------------
# A Windows program started from WSL talks back through the socket named in
# WSL_INTEROP (/run/WSL/<pid>_interop). A tmux server keeps the value from the
# terminal that started it; once that terminal closes, the socket is gone and
# every .exe fails with an interop error on stderr. explorer.exe's own exit
# status means nothing (it exits 1 after opening a window), so that stderr is
# the only sign — without reading it the cockpit said "opened" while nothing
# opened (2026-10-01 seminar, cockpit under WSL).
WSL_INTEROP_DIR = "/run/WSL"
BINFMT_DIR = "/proc/sys/fs/binfmt_misc"
WSL_INTEROP_FAILURE_RE = re.compile(
    r"UtilConnectToInteropServer|UtilBindVsockAnyPort|UtilAcceptVsock|"
    r"Exec format error|interop",
    re.IGNORECASE,
)


def _interop_socket_answers(path: str) -> bool:
    """A socket that accepts a connection right now. A socket file outlives
    the server that made it, so its existence proves nothing.

    WSL's init creates the interop socket as root before it drops to the
    user (and opens it to everyone), so root's is the normal owner; this
    user's is accepted too. Another user's, and a symlink, are not — the
    current value included."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid not in (0, os.getuid()):
        return False
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(0.5)
    try:
        probe.connect(path)
    except OSError:
        return False
    finally:
        probe.close()
    return True


def wsl_interop_env() -> dict[str, str]:
    """This process's environment with WSL_INTEROP naming a socket that answers.

    Kept when the current one answers, or when nothing better answers (WSL 1
    has no socket; a guess would not help). Otherwise the newest of this
    user's /run/WSL/*_interop sockets that accepts a connection is used. Any
    answering interop server can start a Windows program; whether it did is
    still judged by the program's own result (run_opener).
    """
    env = dict(os.environ)
    if _interop_socket_answers(env.get("WSL_INTEROP", "")):
        return env
    try:
        names = os.listdir(WSL_INTEROP_DIR)
    except OSError:
        return env
    candidates = []
    for name in names:
        path = os.path.join(WSL_INTEROP_DIR, name)
        if not name.endswith("_interop") or os.path.islink(path):
            continue
        with contextlib.suppress(OSError):
            candidates.append((os.stat(path).st_mtime, path))
    for _, path in sorted(candidates, reverse=True):
        if _interop_socket_answers(path):
            env["WSL_INTEROP"] = path
            break
    return env


def wsl_interop_problem() -> str | None:
    """Why this distro cannot run Windows programs at all, or None if it
    can (or if it cannot be told: binfmt_misc not readable)."""
    try:
        entries = os.listdir(BINFMT_DIR)
    except OSError:
        return None
    if not any(name.startswith("WSLInterop") for name in entries):
        return "Windows interop is turned off in this distro ([interop] enabled=false in /etc/wsl.conf)"
    return None


def run_opener(
    argv: list[str], *, trust_exit_status: bool = True, confirm: bool = False
) -> None:
    """Run `open`/`xdg-open` and raise OSError if it reports a failure.

    The opener used to be fired and forgotten, so a backend that had lost its
    window-server session answered "opened" while nothing opened (2026-09-25:
    a sidecar left from 2026-09-18 ran `open` without effect; a fresh one
    worked). Waiting for the exit status turns that into a visible error.
    `open` returns within a second; if it has not, it is left running and the
    request is treated as delivered.

    explorer.exe exits 1 even when it opened the window, so for it only a
    failure to start at all is an error (``trust_exit_status=False``).
    explorer.exe hands the window over and returns at once; when it has not
    returned in time nothing says a window opened, so with ``confirm`` that
    is an error too, and the caller shows the path instead.
    """
    wsl = host_kind() == "wsl"
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
        env=wsl_interop_env() if wsl else None,
    )
    try:
        _, err = proc.communicate(timeout=OPENER_WAIT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        # Whatever it said before the wait ran out still counts.
        detail = (exc.stderr or b"").decode("utf-8", "replace").strip()
        if wsl and WSL_INTEROP_FAILURE_RE.search(detail):
            raise OSError(f"{argv[0]} did not start: {detail[:300]}") from None
        if confirm:
            raise OSError(
                f"{argv[0]} did not finish within {OPENER_WAIT_SECONDS:g} s; "
                "whether it opened is not confirmed"
            ) from None
        return
    detail = (err or b"").decode("utf-8", "replace").strip()
    failed = proc.returncode != 0 and trust_exit_status
    # A Windows program that never started says so on stderr, whatever its
    # exit status is trusted to mean.
    if wsl and proc.returncode != 0 and WSL_INTEROP_FAILURE_RE.search(detail):
        failed = True
    if failed:
        message = f"{argv[0]} exited {proc.returncode}" + (f": {detail[:300]}" if detail else "")
        print(f"[opener] {message}", file=sys.stderr, flush=True)
        raise OSError(message)


def launch_url(url: str) -> None:
    """Hand a web URL to the OS default browser (Windows' browser under WSL)."""
    kind = host_kind()
    if kind == "mac":
        run_opener(["open", url])
    elif kind == "wsl":
        if shutil.which("wslview"):
            run_opener(["wslview", url])
            return
        explorer = windows_exe("explorer.exe")
        if not explorer:
            raise OSError("no way to reach Windows from WSL: neither wslview nor explorer.exe was found")
        run_opener([explorer, url], trust_exit_status=False)
    else:
        run_opener(["xdg-open", url])


async def open_url(request: web.Request) -> web.Response:
    """Open a http(s) link from a cockpit pane in the user's browser.

    The cockpit runs inside a Tauri webview where window.open() has no
    handler, so xterm's web-links addon posts the URL here instead. Only
    web schemes are accepted: this endpoint must never become a way to run
    `open` on arbitrary files or custom schemes.
    """
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response(
            {"ok": False, "error": "body must be a JSON object"}, status=400
        )
    if not isinstance(payload, dict):
        return web.json_response(
            {"ok": False, "error": "body must be a JSON object"}, status=400
        )
    url = payload.get("url")
    if not isinstance(url, str) or not url or len(url) > 4096:
        return web.json_response({"ok": False, "error": "url is required"}, status=400)
    if any(ch.isspace() or ord(ch) < 32 for ch in url):
        return web.json_response({"ok": False, "error": "url contains whitespace"}, status=400)
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return web.json_response(
            {"ok": False, "error": "only http(s) URLs can be opened"}, status=400
        )
    try:
        await asyncio.to_thread(launch_url, url)
    except OSError as exc:
        return web.json_response(
            {"ok": False, "error": f"failed to open browser: {exc}"}, status=500
        )
    return web.json_response({"ok": True})


class RevealUnavailable(OSError):
    """The file manager could not be reached; `shown` is the path to show the
    person instead, spelled the way their file manager would take it."""

    def __init__(self, reason: str, shown: str) -> None:
        super().__init__(reason)
        self.shown = shown


# A directory that is a macOS bundle (.app and the like) is a program or a
# document to the system: `open` on it launches the app instead of showing the
# folder. Recognised by its suffix or, for one with an unusual name, by
# Contents/Info.plist. A bundle, and any symlink, is revealed (`open -R`),
# never opened; only a plain folder is opened.
MAC_BUNDLE_SUFFIXES = frozenset({
    ".app", ".appex", ".bundle", ".framework", ".plugin", ".kext", ".prefpane",
    ".saver", ".xpc", ".qlgenerator", ".mdimporter", ".component", ".action",
    ".workflow", ".pkg", ".mpkg", ".photoslibrary", ".musiclibrary", ".rtfd",
    ".playground", ".xcodeproj", ".xcworkspace", ".scptd", ".docset",
})


def is_mac_bundle(path: pathlib.Path) -> bool:
    if not path.is_dir():
        return False
    if path.suffix.lower() in MAC_BUNDLE_SUFFIXES:
        return True
    return (path / "Contents" / "Info.plist").is_file()


def reveal_in_finder(path: pathlib.Path) -> str:
    """Show a local path in the file manager: a plain folder opens; a file, a
    bundle or a symlink is revealed (selected in its folder), never launched."""
    kind = "dir" if path.is_dir() else "file"
    host = host_kind()
    if host == "mac":
        if kind == "dir" and (path.is_symlink() or is_mac_bundle(path.resolve())):
            kind = "bundle"
        argv = ["open", str(path)] if kind == "dir" else ["open", "-R", str(path)]
    elif host == "wsl":
        # /mnt/c/... becomes C:\..., a distro path \\wsl.localhost\<distro>\...
        target, unconverted = None, None
        try:
            target = windows_path(path)
        except OSError as exc:
            unconverted = str(exc)
        shown = target or str(path)
        explorer = windows_exe("explorer.exe")
        problem = wsl_interop_problem() or (
            None if explorer else "explorer.exe is not reachable from this WSL distro"
        )
        if problem:
            raise RevealUnavailable(problem, shown)
        if target is None:
            raise RevealUnavailable(unconverted or "wslpath gave no Windows path", shown)
        argv = [explorer, target] if kind == "dir" else [explorer, "/select,", target]
        try:
            run_opener(argv, trust_exit_status=False, confirm=True)
        except OSError as exc:
            raise RevealUnavailable(str(exc), shown) from exc
        return kind
    else:
        argv = ["xdg-open", str(path if kind == "dir" else path.parent)]
    run_opener(argv)
    return kind


def windows_path(path: pathlib.Path) -> str:
    """The Windows spelling of a WSL path (\\\\wsl.localhost\\... or C:\\...)."""
    try:
        done = subprocess.run(
            ["wslpath", "-w", str(path)],
            capture_output=True, text=True, timeout=OPENER_WAIT_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OSError(f"wslpath could not run: {exc}") from exc
    converted = done.stdout.strip()
    if done.returncode != 0 or not converted:
        raise OSError(f"wslpath -w failed: {done.stderr.strip()[:300] or done.returncode}")
    return converted


# Claude Code shortens a long path to fit its pane, with one "…" standing for
# any run of characters — across folders too: "runs/The-fin-to-lim…/note.md"
# is runs/The-fin-to-limb-…-20261001T224253/draft/note.md. Clicked as printed
# it named nothing, so the cockpit answered "no such path" (2026-10-01
# seminar, a narrow pane under WSL).
#
# The "…" is read only when the text names nothing as it is. The search runs
# under the folder before the "…", never follows or returns a symlink (so it
# stays under that folder), and stops after ELLIPSIS_MAX_ENTRIES entries in
# all — the top folder's included, across every prefix a probe tries. A
# search cut short resolves nothing; several matches open nothing and are
# listed for the person to choose from.
ELLIPSIS = "\u2026"
ELLIPSIS_MAX_DEPTH = 6
ELLIPSIS_MAX_ENTRIES = 5000
SHOWN_PATH_MAX_LISTED = 5


class WalkBudget:
    """Directory entries an ellipsis search may still look at."""

    def __init__(self, entries: int | None = None) -> None:
        self.left = ELLIPSIS_MAX_ENTRIES if entries is None else entries
        self.exhausted = False

    def take(self) -> bool:
        if self.left <= 0:
            self.exhausted = True
            return False
        self.left -= 1
        return True


def shown_path_matches(
    text: str, budget: WalkBudget | None = None
) -> list[pathlib.Path] | None:
    """The existing paths ``text`` may name, reading one "…" as Claude Code's
    shortening when the text itself names nothing. None when the search ran
    out of budget: then nothing is known, not "no match"."""
    path = pathlib.Path(text).expanduser()
    if path.exists():
        return [path]
    if text.count(ELLIPSIS) != 1:
        return []
    head, tail = str(path).split(ELLIPSIS)
    base, _, prefix = head.rpartition("/")
    base = base or "/"
    if not tail or not os.path.isdir(base):
        return []
    budget = budget or WalkBudget()
    matches: list[pathlib.Path] = []
    pending = [(base, 0)]
    while pending:
        folder, depth = pending.pop()
        try:
            entries = os.scandir(folder)
        except OSError:
            continue
        with entries:
            for entry in entries:
                if not budget.take():
                    return None
                if depth == 0 and not entry.name.startswith(prefix):
                    continue
                try:
                    if entry.is_symlink():
                        continue
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                if entry.path.endswith(tail) and len(entry.path) >= len(head) + len(tail):
                    matches.append(pathlib.Path(entry.path))
                if is_dir and depth < ELLIPSIS_MAX_DEPTH:
                    pending.append((entry.path, depth + 1))
    return sorted(matches)


def resolve_shown_path(text: str) -> pathlib.Path | None:
    """The one existing path ``text`` names, or None (nothing, several, or
    the search ran out)."""
    matches = shown_path_matches(text)
    return matches[0] if matches and len(matches) == 1 else None


def probe_shown_path(text: str) -> tuple[str, list[pathlib.Path]] | None:
    """The longest leading part of ``text`` that names an existing path, with
    what it names. One budget covers every prefix tried."""
    if not (text.startswith("/") or text.startswith("~")):
        return None
    # Candidate ends: before any ASCII / ideographic space and before any
    # non-ASCII character (prose such as "…/logs はうまくいかない" follows a
    # path without a space), plus the end of the text. Longest first.
    ends = [
        i for i, ch in enumerate(text)
        if ch in " \u3000)]}>\"'`" or (not ch.isascii() and ch != ELLIPSIS)
    ]
    ends.append(len(text))
    seen: set[str] = set()
    budget = WalkBudget()
    for end in sorted(set(ends), reverse=True):
        candidate = text[:end].rstrip(" \u3000").rstrip(".,;:!?")
        if len(candidate) < 2 or candidate in seen:
            continue
        seen.add(candidate)
        try:
            matches = shown_path_matches(candidate, budget)
        except OSError:
            continue
        if matches is None:
            return None
        if matches:
            return candidate, matches
    return None


def longest_existing_path_prefix(text: str) -> str | None:
    """Return the longest space-delimited prefix of ``text`` that names an existing path.

    Pane output prints paths with spaces unquoted ("…/21_Coding Projects/orrery"),
    so the client cannot tell where the path ends. Try the whole text first, then
    drop one space-separated word at a time.
    """
    found = probe_shown_path(text)
    return found[0] if found else None


async def path_probe(request: web.Request) -> web.Response:
    """Tell the cockpit how much of a printed line is an existing local path."""
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({"ok": False, "error": "body must be a JSON object"}, status=400)
    text = payload.get("text") if isinstance(payload, dict) else None
    if not isinstance(text, str) or not text or len(text) > 4096 or "\x00" in text:
        return web.json_response({"ok": False, "error": "text is required"}, status=400)
    found = await asyncio.to_thread(probe_shown_path, text)
    if found is None:
        return web.json_response({"ok": False, "error": "no such path"}, status=404)
    shown, matches = found
    payload: dict[str, Any] = {"ok": True, "path": shown, "length": len(shown)}
    if len(matches) == 1:
        # The link opens what it was resolved to here, not whatever the text
        # resolves to by the time it is clicked.
        payload["resolved"] = str(matches[0])
    return web.json_response(payload)


FILE_MANAGER_NAMES = {"mac": "Finder", "wsl": "Explorer", "linux": "the file manager"}


async def reveal_path(request: web.Request) -> web.Response:
    """Reveal a filesystem path printed in a cockpit pane in Finder.

    Accepts absolute or ~-relative paths that exist; never executes them and
    never opens them with an application (that is what the path's own app
    association would do): a file, a bundle or a link is selected in its
    folder, a plain folder opens.
    """
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response(
            {"ok": False, "error": "body must be a JSON object"}, status=400
        )
    if not isinstance(payload, dict):
        return web.json_response(
            {"ok": False, "error": "body must be a JSON object"}, status=400
        )
    raw = payload.get("path")
    if not isinstance(raw, str) or not raw or len(raw) > 4096 or "\x00" in raw:
        return web.json_response({"ok": False, "error": "path is required"}, status=400)
    # A path the probe already resolved is opened as it is: if it has gone,
    # a "…" in its name must not be read as a shortening and land elsewhere.
    literal = payload.get("literal") is True
    if not (raw.startswith("/") or raw.startswith("~")):
        return web.json_response(
            {"ok": False, "error": "path must be absolute or start with ~"}, status=400
        )
    if literal:
        exact = pathlib.Path(raw).expanduser()
        matches = [exact] if exact.exists() else []
    else:
        matches = await asyncio.to_thread(shown_path_matches, raw)
    if matches is None:
        return web.json_response(
            {"ok": False, "error": "too many entries to search; not opened"}, status=422
        )
    if not matches:
        return web.json_response({"ok": False, "error": "no such path"}, status=404)
    if len(matches) > 1:
        listed = [str(match) for match in matches[:SHOWN_PATH_MAX_LISTED]]
        return web.json_response(
            {
                "ok": False,
                "error": f"{len(matches)} paths match; not opened",
                "candidates": listed,
            },
            status=409,
        )
    path = matches[0]
    manager = FILE_MANAGER_NAMES.get(host_kind(), "the file manager")
    try:
        kind = await asyncio.to_thread(reveal_in_finder, path)
    except RevealUnavailable as exc:
        # The cockpit shows `show` for the person to open by hand.
        return web.json_response(
            {"ok": False, "error": f"failed to open {manager}: {exc}", "show": exc.shown},
            status=500,
        )
    except OSError as exc:
        return web.json_response(
            {"ok": False, "error": f"failed to open {manager}: {exc}"}, status=500
        )
    return web.json_response({"ok": True, "kind": kind, "path": str(path)})


async def open_ghostty(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response(
            {"ok": False, "error": "body must be a JSON object"},
            status=400,
        )
    if not isinstance(payload, dict):
        return web.json_response(
            {"ok": False, "error": "body must be a JSON object"},
            status=400,
        )

    session = payload.get("session")
    if not isinstance(session, str) or not session:
        return web.json_response(
            {"ok": False, "error": "session is required"},
            status=400,
        )

    tmux_bin = request.app[TMUX_BIN_KEY]
    try:
        exists = await asyncio.to_thread(tmux_session_exists, tmux_bin, session)
    except OSError as exc:
        return web.json_response(
            {"ok": False, "error": f"tmux unavailable: {exc}"},
            status=500,
        )
    if not exists:
        return web.json_response(
            {"ok": False, "error": "unknown tmux session"},
            status=400,
        )

    try:
        already = await asyncio.to_thread(
            tmux_has_non_control_client,
            tmux_bin,
            session,
        )
    except (OSError, RuntimeError) as exc:
        return web.json_response(
            {"ok": False, "error": f"failed to inspect tmux clients: {exc}"},
            status=500,
        )
    if already:
        return web.json_response({"ok": True, "already": True})

    try:
        await asyncio.to_thread(launch_terminal, tmux_bin, session)
    except OSError as exc:
        label = host_platform()["terminal"]["label"]
        return web.json_response(
            {"ok": False, "error": f"failed to open {label}: {exc}"},
            status=500,
        )
    return web.json_response({"ok": True, "already": False})


async def serve_health(request: web.Request) -> web.Response:
    http_session = request.app[HTTP_SESSION_KEY]
    try:
        async with http_session.get(
            DASHBOARD_URL + "/api/agents",
            timeout=ClientTimeout(total=1),
        ):
            dashboard_online = True
    except (ClientError, asyncio.TimeoutError):
        dashboard_online = False
    return web.json_response(
        {
            "backend": "ok",
            "boot": BACKEND_BOOT_ID,
            "dashboard": dashboard_online,
        }
    )


def parse_mail_limit(request: web.Request, default: int) -> int:
    raw_limit = request.query.get("limit")
    if raw_limit is None:
        return default
    try:
        limit = int(raw_limit)
    except ValueError as exc:
        raise ValueError("limit must be an integer between 1 and 100") from exc
    if not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")
    return limit


def mail_excerpt(body_md: str | None) -> str:
    body = (body_md or "").strip()
    first_line = body.split("\n", 1)[0] if body else ""
    return BODY_HEAD_STRIP_RE.sub("", first_line).replace("`", "")[:120]


def mail_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{MAIL_DB}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def aggregate_mail_rows(
    rows: list[sqlite3.Row],
    *,
    include_body: bool = False,
) -> list[dict[str, Any]]:
    messages: dict[int, dict[str, Any]] = {}
    for row in rows:
        message_id = int(row["id"])
        message = messages.get(message_id)
        if message is None:
            message = {
                "id": message_id,
                "ts": row["ts"],
                "sender": row["sender"],
                "recipients": [],
                "subject": row["subject"] or "",
                "importance": (row["importance"] or "normal").lower(),
                "thread_id": row["thread_id"],
            }
            if include_body:
                message["body_md"] = row["body_md"] or ""
            else:
                message["excerpt"] = mail_excerpt(row["body_md"])
            messages[message_id] = message
        if row["recipient"] is not None:
            message["recipients"].append(
                {
                    "name": row["recipient"],
                    "kind": row["recipient_kind"],
                }
            )
    return list(messages.values())


def query_mail_recent(limit: int, agent: str | None) -> list[dict[str, Any]]:
    agent_filter = ""
    params: list[Any] = [MAIL_PROJECT_KEY]
    if agent:
        agent_filter = """
          AND (
              sa.name = ?
              OR EXISTS (
                  SELECT 1
                  FROM message_recipients filter_mr
                  JOIN agents filter_ra ON filter_ra.id = filter_mr.agent_id
                  WHERE filter_mr.message_id = m.id
                    AND filter_ra.name = ?
              )
          )
        """
        params.extend((agent, agent))
    params.append(limit)
    with contextlib.closing(mail_connection()) as connection:
        rows = connection.execute(
            f"""
            WITH picked AS (
                SELECT m.id,
                       CAST(strftime('%s', m.created_ts) AS INTEGER) AS ts,
                       m.created_ts,
                       m.subject,
                       m.body_md,
                       m.importance,
                       m.thread_id,
                       sa.name AS sender
                FROM messages m
                JOIN projects p ON p.id = m.project_id
                JOIN agents sa ON sa.id = m.sender_id
                WHERE p.human_key = ?
                {agent_filter}
                ORDER BY m.created_ts DESC, m.id DESC
                LIMIT ?
            )
            SELECT picked.id,
                   picked.ts,
                   picked.subject,
                   picked.body_md,
                   picked.importance,
                   picked.thread_id,
                   picked.sender,
                   ra.name AS recipient,
                   mr.kind AS recipient_kind
            FROM picked
            LEFT JOIN message_recipients mr ON mr.message_id = picked.id
            LEFT JOIN agents ra ON ra.id = mr.agent_id
            ORDER BY picked.created_ts DESC,
                     picked.id DESC,
                     mr.kind,
                     ra.name
            """,
            params,
        ).fetchall()
    return aggregate_mail_rows(rows)


def query_mail_message(message_id: int) -> dict[str, Any] | None:
    with contextlib.closing(mail_connection()) as connection:
        rows = connection.execute(
            """
            SELECT m.id,
                   CAST(strftime('%s', m.created_ts) AS INTEGER) AS ts,
                   m.subject,
                   m.body_md,
                   m.importance,
                   m.thread_id,
                   sa.name AS sender,
                   ra.name AS recipient,
                   mr.kind AS recipient_kind
            FROM messages m
            JOIN projects p ON p.id = m.project_id
            JOIN agents sa ON sa.id = m.sender_id
            LEFT JOIN message_recipients mr ON mr.message_id = m.id
            LEFT JOIN agents ra ON ra.id = mr.agent_id
            WHERE p.human_key = ?
              AND m.id = ?
            ORDER BY mr.kind, ra.name
            """,
            (MAIL_PROJECT_KEY, message_id),
        ).fetchall()
    messages = aggregate_mail_rows(rows, include_body=True)
    return messages[0] if messages else None


def query_mail_thread(thread_id: str, limit: int) -> list[dict[str, Any]]:
    with contextlib.closing(mail_connection()) as connection:
        rows = connection.execute(
            """
            WITH picked AS (
                SELECT m.id,
                       CAST(strftime('%s', m.created_ts) AS INTEGER) AS ts,
                       m.created_ts,
                       m.subject,
                       m.body_md,
                       m.importance,
                       m.thread_id,
                       sa.name AS sender
                FROM messages m
                JOIN projects p ON p.id = m.project_id
                JOIN agents sa ON sa.id = m.sender_id
                WHERE p.human_key = ?
                  AND m.thread_id = ?
                ORDER BY m.created_ts ASC, m.id ASC
                LIMIT ?
            )
            SELECT picked.id,
                   picked.ts,
                   picked.subject,
                   picked.body_md,
                   picked.importance,
                   picked.thread_id,
                   picked.sender,
                   ra.name AS recipient,
                   mr.kind AS recipient_kind
            FROM picked
            LEFT JOIN message_recipients mr ON mr.message_id = picked.id
            LEFT JOIN agents ra ON ra.id = mr.agent_id
            ORDER BY picked.created_ts ASC,
                     picked.id ASC,
                     mr.kind,
                     ra.name
            """,
            (MAIL_PROJECT_KEY, thread_id, limit),
        ).fetchall()
    return aggregate_mail_rows(rows)


def mail_sqlite_error(exc: sqlite3.Error) -> web.Response:
    return web.json_response(
        {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "messages": [],
        }
    )


def mail_project_not_configured(*, include_messages: bool) -> web.Response:
    payload: dict[str, Any] = {
        "ok": False,
        "error": "project key not configured",
    }
    if include_messages:
        payload["messages"] = []
    return web.json_response(payload)


async def serve_mail_recent(request: web.Request) -> web.Response:
    try:
        limit = parse_mail_limit(request, 40)
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    if MAIL_PROJECT_KEY is None:
        return mail_project_not_configured(include_messages=True)
    agent = request.query.get("agent") or None
    now = int(time.time())
    try:
        messages = await asyncio.to_thread(query_mail_recent, limit, agent)
    except sqlite3.Error as exc:
        return mail_sqlite_error(exc)
    return web.json_response({"ok": True, "now": now, "messages": messages})


async def serve_mail_message(request: web.Request) -> web.Response:
    raw_message_id = request.query.get("id")
    try:
        message_id = int(raw_message_id or "")
    except ValueError:
        return web.json_response(
            {"ok": False, "error": "id must be an integer"},
            status=400,
        )
    if MAIL_PROJECT_KEY is None:
        return mail_project_not_configured(include_messages=False)
    try:
        message = await asyncio.to_thread(query_mail_message, message_id)
    except sqlite3.Error as exc:
        return mail_sqlite_error(exc)
    if message is None:
        return web.json_response(
            {"ok": False, "error": "not found"},
            status=404,
        )
    return web.json_response({"ok": True, "message": message})


async def serve_mail_thread(request: web.Request) -> web.Response:
    thread_id = request.query.get("thread_id")
    if not thread_id:
        return web.json_response(
            {"ok": False, "error": "thread_id is required"},
            status=400,
        )
    try:
        limit = parse_mail_limit(request, 50)
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    if MAIL_PROJECT_KEY is None:
        return mail_project_not_configured(include_messages=True)
    now = int(time.time())
    try:
        messages = await asyncio.to_thread(query_mail_thread, thread_id, limit)
    except sqlite3.Error as exc:
        return mail_sqlite_error(exc)
    return web.json_response({"ok": True, "now": now, "messages": messages})


def portrait_stem(name: str, base: Path) -> str | None:
    if (base / f"{name}.png").is_file():
        return name

    lowered = name.lower()
    # Registered names and portrait files rarely agree on case (`ProOpus` vs
    # `proopus.png`); an exact-case miss used to fall through to initials.
    try:
        for entry in sorted(base.iterdir()):
            if entry.suffix == ".png" and entry.stem.lower() == lowered and entry.is_file():
                return entry.stem
    except OSError:
        pass
    for scientist in SCIENTIST_PORTRAITS:
        if lowered.endswith(scientist.lower()):
            stem = PORTRAIT_ALIASES.get(scientist, scientist)
            if (base / f"{stem}.png").is_file():
                return stem
            return None
    return None


def portrait_fallback(name: str, hi: bool) -> bytes:
    size = 256 if hi else 64
    initials = (name[:2] or "??").upper()
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" '
        f'height="{size}" viewBox="0 0 64 64">'
        f'<rect width="64" height="64" fill="#0e1012"/>'
        f'<text x="32" y="32" fill="#c4c0b2" font-family="Menlo,monospace" '
        f'font-size="26" text-anchor="middle" dominant-baseline="central">'
        f"{initials}</text></svg>"
    ).encode()


async def serve_portrait(request: web.Request) -> web.StreamResponse:
    name = request.query.get("name", "")
    pixel = request.query.get("style") == "pixel"
    hi = request.query.get("hi", "0") in {"1", "true"}
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise web.HTTPNotFound(text="no portrait")

    base = PORTRAIT_DIR_PX if pixel else PORTRAIT_DIR_HI if hi else PORTRAIT_DIR
    stem = portrait_stem(name, base)
    if stem is not None:
        return web.FileResponse(
            base / f"{stem}.png",
            headers={"Cache-Control": "public, max-age=3600"},
        )
    # Not a bundled face: the telemetry dashboard owns the operator's private
    # overlay and custom map (AGENTSTACK_PORTRAITS_DIR / _CUSTOM_PORTRAITS),
    # so a persistent bot registered there gets the same face here instead of
    # initials on one screen and a portrait on the other.
    if not pixel:
        relayed = await relay_dashboard_portrait(request, name, hi)
        if relayed is not None:
            return relayed
    return web.Response(
        body=portrait_fallback(name, hi and not pixel),
        content_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


async def relay_dashboard_portrait(
    request: web.Request, name: str, hi: bool
) -> web.Response | None:
    """Return the dashboard's PNG for `name`, or None when it has none.

    The dashboard answers unknown names with its own initials SVG; only a PNG
    counts as a portrait here, so the cockpit's fallback stays local.
    """
    url = f"{DASHBOARD_URL}/portrait?name={quote(name)}"
    if hi:
        url += "&hi=1"
    http_session = request.app[HTTP_SESSION_KEY]
    try:
        async with http_session.get(url, timeout=ClientTimeout(total=3)) as response:
            if response.status != 200:
                return None
            content_type = response.headers.get("Content-Type", "")
            if not content_type.startswith("image/png"):
                return None
            body = await response.read()
    except (ClientError, asyncio.TimeoutError):
        return None
    return web.Response(
        body=body,
        content_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


def _warn_tmux_gone(tmux_bin: str, exc: OSError) -> None:
    """Never let a missing tmux masquerade as an empty session roster."""
    if isinstance(exc, FileNotFoundError):
        print(
            f"ORRERY: tmux disappeared at {tmux_bin} ({exc}). "
            "Reporting an empty roster, but this is NOT 'no sessions'.",
            file=sys.stderr,
            flush=True,
        )


async def serve_sessions(request: web.Request) -> web.Response:
    tmux_bin = request.app[TMUX_BIN_KEY]
    try:
        sessions = await asyncio.to_thread(list_tmux_sessions, tmux_bin)
    except FileNotFoundError as exc:
        _warn_tmux_gone(tmux_bin, exc)
        # 503 rather than [] so the UI can tell "broken" from "idle".
        return web.json_response(
            {"error": "tmux_unavailable", "tmux_bin": tmux_bin, "detail": str(exc)},
            status=503,
        )
    except OSError:
        sessions = []
    return web.json_response(sessions)


SESSIONS_REFRESH_SECONDS = 5


async def _session_list_refresher(
    peer: WebSocketPeer,
    tmux_bin: str,
    initial: list[dict[str, Any]],
) -> None:
    """Keep the client's session list fresh.

    The list is pushed once at connect; without this task a session created
    afterwards (e.g. a freshly spawned child agent) never becomes jumpable
    in an already-open cockpit.
    """
    last = initial
    while True:
        await asyncio.sleep(SESSIONS_REFRESH_SECONDS)
        try:
            sessions = await asyncio.to_thread(list_tmux_sessions, tmux_bin)
        except OSError as exc:
            _warn_tmux_gone(tmux_bin, exc)
            continue
        if sessions != last:
            last = sessions
            await peer.send_json({"type": "sessions", "sessions": sessions})


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    response = web.WebSocketResponse(heartbeat=30)
    await response.prepare(request)
    peer = WebSocketPeer(response)
    attached: set[str] = set()
    manager = request.app[BRIDGE_MANAGER_KEY]
    refresher: asyncio.Task[None] | None = None

    try:
        try:
            sessions = await asyncio.to_thread(
                list_tmux_sessions, request.app[TMUX_BIN_KEY]
            )
        except OSError as exc:
            _warn_tmux_gone(request.app[TMUX_BIN_KEY], exc)
            sessions = []
        await peer.send_json({"type": "sessions", "sessions": sessions})
        refresher = asyncio.create_task(
            _session_list_refresher(peer, request.app[TMUX_BIN_KEY], sessions)
        )

        async for message in response:
            if message.type == WSMsgType.TEXT:
                try:
                    payload = json.loads(message.data)
                except json.JSONDecodeError:
                    await send_error(peer, None, "invalid JSON")
                    continue
                if not isinstance(payload, dict):
                    await send_error(peer, None, "message must be a JSON object")
                    continue
                try:
                    await manager.handle_message(peer, attached, payload)
                except Exception as exc:
                    session = payload.get("session")
                    await send_error(
                        peer,
                        session if isinstance(session, str) else None,
                        f"request failed: {type(exc).__name__}",
                    )
            elif message.type in {
                WSMsgType.CLOSE,
                WSMsgType.CLOSED,
                WSMsgType.ERROR,
            }:
                break
    finally:
        if refresher is not None:
            refresher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await refresher
        await manager.disconnect(peer, attached)
    return response


async def app_resources(app: web.Application):
    app[HTTP_SESSION_KEY] = ClientSession(timeout=ClientTimeout(total=6))
    app[BRIDGE_MANAGER_KEY] = SessionBridgeManager(app[TMUX_BIN_KEY])
    await app[BRIDGE_MANAGER_KEY].start()
    yield
    await app[BRIDGE_MANAGER_KEY].close()
    await app[HTTP_SESSION_KEY].close()


@web.middleware
async def revalidate_static(request: web.Request, handler):
    """Make the browser re-check assets instead of guessing they are fresh.

    Without a Cache-Control header, a browser is free to invent a freshness
    lifetime from Last-Modified and serve a stale copy with no request at
    all. Edit orrery_view.css, reload, and see the old rendering — which is
    exactly what happened: the fix for the state glyphs was live in the repo
    and correct in a fresh tab, while the desktop app kept animating the old
    stylesheet (2026-08-06). ETag still answers most of these with a 304, so
    this costs a conditional request, not the payload.

    Responses that already carry a Cache-Control (portraits proxied from the
    dashboard) keep theirs.
    """
    response = await handler(request)
    if "Cache-Control" not in response.headers:
        response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Orrery-Boot"] = BACKEND_BOOT_ID
    return response


def create_app(tmux_bin: str = "tmux") -> web.Application:
    app = web.Application(middlewares=[revalidate_static])
    app[TMUX_BIN_KEY] = tmux_bin
    app[USAGE_CACHE_KEY] = UsageCache()
    app[USAGE_LOCKS_KEY] = {}
    app[PREFS_LOCK_KEY] = asyncio.Lock()
    app[PROXY_INFLIGHT_KEY] = {}
    app.cleanup_ctx.append(app_resources)
    app.router.add_get("/telemetry/agents", proxy_dashboard)
    app.router.add_get("/telemetry/messages", proxy_dashboard)
    app.router.add_get("/telemetry/graph", proxy_dashboard)
    app.router.add_post("/telemetry/spawn", proxy_spawn)
    app.router.add_post("/telemetry/open-ghostty", open_ghostty)
    app.router.add_post("/telemetry/open-url", open_url)
    app.router.add_post("/telemetry/reveal-path", reveal_path)
    app.router.add_post("/telemetry/path-probe", path_probe)
    app.router.add_get("/telemetry/health", serve_health)
    app.router.add_get("/telemetry/platform", serve_platform)
    app.router.add_get("/telemetry/identity", serve_identity)
    app.router.add_get("/telemetry/usage", serve_usage)
    app.router.add_get("/telemetry/prefs", serve_prefs)
    app.router.add_put("/telemetry/prefs", update_prefs)
    app.router.add_get("/telemetry/mail/recent", serve_mail_recent)
    app.router.add_get("/telemetry/mail/message", serve_mail_message)
    app.router.add_get("/telemetry/mail/thread", serve_mail_thread)
    app.router.add_get("/telemetry/portrait", serve_portrait)
    app.router.add_get("/telemetry/sessions", serve_sessions)
    app.router.add_get("/telemetry/spawn-catalog", proxy_dashboard)
    app.router.add_get("/telemetry/spawn-status", proxy_dashboard)
    app.router.add_get("/telemetry/skills", serve_skills)
    app.router.add_get("/telemetry/clipboard/files", serve_clipboard_files)
    app.router.add_get("/telemetry/fs/dirs", serve_fs_dirs)
    app.router.add_route("*", "/network", proxy_dashboard_passthrough)
    app.router.add_route("*", "/network/{tail:.*}", proxy_dashboard_passthrough)
    app.router.add_route("*", "/api/{tail:.*}", proxy_dashboard_passthrough)
    app.router.add_route("*", "/assets/{tail:.*}", proxy_dashboard_passthrough)
    app.router.add_get("/portrait", proxy_dashboard_passthrough)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_static("/", HERE, show_index=True)
    return app


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", DEFAULT_PORT)),
    )
    parser.add_argument("--tmux-bin", default=os.environ.get("TMUX_BIN", "tmux"))
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.host != DEFAULT_HOST:
        raise SystemExit("ORRERY backend is restricted to 127.0.0.1.")

    tmux_bin = resolve_tmux_bin(args.tmux_bin)
    print(f"ORRERY: tmux resolved to {tmux_bin}", flush=True)

    app = create_app(tmux_bin)
    with contextlib.suppress(KeyboardInterrupt):
        web.run_app(
            app,
            host=args.host,
            port=args.port,
            print=lambda message: print(message, flush=True),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
