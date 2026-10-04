"""scripts/update.sh updates orrery-telemetry, then the cockpit, in one
command, and changes nothing when it cannot finish (2026-09-30).

Run from bridge/: ``python -m pytest tests/test_update_sh.py``.

Hermetic: an empty HOME, fake orrery-telemetry and cockpit checkouts cloned
from bare remotes in a temporary folder, a fake install.sh and Codex plugin
refresh that only record their calls, and a fake dashboard. Nothing here
reads or changes an installed stack.
"""
from __future__ import annotations

import json
import os
import shutil
import shlex
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

UPDATE_SH = Path(__file__).resolve().parents[2] / "scripts" / "update.sh"
BASH = "/bin/bash" if Path("/bin/bash").exists() else shutil.which("bash")

FAKE_INSTALL = """#!/bin/sh
# Records the call, and the cockpit's commit at that moment (for the order).
printf 'install cockpit=%s\\n' "$(git -C "$FAKE_COCKPIT" rev-parse HEAD)" >> "$FAKE_LOG"
# And the settings install.sh takes only from its environment.
printf 'port=%s label=%s terminal=%s mcp=%s\\n' "${AGENTSTACK_PORT:-}" "${AGENTSTACK_LABEL_PREFIX:-}" \\
  "${AGENTSTACK_TERMINAL:-}" "${AGENTSTACK_MCP_URL:-}" > "$FAKE_LOG.env"
[ -z "${FAKE_INSTALL_FAIL:-}" ] || { echo "fake install failed" >&2; exit 3; }
"""
FAKE_PLUGIN = """#!/bin/sh
printf 'plugin %s\\n' "$*" >> "$FAKE_LOG"
"""


# A fixed identity and no system or user git config, without touching os.environ.
GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def git(cwd: Path | None, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV}).stdout.strip()


class Stack:
    """Two checkouts with bare remotes, and a place to push new commits from."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.home = tmp / "home"
        self.agentstack = self.home / ".agentstack"
        self.agentstack.mkdir(parents=True)
        self.log = tmp / "calls.log"
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.home),
            "AGENTSTACK_HOME": str(self.agentstack),
            **GIT_ENV,
        }
        self.telemetry = self.repo("telemetry", {
            "scripts/install.sh": FAKE_INSTALL,
            "scripts/install-codex-app-integration.sh": FAKE_PLUGIN,
        })
        self.cockpit = self.repo("cockpit", {"scripts/update.sh": UPDATE_SH.read_text()})
        self.env.update(FAKE_LOG=str(self.log), FAKE_COCKPIT=str(self.cockpit))
        (self.agentstack / "install-state.json").write_text(json.dumps({"repo_root": str(self.telemetry)}))

    def repo(self, name: str, files: dict[str, str]) -> Path:
        bare = self.tmp / f"{name}.git"
        seed = self.tmp / f"{name}-seed"
        git(None, "init", "-q", "--bare", "-b", "master", str(bare))
        git(None, "clone", "-q", str(bare), str(seed))
        for rel, text in files.items():
            path = seed / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            path.chmod(0o755)
        (seed / "VERSION").write_text("1\n")
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", "first")
        git(seed, "push", "-q", "origin", "HEAD:master")
        checkout = self.tmp / name
        git(None, "clone", "-q", str(bare), str(checkout))
        return checkout

    def publish(self, name: str) -> str:
        """A new commit on the remote, as a release would be."""
        seed = self.tmp / f"{name}-seed"
        (seed / "VERSION").write_text((seed / "VERSION").read_text() + "1\n")
        git(seed, "commit", "-q", "-am", "release")
        git(seed, "push", "-q", "origin", "HEAD:master")
        return git(seed, "rev-parse", "HEAD")

    def head(self, name: str) -> str:
        return git(getattr(self, name), "rev-parse", "HEAD")

    def tracking(self, name: str) -> str:
        return git(getattr(self, name), "rev-parse", "origin/master")

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def install_env(self) -> str:
        return Path(str(self.log) + ".env").read_text().strip()

    def install_codex_plugin(self, enabled: bool = True, tool: str = "agentstack-codex-app") -> None:
        """What install-codex-app-integration.sh records; the core installer
        also creates the folder, but never this file."""
        folder = self.agentstack / "integrations" / "codex_app"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "install-state.json").write_text(json.dumps(
            {"tool": tool, "plugin": {"enabled": enabled, "id": "agentstack-codex-app@agentstack-local"}}))

    def update(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run([BASH, str(self.cockpit / "scripts" / "update.sh"), *args],
                              env={**self.env, **env}, capture_output=True, text=True, timeout=60)


@pytest.fixture
def stack(tmp_path):
    return Stack(tmp_path)


@pytest.fixture
def dashboard():
    """A fake dashboard answering /api/version, so the summary does not wait."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = json.dumps({"name": "orrery-telemetry", "version": "2099.01.01", "api": 2}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


