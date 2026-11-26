# Updating a live ORRERY Mail service

> 日本語版: [agentstack-mail-update.md](../agentstack-mail-update.md)

This document covers shipping a new build of `agentstack_mail` onto a machine
where the service is already serving traffic. It describes the layout that
`scripts/install.sh` has managed since the bundled service became the only
provider. The earlier hand-run layout under `cutover-maintenance/` is history:
nothing the installer writes reads it, but a machine that once used it may
still carry its units and pointer file, so the pre-flight below checks for
them instead of assuming they are gone.

**Start with `--update-mail`.** With `--update-mail` the installer replaces
the running Mail with this checkout's build (see
"[Replacing the build with `--update-mail`](#replacing-the-build-with---update-mail)"
below). It builds the candidate, verifies it on a scratch port and backs up the
database while the running Mail keeps serving, then switches, and puts the
previous build back if the new one does not answer. A re-run without it
(default `keep`) does not switch and reports the difference with a `notice:`.
`AGENTSTACK_MAIL_UPDATE=auto` (opt-in) switches only when it safely can, and
otherwise keeps the running build and lets the install succeed. The manual procedure below is for
layouts `--update-mail` refuses, and for checking what each stage does.

**Scope.** The commands assume the default layout: install dir `~/.agentstack`,
no `--install-dir`, and no `AGENTSTACK_MAIL_*` overrides at install time. A
custom install is out of scope: the values this document reads from `env.sh`
are shell variables for your checks and are not passed on to the installer,
which would need its own `--install-dir` and overrides on every call, while
`agentstack-mailctl` locates `env.sh` through `AGENTSTACK_HOME`. None of that
has been exercised here. Note that `env.sh` records the service root as
`AGENTSTACK_MAIL_DIR`, while the installer's input for it is
`AGENTSTACK_MAIL_SERVICE_ROOT`.

**What has been executed.** The switch itself (hold the unit, stop, install,
verify: steps 5 to 7) was performed once on a live machine on 2026-09-18 with
the previous draft of this procedure; the 12 s outage is from that run. The
pre-flight (step 0) and the offline verification (step 3) were then re-run
exactly as written here against the installed service, and the stop
conditions of steps 2 and 3 were exercised in a harmless bash control with
stubbed `uv`, `git` and `lsof`, including a stale value left in the parent shell, a failing `git`, and a missing or failing `lsof`. Steps 4 to 7 as written here follow that live run
but have not been re-executed as a whole. The manual rollback in the rollback
section is read from the installer's source and has not been executed.
`--update-mail` is exercised by tests that start real servers on a temporary
HOME, a temporary state root and free ports (`tests/test_install_mail_update.py`):
the switch, going back to the previous build, the automatic rollback when the
new build does not answer, and not stopping anything when offline verification
fails. It has not yet been run on a live machine.

## What the installer does, and does not do

`install.sh` updates hooks, skills, the dashboard, `bin/`, `env.sh` and the
autostart units on every run. For ORRERY Mail it takes one of two paths:

- **Something answers the configured endpoint.** The installer sends it a
  `health_check`. If the answer carries a `database_url` that resolves to the
  expected state database, the listener is adopted: its render is recorded in
  `env.sh` and the service is **not** touched. If the port is occupied but the
  occupant does not answer as ORRERY Mail, or serves a different database, the
  run stops with an error. Once adopted, a running build that differs from
  this checkout's is, by default (`keep`), only reported with a `notice:`, and
  the service is **not** touched. `--update-mail` and `auto` go on to the
  switch below (none of them does anything when the package tree is identical
  in both commits). The dashboard's
  `/api/version` reports the package version, not the build behind the port.
- **Nothing answers.** The installer provisions a candidate for the checkout's
  exact commit (an absent candidate is built; an existing but incomplete one
  stops the run), renders a service env, starts the service through
  `agentstack-mailctl`, points `env.sh` and the autostart unit at the render,
  and checks that the served database is the shared one.

A manual update is therefore "stop the old service, then run the installer",
with the autostart unit held back so it cannot restart the old build in
between. A switch (`auto` or `--update-mail`) performs the step between those
two paths inside the installer.

## Replacing the build with `--update-mail`

```bash
./scripts/install.sh --print-mail-plan         # what would happen to Mail, one line (reads only)
./scripts/install.sh --dry-run                 # show the whole plan
./scripts/install.sh --update-mail             # switch (exit 1 if it cannot)
AGENTSTACK_MAIL_UPDATE=auto ./scripts/install.sh   # switch only when it safely can (opt-in)
./scripts/install.sh                           # never switch (default keep, same as --keep-mail)
```

| Option | When the running build differs | When it cannot switch or the switch fails |
| --- | --- | --- |
| `AGENTSTACK_MAIL_UPDATE=auto` (opt-in) | switch through steps 1 to 5 below, but only for a deployment managed by `agentstack-mailctl`, after verification passes, and when the expected outage is within `AGENTSTACK_MAIL_UPDATE_OUTAGE_BUDGET` (default 8 s) | keep the running build, warn, exit 0 |
| `--update-mail` (`AGENTSTACK_MAIL_UPDATE=update`) | switch; the outage budget does not apply (a person chose the time) | exit 1 |
| none, `--keep-mail` (`AGENTSTACK_MAIL_UPDATE=keep`) | do not switch; a `notice:` reports the difference | — |

