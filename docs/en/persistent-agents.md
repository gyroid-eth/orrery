# Persistent-agent enrollment and startup

> 日本語版: [persistent-agents.md](../persistent-agents.md)

[Launchers and identity](launchers.md) · [Troubleshooting](telemetry-troubleshooting.md) · [Back to README](../../README.en.md)

A persistent agent is a parentless bot that keeps the same ORRERY Mail identity across restarts. `interactive` agents, such as Claude Channels, also accept input through the tmux REPL. `headless` agents receive notifications through a dedicated bridge. These are distinct interaction modes, not lifecycle or parentage values.

Temporary agents started through the normal `agent-start` / `agent-start-codex` or child launchers continue to use their existing registration path. The enrollment procedure here is for migrating an existing bot that never passed through a launcher, or for recovering the same numeric row after its local credential was lost.

## Claude Channels in fresh mode

In `runtime_mode=fresh`, complete [fresh registration and preparation](https://github.com/gyroid-eth/orrery-telemetry/blob/master/docs/fresh-global-update.en.md)
first. The operator prepares login, hooks and the Channels plugin in the prepared Claude HOME.
Set `AGENTSTACK_PYTHON` to the same verified Python that imports this Mail package for ordinary fresh launch.
Do not import legacy enrollment or Mail tokens. Create an owner-only JSON profile:

```json
{
  "kind": "orrery-fresh-persistent-v1",
  "context": "/path/to/prepared/context.json",
  "provider": "claude",
  "working_directory": "/path/to/workspace",
  "channels": ["plugin:telegram@claude-plugins-official"],
  "model": "sonnet",
  "environment": {"TELEGRAM_STATE_DIR": "/path/to/channel-state"}
}
```

```bash
chmod 600 /path/to/bot.json
agentstack-persistent inspect --profile /path/to/bot.json
agentstack-persistent run --profile /path/to/bot.json
```

This explicit fresh profile dispatches to ordinary launch. It does not register an agent,
prepare a context or install a service. Channels reuse interactive configuration source checks
and Mail alias replacement, preserving Channels alongside bound Mail and regular reservation hooks.
The existing fresh watcher delivers idle Mail to the same tmux input surface.

Keep credential values out of the launch environment and profile. Use the existing Channels state
reader; the official plugin still reads its `.env` inside its own process after startup.
Legacy raw Mail tokens are not inherited. Credential values are not passed to the model's Bash.

To stop, send **SIGTERM to this launcher process rather than killing its pane**, and wait for it.
The launcher observes provider exit and writes `ended.json`; restart with the same profile afterward.
Unexpected exit, forced kill or stop timeout stays unknown and blocks another run.
One launch owns one conversation. A session change such as `/clear` stops that run and reports
`FRESH_BOT_RESTART_REQUIRED`. Automatic old-conversation restoration and seamless reset are not supported.
Never run old and new pollers with the same Telegram token; verify that the old poller has stopped.

Bot process restart differs from machine restart. Mac/WSL machine reboot and automatic unlock
remain unverified. Legacy profiles continue to use the enrollment procedure below.

## Fresh Hermes Telegram (interactive)

Use the same prepared registration with the native `hermes chat --tui` and the bundled
`orrery-telegram` plugin. Incoming Telegram DMs enter that live TUI; replies use the
`telegram_reply` tool. Bound Mail, the standard watcher, and terminal input share the same TUI.
No separate gateway or headless bridge is started.

Use the complete, verified TUI product built within the managed generation. The Telegram launch plan checks the management receipt against the selected runtime and passes only the verified `HERMES_TUI_DIR` and `HERMES_NODE` paths. Missing or modified products stop with `invalid_runtime` before profile writes. Startup performs no npm acquisition or build and does not copy `ui-tui` into the Python PM workspace. These environment entries are not added to ordinary child/CLI plans. Acquire a new generation with the installer instead of patching an old one manually. TUI readiness alone does not establish Telegram credentials, Mail or model connectivity.

```json
{
  "kind": "orrery-fresh-persistent-v1",
  "context": "/path/to/prepared/context.json",
  "provider": "hermes",
  "working_directory": "/path/to/workspace",
  "model": "configured-model-id",
  "managed": {
    "manifest_file": "/path/to/native-manifest.json",
    "backend_id": "deepseek"
  },
  "telegram": {
    "token_ref": {"store": "keychain", "service": "telegram-bot", "account": "owner"},
    "allow_from": [123456789]
  }
}
```

Keep the profile at `0600`, with the context and Hermes HOME on a private Linux/macOS filesystem.
Replace the example number with your Telegram user ID; group messages are excluded.
On macOS, store the token yourself in Keychain. Linux/WSL uses the existing
[Secret Service reference](telemetry-install.md#ubuntu-wsl-secret-service-references-real-machine-acceptance-pending),
for example `{"store":"secret-service","attributes":{"application":"telegram-bot"}}`.
Keep values out of profiles and environments. The plugin reads the value in-process;
the same reference enters the ordinary credential-read guard. Provider selection, `key_cmd`,
and config generation reuse the ordinary managed-child path.

Prepare the provider and personally approve hooks/plugins before using the same `inspect`/`run` commands.
Hermes HOME is `providers/hermes` beside the context. Place any non-secret personality/settings there
before launch; do not copy old Mail MCP definitions, credential values, or legacy tokens.
An existing launchd/systemd user unit can run this foreground launcher; no service is registered automatically.
Linux/WSL requires the user bus and an unlocked Secret Service. Do not default private runtime state to `/mnt/c`.

Stop/restart and session changes follow the Channels rules. A requested Hermes stop also waits for
that launch's TUI/backend descendants from startup through normal exit before writing `ended.json`.
The foreground pane/job must give this run its own process group; surviving children or unavailable observation leave it unknown.
`telegram-ready` in `logs/telegram-status.json` means the poller is ready, not that Mail or replies succeeded.
Treat 409, credential-unavailable, and allowlist-empty as failures. Never overlap old/new pollers for one token.

Details for `credential-unavailable` are saved in `logs/telegram-credential-diagnostic.json` (0600) under the same Hermes HOME. Fixed reasons are `configuration-invalid` (settings read/shape), `reference-invalid` (reference shape), `unsupported-store`, `security-nonzero` (only an integer returncode is added), `security-timeout`, `security-unavailable`, `empty-or-invalid-value`, and Secret Service's `secret-service-timeout` / `secret-service-unavailable`. Settings, reference/token values, helper stdout/stderr and full environments are never recorded. This is the last failure: compare its `pid` and `updated_at` with the current status. Investigate the reported reason before changing HOME or Keychain settings.

Known limits: the existing plugin's concurrent flush and partial long replies after a send failure are unchanged.
A surviving child observed by the launcher prevents a confirmed end. The close snapshot also saves known descendants' PID/births, so a later group/session change cannot hide their survival. A child first created after that snapshot and then detached is not captured by this record alone.
The launcher's `operation.lock` is released when that process exits. Separately, the Hermes Telegram plugin uses `telegram-poller.lock` in the same Hermes HOME: **only while a poller process actually holds that lock** does it reject another poller using that HOME ([acquire/release](https://github.com/gyroid-eth/orrery-telemetry/blob/master/integrations/hermes/telegram/managed_guard.py), [release after poll-thread shutdown](https://github.com/gyroid-eth/orrery-telemetry/blob/master/integrations/hermes/telegram/__init__.py)). An unobserved child or a process using another HOME is not guaranteed to hold it. Duplicate-reception protection does not prove that all unknown children have ended.
Each run starts a new conversation; old conversations are not automatically restored. Synthetic transport/native
tests are separate from real Telegram acceptance. Real provider/Telegram round trips, real WSL, and machine
reboots on macOS/WSL remain unverified.

## Close an unfinished fresh run

Closure does not mean task success or cancellation of side effects. Distinguish:

| State | Record and next action |
| --- | --- |
| Normal exit | `ended.json` with observed wait exit 0; one ordinary run |
| Observed failure | `ended.json` with the actual nonzero exit after required child-exit observations; one ordinary run |
| Confirmed closure | `resolved-ended.json`, provider exit unknown (JSON null); one separate ordinary run |
| Unknown | Missing wait, remaining processes, unavailable observations or insufficient records; refuse the next run and report why |

Hermes can close an observed exit 23 as failed when descendant observations also establish no remaining children.
Unexpected nonzero Channels exits without descendant observation, lost launchers and stop timeouts remain unknown.
An exit 0 without a valid session receipt is recorded as ended, but native startup acceptance still fails.

Use the same prepared context, verified Python and profile. `RUN_UUID` is the current run UUID shown in the diagnostic.

```sh
AGENTSTACK_RUNTIME_MODE=fresh AGENTSTACK_FRESH_CLIENT_CONTEXT="$orrery_context" \
  AGENTSTACK_PYTHON="$orrery_python" \
  "$orrery_install/bin/agentstack-runtime-client" resolve-ended \
    --launch-id "$RUN_UUID" --confirm-ended
# Only after ok:true above, launch normally as a separate operation.
AGENTSTACK_RUNTIME_MODE=fresh AGENTSTACK_FRESH_CLIENT_CONTEXT="$orrery_context" \
  AGENTSTACK_PYTHON="$orrery_python" \
  "$orrery_install/bin/agentstack-persistent" run --profile "$orrery_profile"
```

`--confirm-ended` expresses the caller's explicit judgment, without new authentication or force.
The command rechecks the same I/A, credential generation, context, current UUID, launch mutex,
recorded PID/births, pane/socket and job groups. Sufficient observations publish one new private record.
Intent/session/current stay intact; an exit code is never invented. Repeated resolution returns the same end kind.
Closed runs reject Mail delivery, hooks and session publication. Resolution does not kill processes, remove panes
or restart automatically. Do not bypass it by deleting current/lock/receipts or handwriting termination records.

`FRESH_RESOLVE_PROCESS_ALIVE` / `FRESH_RESOLVE_GROUP_ALIVE` mean remaining processes;
`FRESH_RESOLVE_PROCESS_CHANGED` / `FRESH_RESOLVE_TARGET_CHANGED` mean changed PID/pane/socket facts;
`FRESH_RESOLVE_OBSERVATION_UNAVAILABLE` means unavailable observations;
`FRESH_RESOLVE_RECORD_INSUFFICIENT` means insufficient records. Stop and report these, launch-busy and identity/credential refusals.
Any necessary ordinary stop is separate; resolve again only after confirming termination.

New tmux runs add versioned PGID, leader birth and provider descendants' PID/births known from the saved snapshot's parent chain to the existing `tmux.json`. Known children remain subject to survival refusal after changing group. A snapshot exceeding the 64-member bound, containing ancestry cycles, or having unknown birth/ownership shape is refused instead of publishing sufficient evidence.
Children first created after this snapshot and later unrecorded detachment are not tracked. No resident watcher or descendant history database is added.
Old runs without that field, and foreground runs without tmux observations, HOLD for insufficient proof.
Three absent PIDs or human confirmation alone cannot close a run. This does not fully track arbitrary daemonization,
double forks or unrecorded orphans in separate sessions. The shared ps/tmux adapter covers Mac and Linux;
Windows native processes in WSL are outside this boundary.

An agent already authorized to recover needs no extra human commands or product approvals per incident:
one ordinary run after observed termination, or resolve plus ordinary run for two commands after an unfinished run.
Direct human operation also takes two commands; unknown cases are not guaranteed to recover in two steps.
Telegram/Mail round trips, natural wake, provider login/hook trust and machine restart acceptance remain separate.

## Scope of the guarantee

An **operator** here means a person who explicitly runs the dedicated CLI in a local terminal on this machine. The implementation guarantees only:

- an owner-only local Unix socket and same-OS-user peer UID
- matching of numeric agent ID, project, expected name, Mail instance UUID, and credential generation
- compare-and-swap replacement of only that row's credential
- local audit records containing fixed fields only
- no secret in output, logs, argv, or MCP/proxy tools

This is not proof of a human identity. A process with shell access as the same OS user can run the CLI, and a TTY does not prove that a human is present. Requiring a person to inspect the target and type the operation is an operational rule, not a new login mechanism. Do not instruct a model to perform enrollment.

`agentstack-enroll` is absent from MCP/proxy catalogs and dispatch. It talks only to the Mail process's local management socket. `claim` and `recover` do not create aliases or rows, and do not change retirement or profile data.

## The two JSON profiles

The installer creates a connection profile for the local Mail instance:

```text
~/.agentstack/connections/local.json
```

It carries transport details (management socket, loopback MCP URL, and Mail environment) plus `expected_server_instance_id` after the first confirmation. A host name, port, or socket path is not a Mail identity. Keep the file owner-only, with no group or world permissions.

The operator places one persistent profile per bot in the following directory with mode `0600`:

```text
~/.agentstack/profiles/<name>.json
```

The profile never contains a token. The credential is stored in owner-private files under the runtime directory named by the connection profile.

## Creating a new bot

`claim` is not a row-creation API. First create a new bot identity in its project through a normal, supported registration path, such as a top-level launcher, dashboard NEW AGENT, or the preregistration path for that use case. Record the canonical name and positive numeric agent ID from the authoritative response.

Do not substitute `claim` for a nonexistent ID, an ID from another project, or a retired row. It does not search by name or create a second row under an alias.

If the properly created row is `server-null`, use `claim` below. If it already has a valid owner credential, skip the credential mutation. A new bot must still verify and pin the connection's Mail UUID, run `inspect`, and validate its persistent profile.

## Migrating an existing bot

Replace the sample values with values from this machine. Record the numeric `id` from the canonical `register_agent` response when the row is created. For an existing row whose response was lost, the operator verifies the `id` in an authenticated ORRERY Mail `whois` response for the exact project and name. Never infer it from a name or dashboard ordering.

```bash
export BOT_ID=123
export BOT_NAME=ChannelsBot
export PROJECT_KEY=/absolute/project/path
export CONNECTION="$HOME/.agentstack/connections/local.json"
```

### 1. Inspect the target without a secret

```bash
"$HOME/.agentstack/bin/agentstack-enroll" inspect \
  --agent-id "$BOT_ID" \
  --project-key "$PROJECT_KEY" \
  --connection "$CONNECTION" \
  --name "$BOT_NAME"
```

Confirm at least these fields:

- `server_instance_id`: the persistent UUID of the intended local Mail instance
- `project_key` / `agent_id` / `name`: the exact row to start
- `retired: false`
- `credential_state`: `server-null` or `server-token`
- `local_credential_state`: the local saved state
- `connection_pinned`: whether the connection is already fixed to the UUID

`--name` is an optional expectation check. It never searches for a row or creates an alias.

### 2. Pin the connection to the Mail UUID once

When `connection_pinned` is `false`, the operator confirms the Mail instance and UUID shown by the first inspection, then repeats the inspection with that exact value:

```bash
"$HOME/.agentstack/bin/agentstack-enroll" inspect \
  --agent-id "$BOT_ID" \
  --project-key "$PROJECT_KEY" \
  --connection "$CONNECTION" \
  --name "$BOT_NAME" \
  --pin-server '<server_instance_id confirmed above>'
```

`claim` and `recover` reject an unpinned connection. They also refuse to replace an existing pin with a different UUID.

### 3. Select exactly one operation from the state

| Inspection state | Operation |
| --- | --- |
| `server-null` + local `missing` | `claim` |
| `server-token` + local `missing` or `missing-token-same-identity` | `recover` |
| `server-token` + `present` / `present-legacy-verified` | No mutation; continue to persistent-profile inspection |
| `identity-conflict`, a different UUID / ID / name, or retired row | Stop and inspect the target; do not repair automatically |

Initial claim:

```bash
"$HOME/.agentstack/bin/agentstack-enroll" claim \
  --agent-id "$BOT_ID" \
  --project-key "$PROJECT_KEY" \
  --connection "$CONNECTION" \
  --name "$BOT_NAME"
```

Recovery of the same row after its local credential was lost:

```bash
"$HOME/.agentstack/bin/agentstack-enroll" recover \
  --agent-id "$BOT_ID" \
  --project-key "$PROJECT_KEY" \
  --connection "$CONNECTION" \
  --name "$BOT_NAME"
```

`claim` applies only to a row whose server credential is null. `recover` applies only when the row has a server token and the same identity has no local token. Both use the current generation as a CAS expectation and leave the credential unchanged on conflict.

The CLI first saves the new secret in a unique mode-`0600` pending file, then sends the request with that same request ID and secret. If the connection is interrupted, **run the exact same command again**. It checks the saved request's status and does not generate another token. Do not open, delete, or paste pending or active credential files into chat or logs.

Successful stdout is an `orrery-enrollment-receipt-v1`, not the secret. Confirm:

- `result: accepted`
- `operation: claim` or `recover`
- the expected `server_instance_id` / `project_key` / `agent_id`
- `new_generation` is one greater than `old_generation`
- `reason: operator-claim` or `operator-recover`

In the same transaction as the credential update, Mail audits timestamp, request ID, peer UID, authority, row, operation, old/new generation and fingerprint, and fixed reason/result. A rejection records only its fixed reason/result and does not change the credential. Mail does not audit the token, request body, or free-form error text.

### 4. Create the persistent profile

This is an interactive Claude Channels example:

```json
{
  "kind": "orrery-persistent-agent-v1",
  "name": "ChannelsBot",
  "agent_id": 123,
  "project_key": "/absolute/project/path",
  "connection": "../connections/local.json",
  "provider": "claude",
  "parentless": true,
  "lifecycle": "persistent",
  "interaction": "interactive",
  "state_dir": "../persistent/ChannelsBot",
  "working_directory": "/absolute/project/path",
  "command": [
    "/absolute/path/to/claude",
    "--channels",
    "plugin:telegram@claude-plugins-official"
  ],
  "environment": {
    "TELEGRAM_STATE_DIR": "/absolute/path/to/channel-state"
  }
}
```

```bash
chmod 700 "$HOME/.agentstack/profiles"
chmod 600 "$HOME/.agentstack/profiles/ChannelsBot.json"
```

The axes are independent:

| Field | Values | Meaning |
| --- | --- | --- |
| `provider` | `claude` / `codex` | Runtime provider and proxy configuration |
| `parentless` | `true` | Top-level identity with no parent |
| `lifecycle` | `persistent` | Reuse the same row after restart |
| `interaction` | `interactive` / `headless` | Direct REPL input or an intervening bridge |

The existing `standalone` value in dashboard/launcher flows still means “no parent.” Persistent lifecycle, parentage, and interaction are not packed into one enum.

Do not place tokens, passwords, credentials, or API keys in `environment`. The profile also cannot override internal Mail identity, parent, or proxy-credential variables. Service managers often have a short PATH, so absolute command paths are recommended for persistent startup.

### 5. Inspect and start the profile

```bash
"$HOME/.agentstack/bin/agentstack-persistent" inspect \
  --profile "$HOME/.agentstack/profiles/ChannelsBot.json"

exec "$HOME/.agentstack/bin/agentstack-persistent" run \
  --profile "$HOME/.agentstack/profiles/ChannelsBot.json"
```

`inspect` matches the profile, connection, Mail UUID, numeric row, name, and credential generation/fingerprint. `run` repeats the same validation and takes a per-profile instance lock before startup. A second instance of the same profile is rejected.

For an interactive profile that passes the checks, `inspect` includes these fields.

```json
{"ready": true, "lifecycle": "persistent", "interaction": "interactive"}
```

The launcher never enrolls automatically. It stops with a fixed reason and documentation path if the identity is not enrolled, the local credential is missing, or the authority/row does not match.

After the interactive REPL starts, the operator verifies:

1. `/mcp` shows every Mail alias generated by the wrapper (normally `orrery-mail` when no alias existed) and the expected channel plugin as connected. Multiple existing aliases correctly produce multiple bound connections.
2. `runtime_status`, called through the bound namespace that will be used, returns the profile's name and project. This confirms the local proxy binding; it does not prove Mail server authentication/reachability or Telegram receive/reply.
3. An `/mcp` display name alone does not distinguish raw from proxy or prove duplicate-start prevention. If details expose the command, check without revealing secret values that it points to the generated bound-proxy runner.

## Interactive and headless modes

### Interactive

An interactive Claude profile must name a real `claude --channels ...` command. After preparation, the wrapper replaces itself with `exec`, preserving the tmux PTY, stdin, signals, and process surface. It does not hide Claude behind a headless supervisor child.

The wrapper preserves the normal channel selector written in the profile, such as `plugin:telegram@claude-plugins-official`. It does not add a development-channel bypass. It also does not add `--strict-mcp-config`, because strict mode suppresses Channels plugins; it adds only an owner-private `--mcp-config` overlay.

To keep raw Mail from being exposed after strict mode is removed, the wrapper examines this finite set of Claude configuration sources after applying the profile's `environment`:

| Source | Inspection and action |
| --- | --- |
| User | Top-level `mcpServers` in effective `CLAUDE_CONFIG_DIR/.claude.json`, or effective `HOME/.claude.json` when the former is unset |
| Local project | `projects[project root].mcpServers` in the same user JSON; use the exact `git rev-parse --show-toplevel` key inside Git and the exact `working_directory` key outside Git |
| Project | Every `.mcp.json` from the profile's `working_directory` through the filesystem root; put Mail aliases in same-named bound overlays and leave unrelated definitions unchanged |
| Enabled plugin | Apply `enabledPlugins` from effective user `settings.json`, then the working directory's `.claude/settings.json` and legacy `settings.local.json`, then the Git repository's effective root-local `settings.local.json`. A normal checkout or separate gitdir uses the current checkout root; a linked worktree uses the main checkout root. The wrapper follows Claude's working-directory legacy-local fallback only when otherwise valid root, `.git`, `.claude`, or resolved Git metadata has a different owner. A symlink, unknown type, or inspection failure is rejected so it cannot hide a source. Claude does not read user-config `settings.local.json` or intermediate shared/local ancestors, so they are not sources. Resolve installed plugins through the effective plugins-root inventory, marketplace registry and catalog, and exact ID before inspecting them |
| Selected plugin | Inspect installed plugins selected by `--channels plugin:...` and by a caller-supplied `--dangerously-load-development-channels plugin:...`, even when absent from the enabled map; the wrapper itself never adds a development selector |
| Explicit plugin | Inspect every profile `--plugin-dir` |

The effective plugins root is an absolute `CLAUDE_CODE_PLUGIN_CACHE_DIR` from the profile environment when set, otherwise `plugins/` under the effective config root. The plugins root and resolved `installPath` / `installLocation` must be owned by the local user and not group- or world-writable. The wrapper matches the exact `name@marketplace` and `installPath` in `installed_plugins.json`, the exact marketplace and absolute `installLocation` in `known_marketplaces.json`, and the exact plugin entry in that location's catalog. It does not infer identity from cache directory names. Marketplace `mcpServers` references resolve from the inventory `installPath`, not the catalog directory.

For a marketplace entry with `strict: false`, a missing manifest is valid and the entry's MCP definitions are inspected. As a safety superset that cannot miss Mail when current CLI source precedence changes, an existing root `.mcp.json` is also inspected. A manifest that declares component fields is a conflict. For `strict: true` or an omitted value, the manifest is required and the wrapper inspects the manifest, an optional root `.mcp.json`, and the marketplace entry. Same-named servers in separate sources are each inspected: benign/benign is allowed, while any Mail definition stops startup.

When a standalone source contains a Mail alias, the same local Mail endpoint, or a known Mail runner, only that **same name** is emitted in the bound-proxy overlay. Supported aliases, after ignoring ASCII case and removing `-` / `_`, are `orrerymail`, `agentmail`, `mcpagentmail`, `agentstackmail`, and `agentstack`. Only when no matching name exists does the wrapper emit one `orrery-mail` entry. For example, an existing `agent-mail` by itself produces and documents only `agent-mail`; it does not invent `orrery-mail`. `AGENTSTACK_PERSISTENT_MAIL_MCP_NAMES` carries the actual emitted names as a comma-separated value.

Claude's standalone precedence cannot suppress a same-named server supplied by a plugin. A plugin with a Mail alias or raw local endpoint therefore stops with `claude-plugin-mail-conflict`. An operator may explicitly disable that plugin or remove its `--plugin-dir`, but doing so also removes the plugin's channels and other features. The wrapper never rewrites or disables a plugin automatically.

The following are outside the finite contract and stop before `exec` instead of being overlooked:

- `working_directory` is a symlink, Git-discovery-changing environment is present, or the Git project root / separate gitdir / linked-worktree main-checkout root cannot be resolved safely: `claude-project-root-unsupported`. An ordinary non-Git directory with no `.git` marker is supported
- macOS `/Library/Application Support/ClaudeCode/managed-mcp.json` or `managed-settings.json` exists: `claude-managed-configuration-unsupported`; v1 rejects either file regardless of its contents, so changing only one Mail entry does not bypass the refusal
- the profile command contains `--settings`, `--setting-sources`, `--safe-mode`, or caller-owned `--mcp-config` / `--strict-mcp-config`
- a configuration, plugin inventory / marketplace registry / catalog, selected/enabled plugin, or manifest / marketplace reference cannot be read or interpreted

For managed configuration, the operator consults the administrator and startup remains blocked until reviewed managed support is added to the product. An arbitrarily renamed shell wrapper whose internal connection is not visible as a literal endpoint or known runner remains outside the guarantee. Diagnostics return fixed reasons and, when applicable, only the absolute `path` of the responsible file; they do not return config bodies, URL queries, or tokens.

An interactive Codex profile similarly `exec`s the real `codex`. The wrapper creates a fresh session-binding expectation on every run. It is normal for an idle composer to remain unbound until SessionStart claims the official session ID and receipt. `launch_kind=startup` describes wrapper process startup; it does not override a conversation resume inside a bridge. This does not migrate an old Codex UI session.

Keep `--channels`, channel state directories, search settings, and sequential bot startup in the profile command/environment or outer service definition. This wrapper does not solve Mail startup ordering.

### Headless

A headless profile names a bot bridge executable, not a raw `claude` or `codex` command, and adds:

```json
"interaction": "headless",
"bridge_contract": "orrery-mail-notification-reply-v1",
"command": ["/absolute/path/to/bot-bridge", "--config", "/absolute/path/to/bot.json"]
```

The bridge listens on the owner-private Unix socket supplied by the wrapper. It returns `status: replied` for the matching message ID only after the complete path has succeeded:

1. receive the Mail notification
2. hand it to the bot
3. send the bot's response back through Mail
4. return the bridge acknowledgement

The minimum wire contract is:

| Item | Contract |
| --- | --- |
| Socket | The bridge listens at `AGENTSTACK_PERSISTENT_WAKE_SOCKET` and, after binding, makes the socket owned by the same OS user with mode `0600` |
| Transport | `AF_UNIX` stream with one UTF-8 JSON object per line, terminated by `\n` |
| Timeout | Watcher setting `AGENTSTACK_HEADLESS_REPLY_TIMEOUT`; integer `1..300` seconds, with `300` used when absent or invalid |

Minimal request:

```json
{"version":1,"contract":"orrery-mail-notification-reply-v1","type":"mail-notification","agent_name":"HeadlessBot","message":{"id":42}}
```

Response only after the bot has completed the matching Mail reply:

```json
{"version":1,"contract":"orrery-mail-notification-reply-v1","status":"replied","message_id":42}
```

The same notification can be redelivered after a lost acknowledgement, timeout, or bridge restart. The bridge must make bot handoff and Mail reply idempotent using the message ID or an equivalent key; it must not assume that the product guarantees exactly-once replies.

A headless Claude bridge must read the path in `AGENTSTACK_PERSISTENT_MCP_CONFIG` and explicitly apply it as `--mcp-config "$AGENTSTACK_PERSISTENT_MCP_CONFIG"` when starting the real Claude CLI, or supply the equivalent explicit MCP configuration through an SDK. Merely inheriting this product-specific environment variable does not make Claude load it. `AGENTSTACK_PERSISTENT_MAIL_MCP_NAMES` tells the bot its real namespace; it is not a loader setting. Only interactive Claude has the overlay appended to its command by the wrapper. Headless mode does not receive the interactive source-inspection or alias-overlay guarantee, so the bridge itself must inspect its provider configuration and prevent conflicts with raw Mail definitions. The wrapper never adds `--strict-mcp-config`. A headless Codex bridge must preserve `CODEX_HOME` / `CODEX_SHARED_CODEX_DIR` and the per-run fresh `AGENTSTACK_CODEX_LAUNCH_BINDING` / `AGENTSTACK_CODEX_LAUNCH_ID` for its real Codex child; it must not replace them with another home or an old pair.

Merely listing tools is not this guarantee. When the acknowledgement is absent, expires, or the bridge stops, the watcher retains the signal for retry and never falls back to injecting an identically named tmux pane. This repository implements the delivery/acknowledgement boundary; it does not bundle a provider-specific Telegram bot bridge. Isolated fixtures verify the matching bridge acknowledgement, while real Mail → real provider bot → Mail reply remains deployment-specific acceptance work.

Dashboard `surface` continues to describe the display carrier, such as tmux. The API exposes profile `interaction` separately. The UI labels only the exceptional headless row as `BRIDGE · HEADLESS`; interactive and existing `unknown` rows do not change appearance.

## Restarting

Manual enrollment happens once during initial migration or explicit recovery. During an ordinary machine or bot restart, do not call `claim` or `recover`; start the wrapper and let it validate the saved credential.

```bash
exec "$HOME/.agentstack/bin/agentstack-persistent" run \
  --profile "$HOME/.agentstack/profiles/ChannelsBot.json"
```

A startup service or tmux script should make this its final `exec`. Do not hide the interactive process behind another child if the interactive surface must be retained.

### credential-unavailable

Only when restart reports `local-credential-unavailable` or the exact diagnostic `stage=local-token reason=credential-unavailable` should an operator stop the bot, begin again with `$HOME/.agentstack/bin/agentstack-enroll inspect`, and choose `recover` if the state is `server-token` plus a missing local credential. Do not have the model run it. Do not infer credential loss from a generic registration failure, HTTP 401/403, or a stopped Mail service.

### Resume Claude in DECK after retention expires

Use this procedure when retention expiry removed the child state and local credential and DECK reports `mail_reason: retention_expired`. The operator uses the original numeric ID, name, project, and connection pinned to the same Mail UUID.

1. Run `"$HOME/.agentstack/bin/agentstack-enroll" inspect --agent-id "$TARGET_ID" --project-key "$PROJECT_KEY" --connection "$CONNECTION" --name "$TARGET_NAME"`. Verify the target, `connection_pinned: true`, `retired: false`, `credential_state: server-token`, and a local credential state of `missing` or `missing-token-same-identity`.
2. Run `"$HOME/.agentstack/bin/agentstack-enroll" recover --agent-id "$TARGET_ID" --project-key "$PROJECT_KEY" --connection "$CONNECTION" --name "$TARGET_NAME"` once. Confirm `result: accepted` and `reason: operator-recover`. A previous successful recovery is sufficient while its receipt and saved credential are current.
3. Exit any running conversation-only session and choose **Resume** in DECK. DECK matches the recovery receipt issued after expiry against the current credential, authenticates the same Mail identity, and returns `resume_mode: mail`. Later DECK resumes can use the same credential.

Mail continues to reject `recover` for retired rows, and DECK rejects resumes after an explicit purge. The original child state is required when Claude needs its child-specific tool configuration and when resuming a Codex child.

## Applying the contract to another Mail instance or machine

Each machine uses its own local Mail and connection profile. In the second machine's terminal:

1. run `inspect` with that machine's connection profile
2. verify and pin that machine's Mail `server_instance_id`
3. select the numeric agent ID in that machine's project
4. run `claim` or `recover` on that machine if its state requires it
5. create and start a persistent profile specific to that machine

Do not copy the first machine's token, pending file, or receipt to the second machine. A numeric ID from the first machine need not identify the same row on the second. Identical hostnames, ports, URLs, or socket paths do not make two Mail instances identical; the persistent instance UUID is authoritative.

## Conditions that require stopping

Stop instead of creating an alias or recovering automatically when you see:

- `mail-control-unavailable`: restore the Mail service/management socket
- `server-identity-mismatch` / `connection-not-pinned`: verify the connection and UUID
- `agent-not-found` / `name-mismatch`: verify the project and numeric row
- `generation-conflict`: another operator/process updated first; inspect again
- `identity-conflict` / `local-identity-conflict`: do not reuse a local file as proof for another identity
- `agent-retired`: return to the normal creation or retirement workflow
- `profile-already-running`: use or stop the existing instance
- `claude-project-root-unsupported`: use stderr's `path` to correct a `working_directory` symlink, Git-root resolution, or worktree main-checkout resolution
- `claude-managed-configuration-unsupported`: v1 stops while a managed file exists; consult the administrator about reviewed product support
- `claude-plugin-mail-conflict`: explicitly disable the plugin or remove `--plugin-dir`, after accounting for the features that will be lost
- `claude-config-unreadable` / `claude-project-config-unreadable` / `claude-settings-unreadable` / `claude-plugin-inventory-unreadable` / `claude-plugin-marketplace-unreadable` / `claude-plugin-definition-unreadable` / `claude-plugin-unavailable` / `claude-settings-flag-unsupported`: repair stderr's `path` when present; otherwise do not guess the hidden source, and repair the config, plugin, or command category named by the fixed reason

Hand-editing secret files, using token-omission compatibility as ownership proof, or avoiding a collision with an alias is not recovery.

## Related documentation

- [Launchers and identity](launchers.md)
- [Troubleshooting](telemetry-troubleshooting.md)
- [Mail claim/enrollment design](https://github.com/gyroid-eth/orrery-telemetry/blob/master/docs/agentstack-mail-claim-enrollment-design.en.md)
- [Configuration](telemetry-configuration.md)
