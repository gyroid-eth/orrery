# Protecting legacy cockpit tmux targets

At startup cockpit pins one legacy endpoint and uses an explicit absolute `tmux -S` socket thereafter. It calls Telemetry's shared admission before control attach, input, split/close, and opening a terminal. A changed socket or server PID is refused; it never falls back to bare tmux. Only an initially absent server may pin the first server appearing at the same endpoint.

This protects legacy consumers. Global dedicated terminals, WebSocket references, and pane windows belong to a later change. It does not enable new global launches. Pure legacy operations and the existing split/close restriction on auxiliary sessions remain.

| Placement | Target operation |
|---|---|
| Working shared helper | Refuse global panes using existing context/live snapshots; continue normal legacy panes |
| Missing/old/failed helper, no global hints | Preserve legacy operations after fixed-layout negative admission |
| Unavailable helper with roots/context/config present or unknown | Refuse with `GLOBAL_TARGET_HELPER_UNAVAILABLE`; harmless roster reads continue |
| Working helper with a corrupt/partial root | Refuse all target side effects with `GLOBAL_TARGET_OWNERSHIP_UNKNOWN` until repaired; an arbitrary standalone name cannot be excluded |
| Legacy startup inherits the dedicated global socket | Refuse startup with `GLOBAL_TMUX_LEGACY_CONSUMER_REFUSED` |

Telemetry's `bin/lib/runtime_tmux.py` and `runtime_tmux_contract.json` own membership checks, schemas and reasons. Cockpit stores no socket registry or ownership ledger. Only missing-helper placement admission lives in `bridge/runtime_target.py`. The existing literal reader reads `env.sh` without executing it.

The existing WS/HTTP error path displays refusal reasons. Read `agentstack-runtime-client tmux-diagnostics`, then `agentstack-ui-client status` for the relevant existing config. Repair the root/config, verify `global_complete=true`, and retry. Do not remove a running root or pending intent to bypass a refusal.

Directly starting an older consumer inside a dedicated pane with its inherited `TMUX` is unsupported. Update both Telemetry and cockpit before enabling dedicated launches. Custom legacy endpoints require startup socket/server proof. Windows Terminal receives the same Linux distro and absolute socket as argv; the socket is never converted to a Windows path.

## Existing callers

| Caller | Transport / admission |
|---|---|
| Roster, interactive clients, pane→session, question capture | Same explicit `-S`; admit before reading question content |
| Control attach, input/capture/resize/split/close | Admit before attach and immediately inside the existing send lock; retain the lifetime pipe/guard |
| Closed detection: has-session / list-sessions / show-options | All three use the same explicit `-S` and environment without TMUX/TMUX_PANE; retain True/False/unknown semantics |
| Ghostty / WT attach | Complete admitted argv/env; same Linux socket and existing distro resolution |
| Auxiliary control-bridge session creation | Establish placement before creation; never adopt or rename another session |

Tests deploy the actual shared helper from a pinned Telemetry commit's installer declaration. Set `ORRERY_TEST_TELEMETRY_ROOT` to that checkout. Fixtures use private HOME, short temporary directories and dedicated servers, without live/default tmux, real provider state or the real Mail DB. Schema/consumer cases use fixture process-start values; real OS proof is distinguished in the shared contract's outside tests.

Admission and tmux effects are not an atomic OS transaction and do not fully isolate a hostile same-UID process. Admission runs immediately inside the send lock without an intervening external wait.