The option is `--mail auto|update|keep` (or `--mail=VALUE`); `--update-mail`
and `--keep-mail` are aliases. An option wins over `AGENTSTACK_MAIL_UPDATE`
(cockpit's update.sh passes an option, so an outer environment value cannot
override it). `AGENTSTACK_MAIL_UPDATE` is a
per-run choice and is never recorded in `env.sh`, so a value chosen once does
not stick to every later update. `auto` is not the default yet: before it
becomes one, it needs an outage deadline that covers a rollback, and a check
that the previous build still runs on the updated database
([design note](https://github.com/gyroid-eth/orrery-telemetry/blob/master/docs/agentstack-mail-update-design.en.md)). The
expected outage is the time the candidate took to answer against the database
snapshot during verification, plus 1.5 s for the stop and the health poll.

The run ends with one machine-readable line; `--dry-run` prints the same
fields as `mail-plan:`. No value contains a space, and the reason is a fixed
code.

```text
mail-result: <installed|switched|kept|unchanged|refused|rolled-back> mode=<auto|update|keep> from=<commit> to=<commit> running=<commit> outage_s=<seconds> reason=<code>
mail-plan: <install|switch|keep|unchanged|refuse> mode=<…> running=<commit> to=<commit> reason=<code>
```

`from` is the build serving before this run (empty when there was none or it
could not be identified), `to` is this checkout's build, and `running` is the
build serving now (`to` after switched or installed, otherwise `from`). A
failed rollback, a refused `--update-mail`, or an interruption prints no line
and exits non-zero: a reader must treat a missing line as a failure.

Reason codes: `no_running_mail`, `newer_build`, `same_candidate`,
`same_package`, `keep_default`, `keep_requested`, `not_mailctl_managed`,
`deployment_unidentified`, `verify_failed`, `outage_over_budget`, `outage_unknown`,
`backup_failed`, `start_failed_rolled_back`, `adopted`, and (from
`--print-mail-plan` only) `plan_unavailable`. `--print-mail-plan` reads only the
pidfile, the render and git, needs no project key, and always exits 0 with one
line. It is a plan, not a promise: the real run may keep the running build
after verification.

Once the adoption path has identified the running deployment, and this
checkout's candidate (`candidates/<commit>/venv`) differs from it, the
installer proceeds in this order. The running Mail keeps serving through
steps 1 to 4.

1. **Prepare the candidate.** A complete one is reused; an absent one is built
   from a clean commit (an incomplete one stops the run). A new render is
   written.
2. **Verify it offline.** A snapshot of the shared database is taken with the
   SQLite backup API into `/tmp/orrery-mail-verify.*` (mode 700), and the
   candidate is started on a free loopback port (fixed with
   `AGENTSTACK_MAIL_UPDATE_VERIFY_PORT`) in an empty process environment. If
   that port is in use, or is the running Mail's own port, nothing is started
   and the result is `not-switched`, so that whatever answers there is never
   read as the candidate. The scratch service env comes from the same function as the
   production render, so database, archive, signals and management socket all
   point into the scratch directory. `health_check` on both `/mcp` and `/api`
   must return the scratch database, the startup DDL must not have removed or
   redefined an existing table, column, index or trigger, and
   `PRAGMA quick_check` must be `ok`. Progress is printed every 10 s while it
   waits. The snapshot is deleted whatever the outcome; only the server log is
   kept, at `mail-service/runtime/mail-update-verify.log`. Interrupted during
   verification by Ctrl-C or SIGTERM, the installer stops the scratch server and
   deletes the snapshot before exiting (status 130; the running Mail was never
   stopped).
3. **Back up the database** to
   `mail-service/backups/storage-<UTC>-before-<commit>.sqlite3` (mode 600); the
   three most recent are kept (`AGENTSTACK_MAIL_UPDATE_BACKUPS`). Only the build
   is rolled back automatically, never the database. The backup is for a person
   to use if the new build turns out to have damaged data.
4. **Switch.** `agentstack-mailctl stop` stops the previous runner (its stop
   marker holds the autostart sweep back), and `agentstack-mailctl start` runs
   the new render. Health on the endpoint must name the shared database and the
   pidfile must name the new runner.
5. **Put it back if it does not answer.** The new runner is stopped, the
   previous render is started again, and the same checks are made. The previous
   candidate, render and runner are immutable and were never rewritten.

`env.sh`, the autostart unit, `connections/local.json` and
`install-state.json` are then written from whichever deployment is actually
serving. `agent_mail.update` in `install-state.json` records the result
(`switched`, `rolled-back`, `not-switched`), the reason and its code, the
mode, how long Mail was actually down (`outage_seconds`), the previous and
requested render and candidate, and the backup path.

| Result | Mail | Exit status (`auto`) | Exit status (`--update-mail`) |
| --- | --- | --- | --- |
| `switched` | the new build | 0 | 0 |
| `not-switched` (failed in 1 to 3, or the expected outage is over budget) | the previous build, never stopped | 0 (warning) | 1 |
| `rolled-back` (4 failed, 5 succeeded) | the previous build, after an outage of seconds up to the start grace | 0 (warning) | 1 |
| rollback failed | possibly down; the error states the state and the next action | 1 (immediately) | 1 (immediately) |
| interrupted during the switch (Ctrl-C, SIGTERM, terminal closed) | left as is if `env.sh` already names the new build; otherwise the previous build is put back | 130 | 130 |

With `not-switched` and `rolled-back` the rest of the install still completes
against the previous build. With `--update-mail`, exit status 1 says that the
update that was asked for did not happen. Under `auto` no update was asked
for, so the run exits 0 and reports it through a warning and the result line.

**Going back to the previous build.** Pin the previous candidate and run the
same operation. Its render comes from the same inputs, has the same path, and
is reused as it is.

```bash
AGENTSTACK_MAIL_CANDIDATE_ID=<previous commit> \
AGENTSTACK_MAIL_SERVICE_VENV=~/.agentstack/mail-service/candidates/<previous commit>/venv \
  ./scripts/install.sh --update-mail
```

**What is and is not affected.**

- **Connections.** The server uses stateless HTTP, so a switch loses no
  session. Requests that arrive between the stop and the new server answering
  (12 s in the earlier manual run) are refused. How a client comes back
  differs (measured on 2026-10-02 with a temporary HOME and a separate port):
  the stdio proxy a launcher binds (Claude and Codex children) connects per
  call and works again from the next call. Top-level Codex (`url` in
  `~/.codex/config.toml`) came back on its next call even after 71 s.
  Top-level Claude Code (`type: http` in `~/.claude.json`) reconnected by
  itself after outages up to 15 s, but stayed disconnected after 18 s or more
  until orrery-mail was reconnected from `/mcp`. After every stop, however
  short, the installer prints how long Mail was down and what to check in each
  running Claude Code session (`/mcp` shows orrery-mail as connected, and a
  small call such as health_check succeeds). A Mail call that failed during the
  stop may still have been carried out, with only the answer lost, so check
  before repeating it (a send in the recipient's inbox or your outbox, a
  registration with `whois`, a spawn or resume in the dashboard). The canonical
  text is `mail_update_reconnect_hint` in `scripts/install.sh`; setup.sh shows
  the same lines. The installer's health check and
  a selftest show that Mail answers, not that a session that was already
  running got its connection back.
- **Tokens and credentials.** Agent tokens live in the shared database, and the
  client-side files (`~/.agentstack/runtime` and the like) are not touched. A
  build change does not change them.
- **Running sessions and bound proxies.** Nothing needs restarting or
  re-registering. The tests check that an agent registered before the switch
  sends and receives with the same owner token afterwards, and that a wrong
  token is refused. The `runtime_status` of a proxy a launcher bound
  returns `state: "bound"` and `agent_id: null`. That says only that the
  binding exists; Mail is not contacted. To see whether Mail is reachable,
  call `fetch_inbox` or another tool (a proxy from 2026.09.30.4 or earlier
  returned `state: "registering"` here even in normal operation, which was no
  evidence of being stuck either).
- **systemd timer (WSL2 and others).** The unit only reads `env.sh` and runs
  `agentstack-mailctl start`; it names no render. A timer firing after the
  switch finds the new build and does nothing (the tests run the unit's command
  as written to check this).
- **Enrollment.** `server_instance_id` is stored in the database's
  `mail_instances`, so it keeps its value. `expected_server_instance_id` in
  `connections/local.json` is preserved and only `mail_env` is rewritten to the
  new render. The management socket path is derived from the state root and
  stays the same.
- **Database, archive, signals.** The same state root stays in use. Only
  additive startup DDL is accepted; a build that removes or redefines an
  existing table, column, index or trigger stops at verification.
- **Autostart.** The stop marker holds the sweep back during the switch, and
  `start` clears it. The unit reads `env.sh`, so it starts the new render as
  soon as the installer has rewritten `env.sh`.

**Out of scope.** Only a runner started by `agentstack-mailctl` (the pidfile
names a live runner) is replaced. A listener whose deployment cannot be
identified and a service supervised directly by launchd are out of scope, and
nothing is stopped: `--update-mail` ends with an error, and `auto` keeps the
running build and carries on (`refused`). Overrides of the state root,
service root and endpoint (`AGENTSTACK_MAIL_*`, `AGENTSTACK_MCP_URL`) take the
same path, and the tests run with them overridden. A non-default
`--install-dir` is not refused either, but is not itself tested.

Time limits: waiting for the verification server,
`AGENTSTACK_MAIL_UPDATE_VERIFY_TIMEOUT` (default 120 s); waiting for the new
build to start, `AGENTSTACK_MAIL_UPDATE_START_GRACE` (default: the
controller's `AGENTSTACK_MAIL_START_GRACE`, 180 s). The rollback start waits
with the controller's default grace. The longest expected outage `auto` will
switch with: `AGENTSTACK_MAIL_UPDATE_OUTAGE_BUDGET` (default 8 s).

## Layout

Resolve these from the installed `env.sh`, not from assumptions: the state
root defaults to `~/.agentstack/mail` independently of the install dir, and
the endpoint, label prefix and roots are all configurable.

| Variable in `env.sh` | Meaning |
| --- | --- |
| `AGENTSTACK_MAIL_DIR` (service root) | `candidates/<commit>/venv`: immutable candidate, one venv per exact commit, built with `uv` from `packages/agentstack_mail`. `renders/<commit>-<id>/service.env` and `run-agentstack-mail.sh`: one render per (commit, venv, endpoint, state root); the id is a hash of exactly those inputs, so the same inputs name the same directory and the installer refuses to rewrite an existing one. `runtime/agentstack-mail.pid` (two lines: runner pid, runner path) and `runtime/agentstack-mail.log`. |
| `AGENTSTACK_MAIL_STATE_ROOT` (state root) | `storage.sqlite3` (WAL mode), `archive/`, `signals/`. Shared state, not part of any candidate, fixed across deployments. |
| `AGENTSTACK_MAIL_ENV` | The render the controller and the autostart unit start. |
| `AGENTSTACK_MCP_URL` | The endpoint; its port is the one to watch. |
| `AGENTSTACK_PYTHON` | The interpreter candidates are built with. |

The autostart unit is `<label prefix>.mail` (`org.agentstack.mail` unless
`AGENTSTACK_LABEL_PREFIX` was set): a launchd job every 300 s on macOS, a
`.timer` of the same name on systemd. It runs `agentstack-mailctl start`,
which reads `env.sh`. Within what the installer manages there is no second
supervisor; the pre-flight checks for leftovers of the older layout.

## Principles

- **Candidates are immutable.** A new build is a new `candidates/<commit>`
  directory. Never run `uv venv` or `pip install` against one that exists.
  The previous one stays on disk untouched; it is the rollback.
- **The database is shared state.** A build that would alter the schema on
  start needs its own migration plan and is out of scope here. Check the tree
  diff of `packages/agentstack_mail/src` for DDL before you begin.
- **Verify before the switch, not after.** Everything before the stop runs in
  an isolated process environment against a scratch port and a consistent
  snapshot of the database.
- **Ask the port which build is serving.** Not `launchctl print`, not the
  pidfile, not your notes, not the package version.

## Procedure

Each step is a shell function: define it, then call it as
`step_N || echo "step N failed"` and stop at the first failure. A function
returns non-zero at the first check that fails and runs nothing after it;
this is why the steps are not one long block. Run them in `bash`; the
pre-flight has also been checked under `zsh`.

0. **Pre-flight: read the installed values.** `env.sh` is written with
   `shlex.quote`, so the right-hand sides are unquoted by a shell, in a
   subshell so nothing leaks. Every required value must be present.

   ```bash
   INSTALL=~/.agentstack
   REPO=<clean checkout at the commit to deploy>
   port_free() {  # 0 only when lsof ran and found no listener on TCP port $1
     local out err rc
     command -v lsof >/dev/null 2>&1 || { echo "lsof is not installed" >&2; return 1; }
     err=$(mktemp) || return 1
     out=$(lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>"$err"); rc=$?
     if [ -s "$err" ]; then echo "lsof failed:" >&2; cat "$err" >&2; rm -f "$err"; return 1; fi
     rm -f "$err"
     [ $rc -ne 0 ] || { echo "port $1 is occupied:" >&2; echo "$out" >&2; return 1; }
     [ $rc -eq 1 ] && [ -z "$out" ] || { echo "lsof exited with status $rc without an error message; not treating port $1 as free" >&2; return 1; }
   }
   listener_pid() {  # prints the pid listening on TCP port $1; fails when there is none or lsof failed
     local out err rc pid
     command -v lsof >/dev/null 2>&1 || { echo "lsof is not installed" >&2; return 1; }
     err=$(mktemp) || return 1
     out=$(lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>"$err"); rc=$?
     if [ -s "$err" ]; then echo "lsof failed:" >&2; cat "$err" >&2; rm -f "$err"; return 1; fi
     rm -f "$err"
     [ $rc -eq 0 ] || { echo "nothing is listening on port $1" >&2; return 1; }
     pid=$(printf '%s\n' "$out" | awk 'NR>1{print $2; exit}')
     [ -n "$pid" ] || { echo "lsof reported a listener on port $1 but no pid could be read" >&2; return 1; }
     printf '%s\n' "$pid"
   }
   step_0() {
     local assignments
     [ -f "$INSTALL/env.sh" ] || { echo "no env.sh under $INSTALL" >&2; return 1; }
     assignments=$(
       set +u
       unset AGENTSTACK_PYTHON AGENTSTACK_MCP_URL AGENTSTACK_MAIL_DIR AGENTSTACK_MAIL_STATE_ROOT AGENTSTACK_MAIL_ENV AGENTSTACK_LABEL_PREFIX
       . "$INSTALL/env.sh" >/dev/null || exit 1
       for k in AGENTSTACK_PYTHON AGENTSTACK_MCP_URL AGENTSTACK_MAIL_DIR AGENTSTACK_MAIL_STATE_ROOT AGENTSTACK_MAIL_ENV; do
         eval "v=\${$k:-}"; [ -n "$v" ] || { echo "env.sh does not define $k" >&2; exit 1; }
       done
       for k in AGENTSTACK_PYTHON AGENTSTACK_MCP_URL AGENTSTACK_MAIL_DIR AGENTSTACK_MAIL_STATE_ROOT AGENTSTACK_MAIL_ENV AGENTSTACK_LABEL_PREFIX; do
         eval "v=\${$k:-}"; printf '%s=%q\n' "$k" "$v"
       done
     ) || { echo "could not read the required values from $INSTALL/env.sh" >&2; return 1; }
     eval "$assignments"
     PY=$AGENTSTACK_PYTHON; SVC=$AGENTSTACK_MAIL_DIR; STATE=$AGENTSTACK_MAIL_STATE_ROOT
     OLD_ENV=$AGENTSTACK_MAIL_ENV; LABEL="${AGENTSTACK_LABEL_PREFIX:-org.agentstack}.mail"
     [ -x "$PY" ] || { echo "AGENTSTACK_PYTHON is not executable: $PY" >&2; return 1; }
     [ -f "$OLD_ENV" ] || { echo "current render env is missing: $OLD_ENV" >&2; return 1; }
     PORT=$("$PY" -c 'import sys,urllib.parse;print(urllib.parse.urlparse(sys.argv[1]).port or "")' "$AGENTSTACK_MCP_URL")
     [ -n "$PORT" ] || { echo "no port in AGENTSTACK_MCP_URL" >&2; return 1; }
     SHA=$(git -C "$REPO" rev-parse HEAD) || return 1
     echo "python=$PY service_root=$SVC state_root=$STATE port=$PORT label=$LABEL sha=$SHA"
   }
   step_0 || echo "step 0 failed"
   ```

1. **Gate on the test suite at that commit** (dev venv, see
   `CONTRIBUTING.md`): `PYTHONPATH=. .venv/bin/python -m pytest -q` green in a
   clean single run, and `packages/agentstack_mail/tests` green as well.

2. **Build the candidate ahead of time**, unless it already exists and is
   complete. This keeps `pip install` out of the outage; the installer reuses
   a complete candidate at this path and stops on an incomplete one.

   ```bash
   step_2() {
     local status
     V="$SVC/candidates/$SHA/venv"
     if [ -x "$V/bin/agentstack-mail" ] && [ -x "$V/bin/agentstack-mail-service" ] && [ -x "$V/bin/agentstack-mail-migrate" ]; then
       echo "candidate complete; not touching it"; return 0
     fi
     [ ! -e "$V" ] || { echo "candidate exists but is incomplete: $V" >&2; return 1; }
     status=$(git -C "$REPO" status --porcelain -- packages/agentstack_mail) || { echo "git status failed in $REPO" >&2; return 1; }
     [ -z "$status" ] || { echo "packages/agentstack_mail is dirty" >&2; return 1; }
     uv venv --python "$PY" "$V" || return 1
     uv pip install --python "$V/bin/python" "$REPO/packages/agentstack_mail" || return 1
     [ -x "$V/bin/agentstack-mail" ] && [ -x "$V/bin/agentstack-mail-service" ] && [ -x "$V/bin/agentstack-mail-migrate" ]
   }
   step_2 || echo "step 2 failed"
   ```

3. **Verify the candidate offline, in an isolated environment.** The server
   reads configuration through python-decouple, which prefers the process
   environment over the env file, so a shell that has sourced `env.sh` (or
   any `AGENTSTACK_MAIL_*` variable) would point the scratch server at the
   live database. Start it with an empty environment. Take the database
   snapshot through SQLite's backup API, not `cp`: the live file is in WAL
   mode and a plain copy of the main file can miss committed pages. The
   snapshot contains credentials, so keep it private and delete it after.

   After copying the live render env, rewrite every setting that names a
   location to the scratch directory. A setting left out of the rewrite keeps
   pointing where the live service does, and the scratch server tries to open
   the live resource (when the enrollment management socket was added, this
   made the scratch server fail with `management socket is already active`).
   `scratch_env_isolated` stops when a line copied unchanged names a path under
   an existing directory. If it stops, add a rewrite for that setting to `sed`.

   ```bash
   probe() {  # probe <url> <tool> '<json arguments>'  → prints the JSON-RPC response
     "$PY" - "$1" "$2" "$3" <<'PY'
   import json, sys, urllib.request
   url, tool, args = sys.argv[1:]
   body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": tool, "arguments": json.loads(args)}}
   req = urllib.request.Request(url, data=json.dumps(body).encode(),
         headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
   print(urllib.request.urlopen(req, timeout=15).read().decode())
   PY
   }
   scratch_env_isolated() {  # scratch_env_isolated <live env> <scratch env>
     # 1 when a line copied unchanged from the live env names a real location
     local line key v d bad=0
     while IFS= read -r line; do
       case "$line" in AGENTSTACK_MAIL_*=*) ;; *) continue ;; esac
       grep -qxF -- "$line" "$1" || continue
       key=${line%%=*}; v=${line#*=}; v=${v#[\'\"]}; v=${v%[\'\"]}; v=${v#*:///}
       case "$v" in
         /*) d=$(dirname "$v")
             if [ "$d" != / ] && [ -d "$d" ]; then
               echo "scratch env still points $key at the live location $v; rewrite it to \$S" >&2; bad=1
             fi ;;
       esac
     done < "$2"
     return $bad
   }
   step_3() {
     local S SPORT=18799 SPID rc=1 r
     [ -x "$V/bin/agentstack-mail" ] || { echo "candidate server binary is missing: $V (run step 2)" >&2; return 1; }
     port_free "$SPORT" || return 1
     S=$(mktemp -d) || return 1
     chmod 700 "$S"; mkdir -p "$S/state/archive" "$S/state/signals"
     "$PY" - "$STATE/storage.sqlite3" "$S/state/storage.sqlite3" <<'PY' || { rm -rf "$S"; return 1; }
   import sqlite3, sys
   src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True); dst = sqlite3.connect(sys.argv[2])
   src.backup(dst); dst.close(); src.close()
   PY
     sed -e "s#^AGENTSTACK_MAIL_HTTP_PORT=.*#AGENTSTACK_MAIL_HTTP_PORT=$SPORT#" \
         -e "s#^AGENTSTACK_MAIL_DATABASE_URL=.*#AGENTSTACK_MAIL_DATABASE_URL=sqlite+aiosqlite:///$S/state/storage.sqlite3#" \
         -e "s#^AGENTSTACK_MAIL_STORAGE_ROOT=.*#AGENTSTACK_MAIL_STORAGE_ROOT=$S/state/archive#" \
         -e "s#^AGENTSTACK_MAIL_NOTIFICATIONS_SIGNALS_DIR=.*#AGENTSTACK_MAIL_NOTIFICATIONS_SIGNALS_DIR=$S/state/signals#" \
         -e "s#^AGENTSTACK_MAIL_MANAGEMENT_SOCKET=.*#AGENTSTACK_MAIL_MANAGEMENT_SOCKET=$S/mgmt.sock#" \
         "$OLD_ENV" > "$S/service.env"
     grep -qE '^AGENTSTACK_MAIL_HTTP_HOST=(127\.0\.0\.1|localhost|::1)$' "$S/service.env" || { echo "scratch env is not loopback" >&2; rm -rf "$S"; return 1; }
     scratch_env_isolated "$OLD_ENV" "$S/service.env" || { rm -rf "$S"; return 1; }
     env -i HOME="$HOME" PATH=/usr/bin:/bin AGENTSTACK_MAIL_ENV_FILE="$S/service.env" \
       "$V/bin/agentstack-mail" > "$S/server.log" 2>&1 &
     SPID=$!
     for _ in $(seq 1 100); do
       kill -0 "$SPID" 2>/dev/null || { echo "scratch server exited early; see $S/server.log" >&2; return 1; }
       curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$SPORT/api" && break; sleep 0.2
     done
     if r=$(probe "http://127.0.0.1:$SPORT/mcp" health_check '{}') && [ "${r#*$S/state/storage.sqlite3}" != "$r" ] \
        && r=$(probe "http://127.0.0.1:$SPORT/api" health_check '{}') && [ "${r#*$S/state/storage.sqlite3}" != "$r" ] \
        && r=$(probe "http://127.0.0.1:$SPORT/api" whois '{"project_key": "<a project key from the live database>", "agent_name": "<an agent in it>"}') && [ "${r#*\"<an agent in it>\"}" != "$r" ] \
        && r=$(probe "http://127.0.0.1:$SPORT/api" health_check '{"nonce": "canary-value"}') && [ "${r#*canary-value}" = "$r" ] && [ "${r#*isError\":true}" != "$r" ] \
        && [ "$(grep -c canary-value "$S/server.log")" = 0 ]; then
       echo "candidate verified on scratch port $SPORT"; rc=0
     else
       echo "candidate failed offline verification; log kept at $S/server.log" >&2
     fi
     kill "$SPID" 2>/dev/null; wait "$SPID" 2>/dev/null
     [ $rc -eq 0 ] && rm -rf "$S"
     return $rc
   }
   step_3 || echo "step 3 failed"
   ```

   Success is all of: both paths answer `health_check` with the scratch
   `database_url`; the read returns the record; the rejected call reports an
   error that names no caller-supplied value, and the scratch log has none.
   Anything else means the candidate is not ready and the procedure stops.

4. **Record the current deployment and dry-run the installer** while
   everything is still running. The dry run must exit 0 and say it would
   reuse the existing service; if it says anything else, the live state is
   not what you think and the switch must wait.

   ```bash
   step_4() {
     local pid log
     pid=$(listener_pid "$PORT") || return 1
     echo "OLD candidate: $(ps -o command= -p "$pid")"          # keep this line
     echo "OLD render:    $OLD_ENV"                              # keep this line
     log=$(mktemp) || return 1
     ( cd "$REPO" && bash scripts/install.sh --scoped --dry-run ) > "$log" 2>&1 || { echo "dry run failed; see $log" >&2; return 1; }
     grep -q "would reuse existing ORRERY Mail service" "$log" || { echo "dry run did not plan to reuse the running service; see $log" >&2; return 1; }
     rm -f "$log"
   }
   step_4 || echo "step 4 failed"
   ```

5. **Hold the autostart unit.** It starts whatever `env.sh` names, and until
   the installer rewrites `env.sh` that is the old render. If it fires between
   your stop and the installer's start, the old build returns and the
   installer adopts it.

   macOS:

   ```bash
   step_5() {
     launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
     ! launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || { echo "$LABEL is still loaded" >&2; return 1; }
     ! grep -lE 'agentstack-mail-service|cutover-maintenance|current-deployment\.env' ~/Library/LaunchAgents/*.plist 2>/dev/null | grep . || { echo "older-layout units above must be disabled first" >&2; return 1; }
     ! crontab -l 2>/dev/null | grep -E 'agentstack-mail-service|cutover-maintenance|current-deployment\.env' || { echo "older-layout cron entries above must be disabled first" >&2; return 1; }
   }
   step_5 || echo "step 5 failed"
   ```

   systemd:

   ```bash
   step_5() {
     systemctl --user stop "$LABEL.timer"
     ! systemctl --user is-active --quiet "$LABEL.timer" || { echo "$LABEL.timer is still active" >&2; return 1; }
     ! systemctl --user list-units --all --no-legend 2>/dev/null | grep -E 'agentstack-mail-service|cutover-maintenance' || { echo "older-layout units above must be disabled first" >&2; return 1; }
     ! crontab -l 2>/dev/null | grep -E 'agentstack-mail-service|cutover-maintenance|current-deployment\.env' || { echo "older-layout cron entries above must be disabled first" >&2; return 1; }
   }
   step_5 || echo "step 5 failed"
   ```

6. **Stop, then install.** This is the outage window. Measured once with the
   candidate pre-built: 12 s from stop to "ready". `agentstack-mailctl stop`
   signals the managed runner it recorded and waits until the endpoint no
   longer answers; it refuses to stop a process it did not start.

   ```bash
   step_6() {
     local log
     "$INSTALL/bin/agentstack-mailctl" stop || return 1
     port_free "$PORT" || return 1
     log=$(mktemp) || return 1
     ( cd "$REPO" && bash scripts/install.sh --scoped ) 2>&1 | tee "$log"
     [ "${PIPESTATUS[0]}" -eq 0 ] || { echo "installer failed; see $log" >&2; return 1; }
     ! grep -q "existing ORRERY Mail listener detected" "$log" || { echo "the old build came back during the window and was adopted: not deployed" >&2; return 1; }
     grep -q "candidate venv $SVC/candidates/$SHA/venv" "$log" || { echo "installer did not use candidate $SHA" >&2; return 1; }
     rm -f "$log"
   }
   step_6 || echo "step 6 failed"
   ```

   Expected lines in the installer output, in this order:
   `no native listener found`;
   `reuse immutable ORRERY Mail candidate venv .../candidates/$SHA/venv`;
   `render namespaced ORRERY Mail service env .../renders/$SHA-<id>/service.env`;
   `ORRERY Mail started (pid ..., ready after Ns)`;
   `ORRERY Mail will restart at login`. If instead it reports
   `existing ORRERY Mail listener detected`, something started the old build
   during the window and the installer adopted it: the deployment did **not**
   happen. Find what started it, stop again, and repeat this step.

   A shell that has sourced the previous `env.sh` is fine: the installer
   forgives an inherited `AGENTSTACK_MAIL_ENV` only when it equals the value in
   the installed `env.sh`, sits under the service root's `renders/`, and
   `AGENTSTACK_MAIL_SERVICE_ENV` is not set. Any other value stops the run.

7. **Prove production, then say done.** Every check must hold; if one does
   not, the deployment is not complete.

   ```bash
   step_7() {
     local pid new_env r
     pid=$(listener_pid "$PORT") || return 1
     # the venv's python can show up as Homebrew's Python.app (measured on a second Mac); match the executable under venv/bin/
     ps -o command= -p "$pid" | grep -q "candidates/$SHA/venv/bin/" || { echo "port $PORT is not served by candidate $SHA" >&2; return 1; }
     new_env=$( set +u; . "$INSTALL/env.sh" || exit 1; printf '%s' "$AGENTSTACK_MAIL_ENV" )
     [ "${new_env#$SVC/renders/$SHA-}" != "$new_env" ] || { echo "env.sh does not point at a render of $SHA: $new_env" >&2; return 1; }
     sed -n 2p "$SVC/runtime/agentstack-mail.pid" | grep -q "$(dirname "$new_env")/" || { echo "pidfile runner is not inside the new render" >&2; return 1; }
     if [ "$(uname)" = Darwin ]; then launchctl list | grep -q "$LABEL" || { echo "$LABEL is not registered" >&2; return 1; }
     else systemctl --user is-active --quiet "$LABEL.timer" || { echo "$LABEL.timer is not active" >&2; return 1; }; fi
     "$INSTALL/bin/agentstack-mailctl" status || return 1
     "$INSTALL/bin/agentstack-selftest" || return 1
     r=$(probe "$AGENTSTACK_MCP_URL" health_check '{}') && [ "${r#*$STATE/storage.sqlite3}" != "$r" ] || { echo "live health_check does not report the shared database" >&2; return 1; }
     echo "deployed $SHA; old render was $OLD_ENV, new render is $new_env"
   }
   step_7 || echo "step 7 failed"
   ```

   Repeat the step-3 probes against the real endpoint, including the rejected
   call if the change touched argument handling or logging. Record `$SHA`,
   the old and new render paths, the outage and the probe results in a
   deployment note.

## Rollback

Going back with `--update-mail` and the previous candidate pinned is the route
the tests exercise (section above). What follows is the manual route.

**Read from the installer's source; not executed.** Treat it as a plan to
verify on a scratch install before relying on it.

The previous candidate and render are still on disk. Rolling back is the
forward procedure with the previous commit, with two differences. First,
`AGENTSTACK_MAIL_CANDIDATE_ID` only names the candidate directory: an absent
directory would be built from the *current* checkout's package under the old
name (an existing but incomplete one stops the installer). So verify the old
candidate is complete before stopping anything, and pin it explicitly with
`AGENTSTACK_MAIL_SERVICE_VENV`, which makes the installer stop instead of
building. Second, everything else the installer manages still comes from the
checkout you run it from.

```bash
rollback() {
  local OLD_SHA=$1 OLD_V
  OLD_V="$SVC/candidates/$OLD_SHA/venv"
  [ -x "$OLD_V/bin/agentstack-mail" ] && [ -x "$OLD_V/bin/agentstack-mail-service" ] && [ -x "$OLD_V/bin/agentstack-mail-migrate" ] \
    || { echo "old candidate is not complete: $OLD_V" >&2; return 1; }
  step_5 || return 1
  "$INSTALL/bin/agentstack-mailctl" stop || return 1
  port_free "$PORT" || return 1
  ( cd "$REPO" && AGENTSTACK_MAIL_CANDIDATE_ID="$OLD_SHA" AGENTSTACK_MAIL_SERVICE_VENV="$OLD_V" bash scripts/install.sh --scoped ) || return 1
  SHA=$OLD_SHA step_7
}
rollback <previous commit> || echo "rollback failed"
```

The unit follows `env.sh`, so there is no separate pointer to update.

## Checking which build is actually serving

The deployment you performed and the build answering the port are different
claims. Ask the port:

```bash
pid=$(lsof -nP -iTCP:<port> -sTCP:LISTEN | awk 'NR>1{print $2}')
ps -o command= -p "$pid"          # which candidate's python is this
```

The pid in `agentstack-mail.pid` is the runner, not the server; the server is
its child, and it is the child that holds the descriptors and answers
requests. Measuring the runner and concluding "the fix is live" is a mistake
that has already been made here. So is reading the dashboard's `/api/version`:
that is the package version, and it changes on every re-run whether or not
Mail was switched.

**What the running build lacks.** `agentstack-doctor` reads the running Mail's
`tools/list` once, and for each feature this install relies on
(`scripts/lib/mail_required_features.json`; for example `existing_agent_id` on
`register_agent`, which lets an old-format Claude child resume with Mail) that
is missing, prints a `warn:` with the fix (`--update-mail`). Mail itself works,
so doctor's exit status does not change. It ends with one line for setup.sh to
read:

```text
mail-features: status=<ok|missing|unknown> missing=<tool.parameter,...> running=<commit>
```

`unknown` means Mail could not be asked, not that every feature is present.

**The notice about an old Mail.** When the Mail this run did not replace is
**shown to be** older than this checkout's build (its commit is an ancestor of
the checkout's), install.sh prints a short notice before the result line. When
the running build is newer, it says that the checkout is older and should be
pulled before updating Mail from it; when which is newer cannot be told
(diverged, or not a commit of this checkout), it says so. Neither suggests an
update from this checkout, since an update from an older checkout would take
Mail back. A missing feature is reported in every case, but it is not proof
that updating from this checkout adds it, so then the notice says to update
from a checkout at least as new as the running build. The notice gives what does not work, how to update
(`./scripts/install.sh --mail update` / `./scripts/setup.sh --mail update`),
the risk of updating (Mail usually stops for a few seconds, but if the new
build does not start, the switch and the return to the old one can take
minutes, with no short limit guaranteed; Mail calls fail meanwhile; children
and Codex reconnect by themselves; a top-level Claude Code session may not:
with Claude Code 2.1.287 in testing, stops of 8 s and 15 s reconnected by
themselves and stops of 18 s and 19 s did not), and
what to do then (in that session, `/mcp`, choose orrery-mail, shown as
"✘ failed", then Reconnect, not Authenticate). doctor prints the same notice
when a feature is missing. The text lives in `scripts/lib/mail_update_notice.py`;
the cockpit's setup.sh shows it through `install.sh --print-mail-update-advice`
(reads only, always exits 0, prints only when Mail is shown to be older, and
leaves out the update command lines).

## History

Before the bundled service, deployments were hand-run under
`cutover-maintenance/` with `agentstack-mail-service render/stop/start` and a
supervisor that read a pointer file. That supervisor silently restored an old
build once (2026-08-26), which is why the installer's layout has one
supervisor that reads `env.sh`, and why step 5 looks for leftovers. The
cutover receipts under `cutover-maintenance/` pin the candidate that performed
the 2026-08 cutover; they describe events, not the currently active build, and
nothing in this procedure edits them.
