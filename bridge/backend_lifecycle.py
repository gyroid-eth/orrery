"""Inspect and stop the selected local cockpit process for a desktop restart."""
from __future__ import annotations

import argparse
from contextlib import closing
import ctypes
from datetime import datetime, timezone
import errno
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import subprocess
import sys
import tempfile
import time

from mobile_input import OSObserver

ROOT = Path(__file__).resolve().parents[1]
COMMIT = re.compile(r"[a-f0-9]{40}|[a-f0-9]{64}")
BOOT = re.compile(r"[0-9]{1,12}-([1-9][0-9]{0,8})")
# Closing a listener can precede process exit while cockpit work unwinds.
BACKEND_STOP_TIMEOUT = 30.0
STOP_TIMESTAMPS = ("term_sent_at", "process_exited_at", "port_cleared_at")


class LifecycleError(ValueError):
    pass


def _request(port: int, path: str, payload: dict | None = None) -> dict | None:
    try:
        with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=2)) as connection:
            if payload is None:
                connection.request("GET", path)
            else:
                connection.request("POST", path, json.dumps(payload), {"Content-Type": "application/json"})
            response = connection.getresponse()
            body = response.read(65537)
            health = json.loads(body) if response.status == 200 and len(body) <= 65536 else None
    except (OSError, ValueError, http.client.HTTPException):
        return None
    return health if isinstance(health, dict) else None


def read_health(port: int) -> dict | None:
    return _request(port, "/telemetry/health")


def installed_commit(root: Path) -> str:
    try:
        result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                capture_output=True, text=True, timeout=4, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    commit = result.stdout.strip()
    return commit if result.returncode == 0 and COMMIT.fullmatch(commit) else ""


def version_status(health: dict | None, root: Path, commit: str, runtime: dict) -> dict:
    if not health or health.get("backend") != "ok":
        return {"state": "unavailable"}
    running, boot, running_runtime = (health.get(key) for key in ("commit", "boot", "runtime"))
    if (health.get("root") != str(root) or running_runtime != runtime
            or not isinstance(running, str) or not COMMIT.fullmatch(running)
            or not isinstance(boot, str) or not BOOT.fullmatch(boot)
            or not COMMIT.fullmatch(commit)):
        return {"state": "unverified"}
    return {"state": "current" if running == commit else "stale",
            "boot": boot, "running_commit": running, "installed_commit": commit,
            "root": str(root), "runtime": running_runtime,
            "restart_guard": health.get("restart_guard") is True}


def checkout_ready(root: Path, commit: str) -> bool:
    try:
        index = subprocess.run(["git", "-C", str(root), "rev-parse", "--git-path", "index.lock"],
                               text=True, capture_output=True, check=True, timeout=4).stdout.strip()
        lock = root / index
        if not index or lock.exists():
            return False
        diff = subprocess.run(["git", "-C", str(root), "diff", "--no-ext-diff", "--quiet", commit, "--"],
                              timeout=6, check=False)
        return diff.returncode == 0 and not lock.exists() and installed_commit(root) == commit
    except (OSError, subprocess.SubprocessError):
        return False


def _state_dir() -> Path:
    default = Path.home() / ".local" / "state"
    return Path(os.environ.get("XDG_STATE_HOME") or default) / "orrery"


def _attempt_file(root: Path, runtime: dict, port: int, commit: str) -> Path:
    identity = json.dumps([str(root), runtime, port], sort_keys=True).encode()
    scope = hashlib.sha256(identity).hexdigest()[:24]
    return _state_dir() / "backend-update" / scope / commit


