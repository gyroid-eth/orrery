# Cockpit in global mode

[日本語](../global-cockpit.md) · [Documentation index](README.md)

This path is explicitly selected for testing. Legacy remains the default and cutover stays disabled. Use an already prepared Telemetry runtime under the same user. Cockpit never opens its Mail DB directly.

## Startup

Use the existing `AGENTSTACK_HOME/env.sh` or launch environment to select `AGENTSTACK_RUNTIME_MODE=global` and `AGENTSTACK_GLOBAL_SERVER_CONFIG`. Set `AGENTSTACK_HOME` to that prepared installation and `ORRERY_DASHBOARD_URL` to its loopback Telemetry origin. Browser and app share `scripts/start-cockpit.sh`. Missing global configuration or capabilities stop startup without a legacy fallback.

`scripts/setup.sh --check` and `--dry-run` call the shared probe and instruction resolver plan without changing projects, Mail DBs, provider files or services. Applying instruction changes uses the existing resolver's consent flow. A research work folder does not change the Mail namespace.

## Unlock and Lock

Run `agentstack-http-operator show` for this cockpit's `AGENTSTACK_HOME` and paste the capability into Unlock. It lives in page-session `sessionStorage`. If storage is unavailable, memory-only mode requires Unlock again after reload. Same-origin tabs can receive it through a bounded handshake. Extensions granted access to the page and same-origin code belong to this trust boundary.

Lock clears this page session's terminals, Mail headings, names and observed settings, aborts requests and notifies same-origin tabs. It does not revoke the capability on the server. Native clipboard, opener and pane operations are refused before Unlock and after Lock.

Every HTTP route except exact static GET/HEAD uses shared admission: loopback alone is insufficient; Host, Origin and the private capability are checked. WebSocket authentication uses the same capability in its first frame. No sessions, attach or input are processed before authentication. Global mode refuses the `?ws=` destination override.

## Mail and agents

Explicitly choose a positive agent ID in **View as**. Open a recent message's reply flow and continue long conversations with **Load more visible mail**. Hidden parents' IDs and names are never inferred. Earlier unavailable Mail gets a small note; old instruction blocks get a restrained notice linking directly to English and Japanese documentation. The Telemetry network uses the same shared controllers.

NEW AGENT uses the shared registration and launch controller. Interrupted registration follows the status's Replay / Abandon operations; unknown processes are not relaunched by inference. Terminals use sessions from the authenticated WebSocket.

Activity, context and parent relationships come from Telemetry's existing local observations. Cockpit keeps no second ledger. Unproven activity, including App without current provider live evidence, is **ACTIVITY UNKNOWN**. Quota values come directly from `/api/quotas`.

## Capability proof and validation

Admitted `/telemetry/health` returns `runtime_mode=global`, `api=1` and these capabilities, each 1: `operator_http_admission`, `global_mail_bridge`, `instruction_migration`, `websocket_first_frame_auth`, `global_runtime_observation`. It includes upstream binding, API and capabilities; a changed binding makes the service unavailable. This is not cutover approval: the shared probe still reports `cutover_ready=false`.

Validation uses isolated real HTTP/management sockets and synthetic Mail, six replies, long text, a narrow pane, light/dark and Lock. No provider binary is required. Real provider/native app interactions and actual connections under another UID need outside validation. Real Gemini agy remains unverified.

## Exit and the PR7 gate

Global Select/Exit is explicitly disabled with a reason. Legacy exit remains unchanged. **Single and bulk global exit / retire must be implemented and accepted before PR7 changes the default**, using the existing termination implementation through shared admission/controllers. Global mode never forwards to legacy `/api/exit`.

## Legacy UI call audit

The table covers fetch, XMLHttpRequest, WebSocket and native invoke call sites in `cockpit.html` and bridge scripts. Shared admission covers every non-static HTTP request.

| Legacy route / purpose | Global replacement | Disposition |
| --- | --- | --- |
| `/telemetry/agents`, `/messages`, `/graph` polling | `/api/agents`, `/api/runtime-observations`, shared network; old polls never start | Implemented |
| `/telemetry/mail/recent`, `/message`, `/thread` | Shared `/api/mail/*` controller and reply flow | Implemented |
| `/telemetry/spawn-catalog`, `/spawn-status`, `/spawn`, `/fs/dirs` | Shared operation controller using `/api/global/*`, `/api/fs/dirs` | Implemented |
| `/telemetry/usage`, `/telemetry/portrait` | `/api/quotas`, `/portrait` via authenticated blob | Implemented |
| `/telemetry/open-url`, `/reveal-path`, `/open-ghostty`, `/path-probe`, `/platform`, `/identity`, `/sessions`, `/skills`, `/clipboard/files` | Existing local handlers inside admission | Implemented |
| `/telemetry/prefs` GET/PUT | Admitted routes retained; old synchronous XHR driver excluded, browser theme preference initializes the page | Old sync driver unnecessary |
| `/network`, `/network/*`, images and shared scripts | Fixed assets and canonical API only; unrestricted passthrough removed | Implemented |
| `/ws`: attach/detach/input/close/resize/release/refresh/codex-page | Existing dispatch after first-frame authentication; close is a terminal pane and release is input ownership, neither exits an agent | Implemented |
| Native clipboard/opener/pane/tour window | Only after Unlock; existing pure theme initialization reads retained | Implemented |
| `/api/exit` (single and bulk) | Select/Exit disabled with a reason; no legacy fallback | Disabled; required before PR7 |

## Related development checks

Use a full Telemetry clone at the CI-pinned commit `b38b76a4abcd07b44c0184665ef8e7a2e3f0393e` as `ORRERY_TEST_TELEMETRY_ROOT`. Install with `python -m pip install -r bridge/requirements.txt pytest -e "$ORRERY_TEST_TELEMETRY_ROOT/packages/agentstack_mail"`, then run global cockpit tests serially. Browser tests connect to an existing CDP service via `ORRERY_CDP_URL`; they never launch a browser. Actual tmux and one-command installation checks run outside the sandbox with dedicated HOME, socket and ports.
