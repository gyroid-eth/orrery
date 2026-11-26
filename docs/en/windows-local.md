Community-maintained / experimental. Verified environment: Windows 11 build 26200, CPython 3.12.10, Windows PowerShell 5.1.26100.9168.

# Experimental native Windows dashboard startup

This development helper starts the bundled Mail HTTP entry point and dashboard
from a checkout, validates readiness and opens the browser. It is not the
standard installer. The maintainer's preferred Windows direction is WSL2;
native Windows remains unsupported. See [tracking issue #3](https://github.com/gyroid-eth/orrery-telemetry/issues/3).

Prepare Python 3.11+, Git and the repository `.venv` once using
[CONTRIBUTING.md](https://github.com/gyroid-eth/orrery-telemetry/blob/master/CONTRIBUTING.md), with `.venv\Scripts\python.exe` on Windows.
The venv needs the bundled Mail package and its dependencies. No global CLI
settings, managed instructions or Windows service registration are installed.
Native tmux is needed for runtime session discovery; without it the helper
prints a warning and only the Mail-backed views are available.

After that preparation, open PowerShell and run:

```powershell
& 'C:\path\to\orrery-telemetry\scripts\windows\start-windows.ps1' -Project 'C:\path\to\your-project'
```

Use `-DryRun` first to inspect the actual database, project and process plan.
The default state directory is `%LOCALAPPDATA%\orrery-telemetry\local`;
Mail uses port 18765 and the dashboard uses 8770. State persists across restarts.
For an existing development setup, supply its actual `-StateDirectory`,
`-MailPort` and `-DashboardPort`; the directory must contain its `storage.sqlite3`.
Use `-PythonCommand` to select an existing development interpreter and
`-NoBrowser` to suppress browser opening.

The helper reuses Mail only after its health response identifies the expected
database. It checks an existing dashboard's process environment for the same
database, project and Mail URL, then probes its version, agents and graph APIs.
An unexpected listener stops startup. Reused processes are never stopped.
Environment settings apply only to children, and each child starts in the
checkout directory, so launching PowerShell elsewhere does not break imports.

When it starts processes, keep the PowerShell window open. Press Enter or
Ctrl+C to stop only those processes; closing the window forcibly is not a
managed shutdown. Logs are under the state directory. If graceful shutdown is
unavailable, the helper reports that it terminated its child; Mail's existing
startup recovery handles archive files left uncommitted. A failed child ends
the supervisor and stops the other child it owns. There is no auto-restart or
Windows login service.

The ready browser supports dashboard inspection. This does not validate native
NEW AGENT, terminal jump, child delegation, resume, mail watcher, hooks or the
Codex Desktop Bridge. Starting a Codex agent is a separate launcher concern.
Long Windows Mail archive paths use the storage fix already merged in
[PR #7](https://github.com/gyroid-eth/orrery-telemetry/pull/7).

Validation covers real fresh Mail/dashboard startup, reuse without new PIDs,
database/project conflicts, occupied ports, shutdown of owned processes and
persistence of the database. Full native Windows support is not claimed.