def _claim_attempt(attempt: Path) -> bool:
    attempt.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        fd = os.open(attempt, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    os.close(fd)
    return True


def _attempt_state(attempt: Path) -> dict:
    try:
        payload = json.loads(attempt.read_text())
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_attempt_state(attempt: Path, **fields) -> None:
    # A reader must always see the claim, including while the result is written.
    fd, filename = tempfile.mkstemp(prefix=".attempt-", dir=attempt.parent)
    temp = Path(filename)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump({**_attempt_state(attempt), **fields}, stream)
        temp.replace(attempt)
    finally:
        temp.unlink(missing_ok=True)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _log_restart(payload: dict, port: int, root: Path, runtime: dict) -> None:
    old_boot = payload.get("boot", "")
    old_sha = payload.get("running_commit", "")
    target = payload.get("installed_commit", "")
    if not all(isinstance(value, str) for value in (old_boot, old_sha, target)):
        raise LifecycleError("Invalid backend restart record.")
    if not BOOT.fullmatch(old_boot) or not COMMIT.fullmatch(old_sha) or not COMMIT.fullmatch(target):
        raise LifecycleError("Invalid backend restart record.")
    health = read_health(port)
    now = version_status(health, root, installed_commit(root), runtime)
    new_boot = now.get("boot") if now.get("boot") != old_boot else None
    error = payload.get("error")
    waited = payload.get("waited")
    allowed = {"send", "batch send", "exit", "permission restart", "reboot", "restart",
               "cockpit write", "terminal action", "checkout"}
    operations = sorted({op for op in waited if isinstance(op, str) and op in allowed}) if isinstance(waited, list) else []
    state = _state_dir()
    state.mkdir(exist_ok=True, parents=True, mode=0o700)
    attempt = _attempt_file(root, runtime, port, target)
    attempt_state = _attempt_state(attempt)
    if attempt_state.get("stop_boot") != old_boot:
        attempt_state = {}
    outcome = {
        "time": _timestamp(),
        "old_sha": old_sha, "target_sha": target, "new_sha": now.get("running_commit") if new_boot else None,
        "old_pid": int(BOOT.fullmatch(old_boot)[1]),
        "new_pid": int(BOOT.fullmatch(new_boot)[1]) if new_boot else None,
        "waited": operations, "error": error if isinstance(error, str) else None,
        **{key: attempt_state.get(key) for key in STOP_TIMESTAMPS},
        "new_listening_at": health.get("listening_at") if new_boot and health else None,
    }
    fd = os.open(state / "backend-updates.jsonl", os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(outcome, ensure_ascii=False) + "\n")
    if isinstance(error, str):
        _claim_attempt(attempt)
        _save_attempt_state(attempt, error=error)


def _darwin_argv(pid: int) -> list[str]:
    # CTL_KERN / KERN_PROCARGS2 return argc, the executable path, and real
    # NUL-delimited arguments, including arguments containing spaces.
    mib = (ctypes.c_int * 3)(1, 49, pid)
    sysctl = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True).sysctl
    sysctl.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_uint, ctypes.c_void_p,
                       ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_size_t]
    size = ctypes.c_size_t()
    if sysctl(mib, len(mib), None, ctypes.byref(size), None, 0) or not 4 < size.value <= 1 << 20:
        return []
    buf = ctypes.create_string_buffer(size.value)
    if sysctl(mib, len(mib), buf, ctypes.byref(size), None, 0):
        return []
    data = buf.raw[:size.value]
    argc = int.from_bytes(data[:4], sys.byteorder, signed=True)
    _, separator, args = data[4:].partition(b"\0")
    if not separator or not 2 <= argc <= 1024:
        return []
    return [os.fsdecode(arg) for arg in args.lstrip(b"\0").split(b"\0", argc)[:argc]]


def _lsof(pid: int, *filters: str) -> list[str]:
    result = subprocess.run(["/usr/sbin/lsof", "-nP", "-a", "-p", str(pid), *filters],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                            timeout=3, check=False)
    return result.stdout.splitlines() if result.returncode == 0 else []


def _linux_listens(process: Path, port: int) -> bool:
    inodes = set()
    for table in ("tcp", "tcp6"):
        path = process / "net" / table
        if not path.exists():
            continue
        for line in path.read_text().splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 10 and fields[3] == "0A" and fields[1].endswith(f":{port:04X}"):
                inodes.add(f"socket:[{fields[9]}]")
    for fd in (process / "fd").iterdir():
        try:
            if os.readlink(fd) in inodes:
                return True
        except FileNotFoundError:
            continue
    return False


