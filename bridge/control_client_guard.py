#!/usr/bin/env python3
"""Keep one tmux control client alive only while its backend owns a pipe.

The PTY is a data channel, not a lifetime guarantee: another process can keep
the master open after the backend dies. This separate pipe has a single writer
in the backend. No process discovery or signalling of unowned clients is used.
"""
from __future__ import annotations

import os
import select
import signal
import subprocess
import sys


def main() -> int:
    lifetime_fd = int(sys.argv[1])
    # Do not leak the lifetime pipe to tmux (or anything it might launch).
    os.set_inheritable(lifetime_fd, False)
    stopping = False

    def terminate(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    signal.signal(signal.SIGHUP, terminate)
    client = None
    try:
        # A signal during Popen must not interrupt assignment of the child we
        # need to reap. The handler only sets a flag, including during cleanup.
        client = subprocess.Popen(sys.argv[2:], close_fds=True)
        while not stopping and client.poll() is None:
            readable, _, _ = select.select([lifetime_fd], [], [], 0.2)
            if readable and not os.read(lifetime_fd, 1):
                break
    finally:
        os.close(lifetime_fd)
        if client is not None and client.poll() is None:
            client.terminate()
            try:
                client.wait(timeout=1)
            except subprocess.TimeoutExpired:
                client.kill()
                client.wait()
    return client.returncode or 0


if __name__ == '__main__':
    raise SystemExit(main())