# ---------------------------------------------------------------- positive

def test_positive_both_are_updated_telemetry_first(stack, dashboard):
    new_telemetry = stack.publish("telemetry")
    new_cockpit = stack.publish("cockpit")
    old_cockpit = stack.head("cockpit")
    result = stack.update(ORRERY_DASHBOARD_URL=dashboard)
    assert result.returncode == 0, result.stdout + result.stderr
    assert stack.head("telemetry") == new_telemetry
    assert stack.head("cockpit") == new_cockpit
    # install.sh ran once, while the cockpit was still at its old commit.
    assert stack.calls() == [f"install cockpit={old_cockpit}"]
    assert "Updated." in result.stdout
    assert "orrery-telemetry: 2099.01.01 (API 2)" in result.stdout
    assert f"cockpit:          {new_cockpit[:7]}" in result.stdout
    assert "./scripts/start-cockpit.sh again" in result.stdout


def test_positive_already_current_runs_install_and_changes_no_commit(stack, dashboard):
    before = (stack.head("telemetry"), stack.head("cockpit"))
    result = stack.update(ORRERY_DASHBOARD_URL=dashboard)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (stack.head("telemetry"), stack.head("cockpit")) == before
    assert "orrery-telemetry is up to date" in result.stdout and "cockpit is up to date" in result.stdout
    assert len(stack.calls()) == 1  # install.sh still runs: it is how the payload is refreshed


def test_positive_the_codex_plugin_is_refreshed_only_when_its_integration_is_installed(stack, dashboard):
    assert stack.update(ORRERY_DASHBOARD_URL=dashboard).returncode == 0
    assert not [c for c in stack.calls() if c.startswith("plugin")]
    stack.install_codex_plugin()
    stack.log.unlink()
    assert stack.update(ORRERY_DASHBOARD_URL=dashboard).returncode == 0
    plugin = [c for c in stack.calls() if c.startswith("plugin")]
    assert plugin == [f"plugin --refresh-plugin-only --install-dir {stack.agentstack}/integrations/codex_app"]
    assert stack.calls()[0].startswith("install")  # after install.sh