def _owns_backend(pid: int, root: Path, port: int) -> bool:
    try:
        if sys.platform == "darwin":
            if f"p{pid}" not in _lsof(pid, f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"):
                return False
            args = _darwin_argv(pid)
            cwd = next((line[1:] for line in _lsof(pid, "-d", "cwd", "-Fn")
                        if line.startswith("n")), "")
        elif sys.platform == "linux":
            process = Path("/proc") / str(pid)
            if not _linux_listens(process, port):
                return False
            args = [os.fsdecode(arg) for arg in (process / "cmdline").read_bytes().split(b"\0")]
            cwd = os.readlink(process / "cwd")
        else:
            return False
        return (len(args) >= 2 and Path(args[0]).name.lower().startswith("python")
                and (bool(cwd) or Path(args[1]).is_absolute())
                and (Path(cwd) / args[1]).resolve() == root / "bridge/orrery_backend.py")
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def _port_is_clear(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.settimeout(0.2)
        return listener.connect_ex(("127.0.0.1", port)) == errno.ECONNREFUSED


def _wait_for_backend_exit(pid: int, pidfd: int | None, observer: OSObserver, birth: str,
                           port: int, timings: dict[str, str]) -> None:
    deadline = time.monotonic() + BACKEND_STOP_TIMEOUT
    while True:
        exited = (bool(select.select([pidfd], [], [], 0)[0]) if pidfd is not None else
                  (observer.process(pid) or {}).get("birth") != birth)
        port_clear = _port_is_clear(port)
        if exited and "process_exited_at" not in timings:
            timings["process_exited_at"] = _timestamp()
        if port_clear and "port_cleared_at" not in timings:
            timings["port_cleared_at"] = _timestamp()
        if exited and port_clear:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if exited:
                raise LifecycleError("The backend exited, but its port is still in use.")
            raise LifecycleError("The backend did not exit after receiving SIGTERM.")
        time.sleep(min(0.1, remaining))


def stop_stale(port: int, root: Path, runtime: dict, expected_boot: str, commit: str, automatic: bool) -> dict:
    health = read_health(port)
    installed = installed_commit(root)
    status = version_status(health, root, installed, runtime)
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit) or not isinstance(expected_boot, str) or not BOOT.fullmatch(expected_boot):
        raise LifecycleError("Invalid backend update identity.")
    attempt = _attempt_file(root, runtime, port, commit)
    if not automatic:
        if status["state"] == "current":
            return {**status, "restarted": False}
        if status["state"] == "unavailable" and installed and _port_is_clear(port):
            if checkout_ready(root, installed):
                return {"state": "stopped", "boot": expected_boot, "installed_commit": installed}
            return {"state": "busy", "operations": ["checkout"]}
        if status["state"] == "stale":
            expected_boot = status["boot"]
            commit = status["installed_commit"]
    if status["state"] != "stale" or status["boot"] != expected_boot or status["installed_commit"] != commit:
        raise LifecycleError("The running backend changed. Check for the update again.")
    if automatic and attempt.exists():
        result = {"state": "spent"}
        if reason := _attempt_state(attempt).get("error"):
            result["reason"] = reason
        return result
    if not checkout_ready(root, commit):
        return {"state": "busy", "operations": ["checkout"]}
    if not status["restart_guard"]:
        raise LifecycleError("This backend cannot verify idle activity. Restart it once from its launcher.")
    pid = int(BOOT.fullmatch(expected_boot)[1])
    observer = OSObserver()
    identity = observer.process(pid) if pid > 1 else None
    if not identity or identity["uid"] != os.getuid() or not _owns_backend(pid, root, port):
        raise LifecycleError("Could not verify the backend process on the selected port.")

    pidfd = None
    token = None
    stopped = False
    timings = {}
    try:
        if sys.platform == "linux":
            pidfd = os.pidfd_open(pid)
        # Recheck both health and kernel birth after the potentially slow checks.
        latest = version_status(read_health(port), root, installed_commit(root), runtime)
        if latest != status or (observer.process(pid) or {}).get("birth") != identity["birth"]:
            raise LifecycleError("The running backend changed before it could be stopped.")
        guard = _request(port, "/telemetry/backend-restart", {"boot": expected_boot, "action": "drain"})
        if guard and guard.get("state") == "busy":
            return guard
        if not guard or guard.get("state") != "drained" or not isinstance(guard.get("token"), str):
            raise LifecycleError("Could not verify that cockpit operations finished.")
        token = guard["token"]
        if not checkout_ready(root, commit):
            return {"state": "busy", "operations": ["checkout"]}
        confirmed = _request(port, "/telemetry/backend-restart",
                             {"boot": expected_boot, "action": "confirm", "token": token})
        if not confirmed or confirmed.get("state") != "drained":
            raise LifecycleError("Could not verify that cockpit operations finished.")
        if (observer.process(pid) or {}).get("birth") != identity["birth"]:
            raise LifecycleError("The running backend changed before it could be stopped.")
        if automatic and not _claim_attempt(attempt):
            return {"state": "spent"}
        try:
            if pidfd is None:
                os.kill(pid, signal.SIGTERM)
            else:
                signal.pidfd_send_signal(pidfd, signal.SIGTERM)
            timings["term_sent_at"] = _timestamp()
        except ProcessLookupError:
            # A verified process can finish between the last check and TERM.
            pass
        _wait_for_backend_exit(pid, pidfd, observer, identity["birth"], port, timings)
        stopped = True
        if not automatic:
            _claim_attempt(attempt)
        return {"state": "stopped", "boot": expected_boot, "installed_commit": commit}
    except (OSError, AttributeError) as exc:
        raise LifecycleError("Could not safely stop the selected backend process.") from exc
    finally:
        if token is not None and not stopped:
            _request(port, "/telemetry/backend-restart", {"boot": expected_boot, "action": "release", "token": token})
        if pidfd is not None:
            os.close(pidfd)
        if automatic and timings:
            _save_attempt_state(attempt, stop_boot=expected_boot, **timings)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "stop", "record"))
    parser.add_argument("port", type=int, metavar="PORT")
    parser.add_argument("runtime", help="expected runtime identity as JSON")
    parser.add_argument("boot", nargs="?")
    parser.add_argument("commit", nargs="?")
    parser.add_argument("intent", nargs="?", choices=("automatic", "manual"))
    args = parser.parse_args()
    try:
        runtime = json.loads(args.runtime)
        if (not isinstance(runtime, dict) or runtime.get("runtime_mode") not in {"legacy", "global", "fresh"}
                or not 1 <= args.port <= 65535):
            raise LifecycleError("Invalid backend runtime selection.")
        if args.action == "stop":
            print(json.dumps(stop_stale(args.port, ROOT, runtime, args.boot, args.commit, args.intent == "automatic")))
        elif args.action == "record":
            _log_restart(json.loads(args.boot), args.port, ROOT, runtime)
        else:
            print(json.dumps(version_status(read_health(args.port), ROOT, installed_commit(ROOT), runtime)))
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
