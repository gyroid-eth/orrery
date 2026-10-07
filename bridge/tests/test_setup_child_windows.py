"""Cockpit defaults cross the real Telemetry setting resolver, offline.

The saved default and a deliberately selected value must survive the same
merge used by setup and update. No services or installed HOME are used.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from test_update_sh import Stack, dashboard, git  # noqa: F401 (isolated dashboard fixture)

ROOT = Path(__file__).resolve().parents[2]
RESOLVER = Path(__file__).with_name("fixtures") / "telemetry_settings_resolution.sh"
BASH = "/bin/bash"


def policy(script: str) -> str:
    text = (ROOT / "scripts" / script).read_text()
    return text.split("# >>> child-window-setting", 1)[1].split("# <<< child-window-setting", 1)[0]


def installer(tmp: Path) -> Path:
    checkout = tmp / "telemetry"
    (checkout / "scripts").mkdir(parents=True)
    text = """#!/bin/bash
set -eu
INSTALL_DIR="$AGENTSTACK_HOME"
OPTION_GIVEN=""
RESET_SETTINGS="${AGENTSTACK_RESET_SETTINGS:-0}"
AUTO_OPEN_CHILD_SETTING="${AGENTSTACK_AUTO_OPEN_CHILD:-}"
# The real resolver calls an installed-env reader. Only synthetic export
# files are used here; this reader isolates absent values from inherited env.
agentstack_installed_env_value() (
  unset "$1"
  if [ -r "$2" ]; then . "$2"; fi
  eval "printf '%s' \\\"\\${$1:-}\\\""
)
""" + RESOLVER.read_text() + """
resolve_setting AUTO_OPEN_CHILD_SETTING AGENTSTACK_AUTO_OPEN_CHILD 1
case "$AUTO_OPEN_CHILD_SETTING" in 0|1) ;; *) exit 2 ;; esac
printf '%s|%s\\n' "$AUTO_OPEN_CHILD_SETTING" "$CHOSEN_SETTINGS" > "$HOME/result"
printf 'export AGENTSTACK_AUTO_OPEN_CHILD=%s\\nexport AGENTSTACK_CHOSEN_SETTINGS="%s"\\n' \\
 "$AUTO_OPEN_CHILD_SETTING" "$CHOSEN_SETTINGS" > "$INSTALL_DIR/env.sh"