def test_positive_dry_run_changes_nothing(stack):
    stack.publish("telemetry")
    stack.publish("cockpit")
    stack.install_codex_plugin()
    before = [(stack.head(n), stack.tracking(n)) for n in ("telemetry", "cockpit")]
    result = stack.update("--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    assert [(stack.head(n), stack.tracking(n)) for n in ("telemetry", "cockpit")] == before  # not even fetched
    assert stack.calls() == []
    assert "orrery-telemetry has new commits on its remote" in result.stdout
    assert "cockpit has new commits on its remote" in result.stdout
    for step in ("pull --ff-only", "./scripts/install.sh", "--refresh-plugin-only"):
        assert step in result.stdout
    assert "Dry run finished: nothing was changed." in result.stdout
    # It says what it did not check (VioletBohr P3-2).
    assert "whether they" in result.stdout and "checked only by the real run" in result.stdout


def test_positive_help(stack):
    result = stack.update("--help")
    assert result.returncode == 0 and "Usage: scripts/update.sh" in result.stdout


SAVED = ("export AGENTSTACK_PORT='19876'\n"
         "export AGENTSTACK_LABEL_PREFIX='org.review.custom'\n"
         "export AGENTSTACK_TERMINAL='none'\n"
         "export AGENTSTACK_MCP_URL='http://127.0.0.1:19877/mcp'\n")


def test_positive_install_gets_the_saved_settings_from_env_sh(stack, dashboard):
    """VioletBohr P2-1: install.sh takes the port, label prefix, terminal and
    Mail URL only from its environment, so a fresh terminal reinstalled with
    the defaults (8770, org.agentstack, auto, 18765)."""
    (stack.agentstack / "env.sh").write_text(SAVED)
    assert stack.update(ORRERY_DASHBOARD_URL=dashboard).returncode == 0
    assert stack.install_env() == ("port=19876 label=org.review.custom terminal=none "
                                   "mcp=http://127.0.0.1:19877/mcp")


def test_positive_a_value_set_in_this_environment_wins_over_env_sh(stack, dashboard):
    (stack.agentstack / "env.sh").write_text(SAVED)
    assert stack.update(ORRERY_DASHBOARD_URL=dashboard, AGENTSTACK_PORT="20000").returncode == 0
    assert stack.install_env().startswith("port=20000 label=org.review.custom ")


def test_negative_without_env_sh_nothing_is_invented(stack, dashboard):
    assert stack.update(ORRERY_DASHBOARD_URL=dashboard).returncode == 0
    assert stack.install_env() == "port= label= terminal= mcp="  # install.sh applies its own defaults


@pytest.mark.parametrize("state", [None, {"tool": "agentstack-codex-app", "plugin": {"enabled": False}},
                                   {"tool": "something-else", "plugin": {"enabled": True}}, "not json"])
def test_negative_the_core_proxy_folder_alone_is_not_the_codex_plugin(stack, dashboard, state):
    """VioletBohr P2-2: the core installer puts the child MCP proxy in the same
    folder, so everyone had it and the refresh failed without a Codex plugin."""
    folder = stack.agentstack / "integrations" / "codex_app"
    (folder / "plugin" / "scripts").mkdir(parents=True)  # what the core install leaves
    if state is not None:
        (folder / "install-state.json").write_text(state if isinstance(state, str) else json.dumps(state))
    result = stack.update(ORRERY_DASHBOARD_URL=dashboard)
    assert result.returncode == 0, result.stdout
    assert not [c for c in stack.calls() if c.startswith("plugin")]
    assert "refresh-plugin-only" not in result.stdout


def test_positive_an_untracked_file_the_update_does_not_touch_is_fine(stack, dashboard):
    new_cockpit = stack.publish("cockpit")
    (stack.cockpit / "notes.txt").write_text("mine\n")
    assert stack.update(ORRERY_DASHBOARD_URL=dashboard).returncode == 0
    assert stack.head("cockpit") == new_cockpit and (stack.cockpit / "notes.txt").read_text() == "mine\n"


def test_positive_telemetry_in_a_linked_worktree(stack, dashboard):
    """VioletBohr P2-4: a linked worktree's .git is a file, and was refused."""
    new_telemetry = stack.publish("telemetry")
    worktree = stack.tmp / "telemetry-wt"
    git(stack.telemetry, "worktree", "add", "-q", "-b", "wt", str(worktree), "master")
    git(worktree, "branch", "-q", "--set-upstream-to=origin/master")
    assert (worktree / ".git").is_file()
    (stack.agentstack / "install-state.json").write_text(json.dumps({"repo_root": str(worktree)}))
    result = stack.update(ORRERY_DASHBOARD_URL=dashboard)
    assert result.returncode == 0, result.stdout
    assert git(worktree, "rev-parse", "HEAD") == new_telemetry


# ---------------------------------------------------------------- negative
# Each case must say why in the output, and leave both checkouts as they were.

def unchanged(stack, before):
    assert [stack.head(n) for n in ("telemetry", "cockpit")] == before
    assert stack.calls() == []


def test_negative_no_install_record(stack):
    (stack.agentstack / "install-state.json").unlink()
    result = stack.update()
    assert result.returncode == 1
    assert "orrery-telemetry is not installed" in result.stdout and "install-state.json" in result.stdout
    assert "docs/install.md, step 0" in result.stdout


def test_negative_install_record_without_repo_root(stack):
    (stack.agentstack / "install-state.json").write_text("{}")
    result = stack.update()
    assert result.returncode == 1 and "does not say where orrery-telemetry was installed from" in result.stdout


@pytest.mark.parametrize("name", ["telemetry", "cockpit"])
def test_negative_uncommitted_changes_stop_everything(stack, name):
    stack.publish("telemetry")
    stack.publish("cockpit")
    before = [stack.head(n) for n in ("telemetry", "cockpit")]
    (getattr(stack, name) / "VERSION").write_text("edited\n")
    result = stack.update()
    assert result.returncode == 1
    label = "orrery-telemetry" if name == "telemetry" else "cockpit"
    assert f"NG    {label} has uncommitted changes; nothing was updated." in result.stdout
    assert " M VERSION" in result.stdout
    unchanged(stack, before)


@pytest.mark.parametrize("name", ["telemetry", "cockpit"])
def test_negative_a_checkout_that_cannot_fast_forward(stack, name):
    stack.publish("telemetry")
    stack.publish("cockpit")
    checkout = getattr(stack, name)
    (checkout / "local.txt").write_text("mine\n")
    git(checkout, "add", "local.txt")
    git(checkout, "commit", "-q", "-m", "local work")
    before = [stack.head(n) for n in ("telemetry", "cockpit")]
    result = stack.update()
    assert result.returncode == 1
    assert "cannot be fast-forwarded; nothing was updated." in result.stdout
    unchanged(stack, before)


@pytest.mark.parametrize("name", ["telemetry", "cockpit"])
def test_negative_an_untracked_file_the_update_would_overwrite(stack, name):
    """VioletBohr P2-3: this stopped the cockpit's pull only after
    orrery-telemetry had been pulled and installed."""
    seed = stack.tmp / f"{name}-seed"
    (seed / "local.txt").write_text("theirs\n")
    git(seed, "add", "local.txt")
    git(seed, "commit", "-q", "-m", "adds local.txt")
    git(seed, "push", "-q", "origin", "HEAD:master")
    stack.publish("telemetry" if name == "cockpit" else "cockpit")
    (getattr(stack, name) / "local.txt").write_text("mine\n")
    before = [stack.head(n) for n in ("telemetry", "cockpit")]
    result = stack.update()
    assert result.returncode == 1
    label = "orrery-telemetry" if name == "telemetry" else "cockpit"
    assert f"NG    {label} has untracked files that the update would overwrite; nothing was updated." in result.stdout
    assert "          local.txt" in result.stdout
    unchanged(stack, before)
    assert (getattr(stack, name) / "local.txt").read_text() == "mine\n"


def add_incoming(stack, name: str, rel: str) -> None:
    seed = stack.tmp / f"{name}-seed"
    path = seed / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("theirs\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "adds a file")
    git(seed, "push", "-q", "origin", "HEAD:master")


def add_local(checkout: Path, rel: str) -> None:
    path = checkout / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("mine\n")


# (incoming tracked path, local untracked path, reported path)
BLOCKING = [
    ("日本語 メモ.md", "日本語 メモ.md", "日本語 メモ.md"),        # VioletBohr R1: quoted by git diff
    ("with space.txt", "with space.txt", "with space.txt"),
    ("new\nline.txt", "new\nline.txt", None),                    # reported, shown over two lines
    ("newfolder/note.md", "newfolder", "newfolder"),              # VioletBohr R2: a file where its folder goes
    ("メモ/深い/note.md", "メモ", "メモ"),
    ("incoming", "incoming/mine.txt", "incoming/mine.txt"),       # a folder where the file goes
]


@pytest.mark.parametrize("incoming, local, shown", BLOCKING)
@pytest.mark.parametrize("name", ["telemetry", "cockpit"])
def test_negative_untracked_files_in_the_way_by_any_name(stack, name, incoming, local, shown):
    add_incoming(stack, name, incoming)
    stack.publish("telemetry" if name == "cockpit" else "cockpit")
    add_local(getattr(stack, name), local)
    before = [stack.head(n) for n in ("telemetry", "cockpit")]
    result = stack.update()
    assert result.returncode == 1, result.stdout
    assert "has untracked files that the update would overwrite; nothing was updated." in result.stdout
    if shown:
        assert f"          {shown}\n" in result.stdout
    unchanged(stack, before)
    assert (getattr(stack, name) / local).read_text() == "mine\n"


# Untracked files that only look alike: the update goes ahead.
NOT_BLOCKING = [
    ("日本語 メモ.md", "日本語 その他.md"),
    ("newfolder/note.md", "newfolder/mine.txt"),   # an untracked file beside it, in a real folder
    ("newfolder/note.md", "newfolder2"),
    ("incoming", "incomingX/mine.txt"),
]


@pytest.mark.parametrize("incoming, local", NOT_BLOCKING)
def test_positive_untracked_files_that_are_not_in_the_way(stack, dashboard, incoming, local):
    add_incoming(stack, "cockpit", incoming)
    new_cockpit = git(stack.tmp / "cockpit-seed", "rev-parse", "HEAD")
    add_local(stack.cockpit, local)
    result = stack.update(ORRERY_DASHBOARD_URL=dashboard)
    assert result.returncode == 0, result.stdout
    assert stack.head("cockpit") == new_cockpit
    assert (stack.cockpit / local).read_text() == "mine\n"
    assert (stack.cockpit / incoming).read_text() == "theirs\n"


def test_negative_install_record_pointing_at_a_folder_that_is_not_a_checkout(stack):
    plain = stack.tmp / "plain"
    (plain / "scripts").mkdir(parents=True)
    (plain / "scripts" / "install.sh").write_text("#!/bin/sh\n")
    (plain / "scripts" / "install.sh").chmod(0o755)
    (stack.agentstack / "install-state.json").write_text(json.dumps({"repo_root": str(plain)}))
    result = stack.update()
    assert result.returncode == 1 and "is no longer an orrery-telemetry checkout" in result.stdout


def test_negative_install_failure_leaves_the_cockpit_alone(stack):
    new_telemetry = stack.publish("telemetry")
    stack.publish("cockpit")
    old_cockpit = stack.head("cockpit")
    result = stack.update(FAKE_INSTALL_FAIL="1")
    assert result.returncode == 1
    assert "install.sh failed (see its output above); the cockpit was not updated." in result.stdout
    assert stack.head("telemetry") == new_telemetry  # pulled, then its installer failed
    assert stack.head("cockpit") == old_cockpit
    assert "Updated." not in result.stdout


@pytest.mark.parametrize("dry", [False, True])
def test_negative_an_unreachable_remote_is_named(stack, dry):
    git(stack.telemetry, "remote", "set-url", "origin", str(stack.tmp / "gone.git"))
    before = [stack.head(n) for n in ("telemetry", "cockpit")]
    result = stack.update(*(["--dry-run"] if dry else []))
    assert result.returncode == 1
    assert "could not reach the remote of orrery-telemetry" in result.stdout
    assert "Check the network connection" in result.stdout
    unchanged(stack, before)


def test_negative_a_branch_with_nothing_to_pull_from(stack):
    git(stack.cockpit, "switch", "-q", "-c", "local-only")
    result = stack.update()
    assert result.returncode == 1 and "cockpit" in result.stdout and "nothing to pull from" in result.stdout
    assert stack.calls() == []


def test_negative_unknown_option(stack):
    result = stack.update("--yes")
    assert result.returncode == 2 and "Unknown option: --yes" in result.stderr


# ---------------------------------------------------------------- saved is not explicit
# install.sh reads most saved settings back from env.sh itself (its
# resolve_setting lines) and treats a value in its environment as chosen on
# purpose. Exporting env.sh's copy made a saved, since-broken Codex path look
# explicit, and install.sh refused it instead of looking for codex again
# (MacBook Air, 2026-10-02). update.sh now leaves those to install.sh.
FAKE_INSTALL_RESOLVING = """#!/bin/sh
resolve_setting() { :; }
resolve_setting PORT AGENTSTACK_PORT 8770
resolve_setting CODEX_BIN_SETTING AGENTSTACK_CODEX_BIN "" found
printf 'install cockpit=%s\\n' "$(git -C "$FAKE_COCKPIT" rev-parse HEAD)" >> "$FAKE_LOG"
printf 'codex=%s port=%s maildb=%s\\n' "${AGENTSTACK_CODEX_BIN-unset}" "${AGENTSTACK_PORT-unset}" \\
  "${AGENTSTACK_MAIL_DB-unset}" > "$FAKE_LOG.env"
"""
SAVED_WITH_CODEX = ("export AGENTSTACK_CODEX_BIN='/broken/codex'\n"
                    "export AGENTSTACK_PORT='19876'\n"
                    "export AGENTSTACK_MAIL_DB='/saved/storage.sqlite3'\n")


def use_resolving_installer(stack):
    seed = stack.tmp / "telemetry-seed"
    (seed / "scripts" / "install.sh").write_text(FAKE_INSTALL_RESOLVING)
    git(seed, "commit", "-q", "-am", "an installer that resolves saved settings itself")
    git(seed, "push", "-q", "origin", "HEAD:master")
    (stack.agentstack / "env.sh").write_text(SAVED_WITH_CODEX)


def test_positive_settings_install_sh_reads_itself_are_not_passed_as_chosen(stack, dashboard):
    use_resolving_installer(stack)
    assert stack.update(ORRERY_DASHBOARD_URL=dashboard).returncode == 0
    # codex and port come from env.sh inside install.sh (saved, not chosen);
    # the Mail database, which install.sh does not read back, is still passed.
    assert stack.install_env() == "codex=unset port=unset maildb=/saved/storage.sqlite3"


def test_positive_a_value_set_in_this_environment_is_still_passed(stack, dashboard):
    use_resolving_installer(stack)
    assert stack.update(ORRERY_DASHBOARD_URL=dashboard, AGENTSTACK_CODEX_BIN="/chosen/codex").returncode == 0
    assert stack.install_env() == "codex=/chosen/codex port=unset maildb=/saved/storage.sqlite3"


# ---------------------------------------------------------------- --mail
# update.sh passes the ORRERY Mail choice to install.sh explicitly every run
# (keep by default), in the form that install.sh understands.
FAKE_INSTALL_MAIL = """#!/bin/sh
# usage: --update-mail
printf 'install cockpit=%s\\n' "$(git -C "$FAKE_COCKPIT" rev-parse HEAD)" >> "$FAKE_LOG"
printf 'args=%s env=%s\\n' "$*" "${AGENTSTACK_MAIL_UPDATE-unset}" > "$FAKE_LOG.env"
"""


def use_mail_installer(stack, new: bool):
    seed = stack.tmp / "telemetry-seed"
    text = FAKE_INSTALL_MAIL
    if new:  # update.sh reads the option from the installer's own text
        text = text.replace("# usage: --update-mail", "# usage: --mail auto|update|keep, --update-mail")
    (seed / "scripts" / "install.sh").write_text(text)
    git(seed, "commit", "-q", "-am", "an installer with Mail options")
    git(seed, "push", "-q", "origin", "HEAD:master")


def test_positive_help_lists_the_mail_choice(stack):
    out = stack.update("--help")
    assert out.returncode == 0 and "--mail auto|update|keep" in out.stdout


@pytest.mark.parametrize("args,new,expected", [
    ((), True, "args=--mail keep env=unset"),
    (("--mail", "update"), True, "args=--mail update env=unset"),
    (("--mail=auto",), True, "args=--mail auto env=unset"),
    (("--mail", "keep"), True, "args=--mail keep env=unset"),
    ((), False, "args= env=keep"),
    (("--mail", "update"), False, "args=--update-mail env=unset"),
    (("--mail", "auto"), False, "args= env=auto"),
])
def test_positive_the_mail_choice_reaches_install_sh(stack, dashboard, args, new, expected):
    use_mail_installer(stack, new)
    assert stack.update(*args, ORRERY_DASHBOARD_URL=dashboard).returncode == 0
    assert stack.install_env() == expected


def test_negative_an_unknown_mail_choice(stack):
    out = stack.update("--mail", "sometimes")
    assert out.returncode == 2 and "auto|update|keep" in out.stderr


def test_positive_values_the_login_shell_echoes_from_env_sh_stay_saved(stack, dashboard):
    """MacBook Air, 2026-10-02: ~/.zshenv sources ~/.agentstack/env.sh, so every
    saved value is also in update.sh's environment. A value equal to the saved
    one is an echo of env.sh, not a choice; install.sh reads it as saved (and
    looks for codex again when the saved path no longer runs)."""
    use_resolving_installer(stack)
    assert stack.update(ORRERY_DASHBOARD_URL=dashboard, AGENTSTACK_CODEX_BIN="/broken/codex",
                        AGENTSTACK_PORT="19876", AGENTSTACK_MAIL_DB="/saved/storage.sqlite3").returncode == 0
    assert stack.install_env() == "codex=unset port=unset maildb=/saved/storage.sqlite3"


# ---------------------------------------------------------------- rewritten cockpit history
# No installed stack is involved: every force-push targets a temporary bare repo.
ISSUE_20 = "https://github.com/gyroid-eth/orrery/issues/20"


def rewrite_cockpit(stack):
    seed = stack.tmp / "cockpit-seed"
    old_tree = git(seed, "rev-parse", "HEAD^{tree}")
    git(seed, "commit", "-q", "--amend", "-m", "rewritten metadata")
    git(seed, "push", "-q", "--force", "origin", "HEAD:master")
    assert git(seed, "rev-parse", "HEAD^{tree}") == old_tree
    return git(seed, "rev-parse", "HEAD")


def checkout_contents(checkout):
    """Working files, staged contents and HEAD; fetch may update remote refs."""
    files = {str(p.relative_to(checkout)): p.read_bytes()
             for p in checkout.rglob("*") if p.is_file() and ".git" not in p.relative_to(checkout).parts}
    return (git(checkout, "rev-parse", "HEAD"), git(checkout, "ls-files", "--stage"),
            git(checkout, "status", "--porcelain", "--untracked-files=all"), files)


def recovery_commands(output):
    return [shlex.split(line.strip()) for line in output.splitlines()
            if line.strip().startswith("git -C ") and
            (" fetch origin master" in line or " reset --hard origin/master" in line)]


def test_rewritten_cockpit_gives_manual_commands_without_changing_checkouts(stack):
    stack.publish("telemetry")  # Must not install this before diagnosing cockpit.
    # Reproduce a user who already updated to the now-rewritten release.
    stack.publish("cockpit")
    git(stack.cockpit, "pull", "-q", "--ff-only")
    new_remote = rewrite_cockpit(stack)
    before = [checkout_contents(getattr(stack, n)) for n in ("telemetry", "cockpit")]
    result = stack.update()
    assert result.returncode == 1, result.stdout + result.stderr
    assert ISSUE_20 in result.stdout and "may have been rewritten" in result.stdout
    assert "or this checkout has local commits" in result.stdout
    assert "reset --hard discards local commits and changes" in result.stdout
    assert recovery_commands(result.stdout) == [
        ["git", "-C", str(stack.cockpit), "fetch", "origin", "master"],
        ["git", "-C", str(stack.cockpit), "reset", "--hard", "origin/master"],
    ]
    assert [checkout_contents(getattr(stack, n)) for n in ("telemetry", "cockpit")] == before
    assert stack.tracking("cockpit") == new_remote  # Normal preflight fetch only.
    assert stack.calls() == []


@pytest.mark.parametrize("dirty", ["tracked", "staged", "untracked"])
def test_rewritten_dirty_cockpit_preserves_work_and_asks_for_backup(stack, dirty):
    rewrite_cockpit(stack)
    path = stack.cockpit / ("notes.txt" if dirty == "untracked" else "VERSION")
    path.write_text("unsaved work\n")
    if dirty == "staged":
        git(stack.cockpit, "add", "VERSION")
    before = [checkout_contents(getattr(stack, n)) for n in ("telemetry", "cockpit")]
    result = stack.update()
    assert result.returncode == 1, result.stdout
    assert "back up or commit" in result.stdout.lower()
    assert "Do not reset unsaved work" in result.stdout
    assert recovery_commands(result.stdout) == []
    assert [checkout_contents(getattr(stack, n)) for n in ("telemetry", "cockpit")] == before
    assert stack.calls() == []


def test_rewritten_cockpit_dry_run_does_not_even_fetch(stack):
    rewrite_cockpit(stack)
    before = [checkout_contents(getattr(stack, n)) for n in ("telemetry", "cockpit")]
    refs = [stack.tracking(n) for n in ("telemetry", "cockpit")]
    result = stack.update("--dry-run")
    assert result.returncode == 0, result.stdout
    assert ISSUE_20 not in result.stdout and recovery_commands(result.stdout) == []
    assert "checked only by the real run" in result.stdout
    assert [stack.tracking(n) for n in ("telemetry", "cockpit")] == refs
    assert [checkout_contents(getattr(stack, n)) for n in ("telemetry", "cockpit")] == before
    assert stack.calls() == []


@pytest.mark.parametrize("dry", [False, True])
def test_cockpit_network_failure_is_not_reported_as_history_rewrite(stack, dry):
    git(stack.cockpit, "remote", "set-url", "origin", str(stack.tmp / "gone.git"))
    before = [stack.head(n) for n in ("telemetry", "cockpit")]
    result = stack.update(*(["--dry-run"] if dry else []))
    assert result.returncode == 1
    assert "could not reach the remote of cockpit" in result.stdout
    assert ISSUE_20 not in result.stdout and recovery_commands(result.stdout) == []
    unchanged(stack, before)


def test_local_commits_only_are_not_reported_as_history_rewrite(stack):
    add_local(stack.cockpit, "local.txt")
    git(stack.cockpit, "add", "local.txt")
    git(stack.cockpit, "commit", "-q", "-m", "local work")
    before = checkout_contents(stack.cockpit)
    result = stack.update()
    assert result.returncode == 1
    assert "cannot be fast-forwarded" in result.stdout
    assert ISSUE_20 not in result.stdout and recovery_commands(result.stdout) == []
    assert checkout_contents(stack.cockpit) == before and stack.calls() == []


@pytest.mark.parametrize("branch", ["feature", "other-upstream"])
def test_rewritten_other_branch_does_not_offer_a_master_reset(stack, branch):
    if branch == "feature":
        git(stack.cockpit, "switch", "-q", "-c", "feature")
        git(stack.cockpit, "branch", "--set-upstream-to=origin/master")
    else:
        git(stack.tmp / "cockpit-seed", "push", "-q", "origin", "HEAD:other")
        git(stack.cockpit, "fetch", "-q", "origin")
        git(stack.cockpit, "branch", "--set-upstream-to=origin/other")
        git(stack.tmp / "cockpit-seed", "commit", "-q", "--amend", "-m", "rewritten other")
        git(stack.tmp / "cockpit-seed", "push", "-q", "--force", "origin", "HEAD:other")
    if branch == "feature":
        rewrite_cockpit(stack)
    before = checkout_contents(stack.cockpit)
    result = stack.update()
    assert result.returncode == 1
    assert ISSUE_20 not in result.stdout and recovery_commands(result.stdout) == []
    assert checkout_contents(stack.cockpit) == before and stack.calls() == []


def test_recovery_commands_quote_the_actual_checkout_path(stack):
    renamed = stack.tmp / "cockpit space'$(example)"
    stack.cockpit.rename(renamed)
    stack.cockpit = renamed
    rewrite_cockpit(stack)
    result = stack.update()
    assert result.returncode == 1
    assert recovery_commands(result.stdout) == [
        ["git", "-C", str(renamed), "fetch", "origin", "master"],
        ["git", "-C", str(renamed), "reset", "--hard", "origin/master"],
    ]
    assert stack.calls() == []


@pytest.mark.parametrize("failure", ["rewrite", "network", "dirty"])
def test_cockpit_pull_failure_after_preflight_is_classified_without_reset(stack, failure):
    # The fake installer changes remote state after preflight, before cockpit pull.
    seed = stack.tmp / "telemetry-seed"
    hook = {
        "rewrite": 'git -C "$FAKE_SEED" commit -q --amend -m "rewritten metadata"\n'
                   'git -C "$FAKE_SEED" push -q --force origin HEAD:master\n',
        "network": 'git -C "$FAKE_COCKPIT" remote set-url origin "$FAKE_GONE"\n',
        "dirty": 'git -C "$FAKE_SEED" commit -q --amend -m "rewritten metadata"\n'
                 'git -C "$FAKE_SEED" push -q --force origin HEAD:master\n'
                 'printf "unsaved work\\n" > "$FAKE_COCKPIT/VERSION"\n',
    }[failure]
    (seed / "scripts/install.sh").write_text(FAKE_INSTALL + hook)
    git(seed, "commit", "-q", "-am", "installer test hook")
    git(seed, "push", "-q", "origin", "HEAD:master")
    old_cockpit = checkout_contents(stack.cockpit)
    result = stack.update(FAKE_SEED=str(stack.tmp / "cockpit-seed"),
                          FAKE_GONE=str(stack.tmp / "gone.git"))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "git pull of the cockpit failed" in result.stdout
    assert "orrery-telemetry was updated" in result.stdout
    assert len(stack.calls()) == 1  # Installation already happened; say so accurately.
    assert stack.head("cockpit") == old_cockpit[0]
    if failure == "rewrite":
        assert ISSUE_20 in result.stdout and len(recovery_commands(result.stdout)) == 2
        assert checkout_contents(stack.cockpit) == old_cockpit
    else:
        assert recovery_commands(result.stdout) == [] and ISSUE_20 not in result.stdout
        if failure == "dirty":
            assert "Do not reset unsaved work" in result.stdout
            assert (stack.cockpit / "VERSION").read_text() == "unsaved work\n"
        else:
            assert checkout_contents(stack.cockpit) == old_cockpit


@pytest.mark.parametrize("name", ["telemetry", "cockpit"])
@pytest.mark.parametrize("failure", ["rewrite", "local-ahead", "no-upstream"])
def test_all_displayed_git_advice_preserves_literal_shell_arguments(stack, name, failure):
    # Exercise Bash itself: shlex parsing alone cannot detect command substitution
    # inside double quotes or Bash's ANSI-C quoting for a newline in the path.
    renamed = stack.tmp / (name + " space'\"$(example)`example`\\newline\nend")
    getattr(stack, name).rename(renamed)
    setattr(stack, name, renamed)
    stack.env["FAKE_COCKPIT"] = str(stack.cockpit)
    (stack.agentstack / "install-state.json").write_text(json.dumps({"repo_root": str(stack.telemetry)}))
    if failure == "rewrite":
        seed = stack.tmp / f"{name}-seed"
        git(seed, "commit", "-q", "--amend", "-m", "rewritten metadata")
        git(seed, "push", "-q", "--force", "origin", "HEAD:master")
    elif failure == "local-ahead":
        add_local(renamed, "local.txt")
        git(renamed, "add", "local.txt")
        git(renamed, "commit", "-q", "-m", "local work")
    else:
        git(renamed, "switch", "-q", "-c", "local-only")
    before = [checkout_contents(getattr(stack, n)) for n in ("telemetry", "cockpit")]
    result = stack.update()
    assert result.returncode == 1
    commands = []
    for line in result.stdout.splitlines():
        if "Look at them with: " in line:
            commands.append(line.split("Look at them with: ", 1)[1])
        elif line.strip().startswith("git -C "):
            commands.append(line.strip())
    expected = [["-C", str(renamed), "switch", "master"]] if failure == "no-upstream" else [
        ["-C", str(renamed), "log", "@{u}..HEAD"]]
    if failure == "rewrite" and name == "cockpit":
        expected = [["-C", str(renamed), "fetch", "origin", "master"],
                    ["-C", str(renamed), "reset", "--hard", "origin/master"]] + expected
    assert len(commands) == len(expected)
    marker = stack.tmp / "substitution-marker"
    # Stub git to record argv only: especially, never execute the displayed reset.
    prelude = 'example() { printf evaluated > "$SUBSTITUTION_MARKER"; }; '
    prelude += "git() { printf '%s\\0' \"$@\"; }; "
    for command, argv in zip(commands, expected):
        probe = subprocess.run([BASH, "-c", prelude + command], capture_output=True,
                               env={**stack.env, "SUBSTITUTION_MARKER": str(marker)}, check=True)
        assert not marker.exists(), command
        assert probe.stdout.decode().split("\0")[:-1] == argv
    assert [checkout_contents(getattr(stack, n)) for n in ("telemetry", "cockpit")] == before
    assert stack.calls() == []