"""
    path = checkout / "scripts" / "install.sh"
    path.write_text(text)
    path.chmod(0o755)
    return checkout


def run(tmp: Path, script: str, shell: str | None = None, reset: str = "0"):
    home = tmp / "home"
    home.mkdir(exist_ok=True)
    install = home / ".agentstack"
    install.mkdir(exist_ok=True)
    tel = installer(tmp)
    text = (ROOT / "scripts" / script).read_text()
    name = "run_installer" if script == "setup.sh" else "telemetry_install"
    function = text.split(name + "() {", 1)[1].split("\n}\n", 1)[0]
    command = policy(script) + f"\n{name}() {{" + function + "\n}\n" + "\n".join([
        f"ENV_FILE={shlex.quote(str(install / 'env.sh'))}",
        f"tel_root={shlex.quote(str(tel))}",
        f"telemetry_root={shlex.quote(str(tel))}",
        'AGENTSTACK_DIR="$AGENTSTACK_HOME"',
        "assume_flag=''", "project_key=$HOME/work", "mail_mode=keep",
        'export AGENTSTACK_AUTO_OPEN_CHILD="$(child_window_setting "$ENV_FILE")"',
        name,
    ])
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "AGENTSTACK_HOME": str(install),
           "AGENTSTACK_RESET_SETTINGS": reset}
    if shell is not None:
        env["AGENTSTACK_AUTO_OPEN_CHILD"] = shell
    return subprocess.run([BASH, "-c", command], env=env, capture_output=True, text=True, timeout=10)


def saved(tmp: Path, value: str | None, chosen: str | None):
    directory = tmp / "home" / ".agentstack"
    directory.mkdir(parents=True)
    lines = []
    if value is not None:
        lines.append(f"export AGENTSTACK_AUTO_OPEN_CHILD={shlex.quote(value)}")
    if chosen is not None:
        lines.append(f"export AGENTSTACK_CHOSEN_SETTINGS={shlex.quote(chosen)}")
    if lines:
        (directory / "env.sh").write_text("\n".join(lines) + "\n")


CHOICE = "AGENTSTACK_AUTO_OPEN_CHILD"
CASES = [
    (None, None, None, "0"),  # new install
    (None, None, "1", "1"),
    (None, None, "0", "0"),
    (None, None, "", "0"),  # clear to the cockpit default
    ("1", "", None, "0"),  # recorded default
    ("1", "AGENTSTACK_TERMINAL", None, "0"),
    ("1", "", "1", "0"),  # login shell echo is not a new choice
    ("1", CHOICE, None, "1"),
    ("1", CHOICE, "1", "1"),
    ("1", CHOICE, "0", "0"),
    ("0", CHOICE, None, "0"),
    ("0", CHOICE, "1", "1"),
    ("1", None, None, "1"),  # ambiguous pre-record legacy value
    ("0", None, None, "0"),
    ("1", None, "0", "0"),
]


@pytest.mark.parametrize("script", ["setup.sh", "update.sh"])
@pytest.mark.parametrize("value,chosen,shell,expected", CASES)
def test_effective_setting_and_saved_choice(tmp_path, script, value, chosen, shell, expected):
    saved(tmp_path, value, chosen)
    result = run(tmp_path, script, shell)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not result.stderr
    effect, record = (tmp_path / "home" / "result").read_text().strip().split("|", 1)
    assert effect == expected
    assert CHOICE in record.split()


def test_same_policy_in_temporary_setup_and_update():
    assert policy("setup.sh") == policy("update.sh")


@pytest.mark.parametrize("script", ["setup.sh", "update.sh"])
def test_legacy_one_remains_selected_through_three_updates(tmp_path, script):
    saved(tmp_path, "1", None)
    for _ in range(3):
        result = run(tmp_path, script)
        assert result.returncode == 0, result.stdout + result.stderr
        assert not result.stderr
        assert (tmp_path / "home" / "result").read_text().strip() == "1|" + CHOICE
        shutil.rmtree(tmp_path / "telemetry")


def test_explicit_zero_twice_recovers_manually_edited_unselected_zero(tmp_path):
    saved(tmp_path, "0", "")
    tel = installer(tmp_path)
    home = tmp_path / "home"
    env = {"HOME": str(home), "PATH": os.environ["PATH"],
           "AGENTSTACK_HOME": str(home / ".agentstack"), CHOICE: "0"}
    for expected in ("1|", "0|" + CHOICE):
        result = subprocess.run([BASH, str(tel / "scripts" / "install.sh")],
                                env=env, capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stdout + result.stderr
        assert (home / "result").read_text().strip() == expected
    shutil.rmtree(tel)
    assert run(tmp_path, "update.sh").returncode == 0
    assert (home / "result").read_text().strip() == "0|" + CHOICE


@pytest.mark.parametrize("script", ["setup.sh", "update.sh"])
def test_invalid_explicit_value_reaches_installer_validation(tmp_path, script):
    saved(tmp_path, "1", CHOICE)
    result = run(tmp_path, script, "invalid")
    assert result.returncode == 2


@pytest.mark.parametrize("script", ["setup.sh", "update.sh"])
def test_reset_drops_saved_choice_to_cockpit_default(tmp_path, script):
    saved(tmp_path, "1", CHOICE)
    result = run(tmp_path, script, reset="1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "home" / "result").read_text().startswith("0|")


@pytest.mark.parametrize("script", ["setup.sh", "update.sh"])
def test_opt_in_after_default_update_is_recorded_and_survives_next_update(tmp_path, script):
    saved(tmp_path, "1", "")
    assert run(tmp_path, script).returncode == 0
    home = tmp_path / "home"
    tel = tmp_path / "telemetry"
    result = subprocess.run([BASH, str(tel / "scripts" / "install.sh")],
                            env={"HOME": str(home), "PATH": os.environ["PATH"],
                                 "AGENTSTACK_HOME": str(home / ".agentstack"), CHOICE: "1"},
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert (home / "result").read_text().strip() == "1|" + CHOICE
    # A later update from a fresh shell keeps that explicit opt-in.
    (tel / "scripts" / "install.sh").unlink()
    (tel / "scripts").rmdir()
    tel.rmdir()
    assert run(tmp_path, script).returncode == 0
    assert (home / "result").read_text().strip() == "1|" + CHOICE


@pytest.mark.parametrize("value,chosen,shell,expected", [
    (None, None, None, "0"),
    (None, None, "1", "1"),
    ("1", "", None, "0"),
    ("1", CHOICE, None, "1"),
    ("1", None, None, "1"),
])
def test_complete_update_entry_uses_cockpit_policy(tmp_path, dashboard, value, chosen, shell, expected):
    stack = Stack(tmp_path)
    # Publish the upstream resolver fixture as the next Telemetry installer,
    # then let the real update command fetch it and run it in its usual order.
    generated = installer(tmp_path / "core") / "scripts" / "install.sh"
    seed = tmp_path / "telemetry-seed"
    (seed / "scripts" / "install.sh").write_text(generated.read_text())
    git(seed, "commit", "-q", "-am", "installer resolver")
    git(seed, "push", "-q", "origin", "HEAD:master")
    if value is not None:
        content = f"export {CHOICE}={shlex.quote(value)}\n"
        if chosen is not None:
            content += f"export AGENTSTACK_CHOSEN_SETTINGS={shlex.quote(chosen)}\n"
        (stack.agentstack / "env.sh").write_text(content)
    env = {"ORRERY_DASHBOARD_URL": dashboard}
    if shell is not None:
        env[CHOICE] = shell
    for _ in range(3 if value == "1" and chosen is None else 1):
        result = stack.update(**env)
        assert result.returncode == 0, result.stdout + result.stderr
        assert (stack.home / "result").read_text().split("|", 1)[0] == expected
