"""Legacy cockpit adapter for Telemetry's single target admission boundary.

Global terminal protocol belongs to a later change. Missing/old helpers only
retain the old behavior when fixed-layout absence has been proved here.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import runpy
import shlex
import stat
import subprocess
import threading


class TargetRefused(RuntimeError):
    pass


class LegacyTargetBoundary:
    """One frozen endpoint per consumer, with fresh admission per operation."""

    def __init__(self, binary, *, home=None, environ=None):
        self.binary = binary
        self._pin_lock = threading.Lock()  # ephemeral consumer pin, no lock file
        self.environment = dict(os.environ if environ is None else environ)
        self.home = Path(home or self.environment.get('AGENTSTACK_HOME') or Path.home() / '.agentstack')
        self.shared = None
        self.transport = None
        self.pin = None
        self.fallback_pid = None
        self.validate = None
        self._settings_stamp = None
        self._settings_hint = False
        module = self.home / 'bin/lib/runtime_tmux.py'
        if module.exists() or module.is_symlink():
            try:
                info = module.lstat()
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_mode & 0o022 or module.resolve() != module):
                    raise TargetRefused('GLOBAL_TARGET_HELPER_UNAVAILABLE')
                shared = runpy.run_path(str(module))
                if (shared.get('CONTRACT') != 'orrery-tmux-target-v1'
                        or not {'legacy-transport', 'legacy-target-admission'} <= set(shared.get('CAPABILITIES', []))):
                    raise TargetRefused('GLOBAL_TARGET_HELPER_UNAVAILABLE')
                validator = runpy.run_path(str(module.with_name('schema_contract.py')))
                self.validate = validator['validate_schema']
                for key in ('legacy_transport', 'legacy_admission', 'result_schema', 'check_pinned_transport', 'global_proofs', 'REASONS', 'TargetError'):
                    if key not in shared:
                        raise TargetRefused('GLOBAL_TARGET_HELPER_UNAVAILABLE')
                self.shared = shared
            except (Exception, SystemExit):
                self.shared = None
        if self.shared is not None:
            try:
                self.transport = self.shared['legacy_transport'](binary=binary, environ=self.environment)
                self.pin = self.transport.public()
                self.validate({'contract':self.shared['CONTRACT'],'ok':True,**self.pin}, self.shared['result_schema']('legacy-transport'))
                self.prefix = self.transport.argv
            except (Exception, SystemExit) as exc:
                self._helper_failure(exc)
                self.shared = None
                self.prefix = self._legacy_bootstrap()
        else:
            self.prefix = self._legacy_bootstrap()

    def __str__(self):
        return str(self.binary)

    def env(self):
        return {k: v for k, v in self.environment.items() if k not in ('TMUX', 'TMUX_PANE')}

    def _installed_hint(self):
        """Reuse the installed literal reader; never execute env.sh or parse it twice."""
        path = self.home / 'env.sh'
        if not path.exists() and not path.is_symlink():
            return False
        try:
            info = path.lstat()
            stamp = (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size)
            if stamp == self._settings_stamp:
                return self._settings_hint
            reader = self.home / 'hooks/project-context.sh'
            reader_info = reader.lstat()
            if (not stat.S_ISREG(info.st_mode) or not stat.S_ISREG(reader_info.st_mode)
                    or info.st_uid != os.getuid() or reader_info.st_uid != os.getuid()
                    or info.st_mode & 0o022 or reader_info.st_mode & 0o022
                    or path.resolve() != path or reader.resolve() != reader):
                return True
            result = subprocess.run(['/bin/bash', '-c',
                '. "$1"; for key in AGENTSTACK_RUNTIME_MODE AGENTSTACK_GLOBAL_SERVER_CONFIG AGENTSTACK_CLIENT_CONFIG; do '
                'agentstack_installed_env_value "$key" "$2" --shell || exit 2; printf "\\n"; done',
                'runtime-target-settings', str(reader), str(path)],
                capture_output=True, text=True, timeout=5, env=self.env())
            if result.returncode:
                return True
            values = {}
            for line in result.stdout.splitlines():
                if not line:
                    continue
                tokens = shlex.split(line)
                if len(tokens) != 2 or tokens[0] != 'export' or '=' not in tokens[1]:
                    return True
                name, value = tokens[1].split('=', 1)
                if name in values:
                    return True
                values[name] = value
            hint = (values.get('AGENTSTACK_RUNTIME_MODE', 'legacy') not in ('', 'legacy')
                    or bool(values.get('AGENTSTACK_GLOBAL_SERVER_CONFIG'))
                    or bool(values.get('AGENTSTACK_CLIENT_CONFIG')))
            after = path.lstat()
            if stamp != (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_size):
                return True
            self._settings_stamp, self._settings_hint = stamp, hint
            return hint
        except (OSError, ValueError, subprocess.SubprocessError):
            return True

    def global_hint(self):
        # This is missing-helper admission, not a runtime mode selector.
        paths = [self.home / 'clients', self.home / 'runtime-client.json']
        for key in ('AGENTSTACK_CLIENT_CONFIG', 'AGENTSTACK_GLOBAL_SERVER_CONFIG'):
            if self.environment.get(key):
                return True
        if self.environment.get('AGENTSTACK_RUNTIME_MODE', 'legacy') not in ('', 'legacy'):
            return True
        try:
            return any(p.exists() or p.is_symlink() for p in paths) or self._installed_hint()
        except OSError:
            return True

    def _legacy_bootstrap(self):
        # This bootstrap is only for an old/missing/broken shared helper. It
        # selects one legacy endpoint, never a global target or an owner.
        inherited = self.environment.get('TMUX')
        expected_pid = None
        if inherited:
            parts = inherited.rsplit(',', 2)
            if len(parts) != 3 or not parts[1].isdigit():
                raise TargetRefused('LEGACY_TMUX_TRANSPORT_UNAVAILABLE')
            path = Path(parts[0])
            expected_pid = int(parts[1])
        else:
            base = Path(self.environment.get('TMUX_TMPDIR') or '/tmp').resolve()
            path = base / ('tmux-' + str(os.getuid())) / 'default'
        if str(path).startswith('/tmp/'):
            path = Path('/tmp').resolve() / path.relative_to('/tmp')
        if path.parent == Path('/tmp').resolve() / ('orrery-tmux-' + str(os.getuid())):
            raise TargetRefused('GLOBAL_TMUX_LEGACY_CONSUMER_REFUSED')
        if not path.is_absolute() or any(c in str(path) for c in '\0\r\n') or path.resolve() != path:
            raise TargetRefused('LEGACY_TMUX_TRANSPORT_UNAVAILABLE')
        prefix = [self.binary, '-S', str(path)]
        if inherited or path.exists() or path.is_symlink():
            self.fallback_pid = self._fallback_server(prefix)
            if expected_pid is not None and expected_pid != self.fallback_pid:
                raise TargetRefused('LEGACY_TMUX_TRANSPORT_UNAVAILABLE')
        return prefix

    def _fallback_server(self, prefix):
        try:
            result = subprocess.run([*prefix, 'display-message', '-p', '#{socket_path}\t#{pid}'],
                capture_output=True, text=True, timeout=3, env=self.env())
            fields = result.stdout.strip().split('\t')
            if result.returncode or len(fields) != 2 or fields[0] != prefix[-1] or not fields[1].isdigit():
                raise TargetRefused('LEGACY_TMUX_TRANSPORT_UNAVAILABLE')
            return int(fields[1])
        except (OSError, subprocess.SubprocessError) as exc:
            raise TargetRefused('LEGACY_TMUX_TRANSPORT_UNAVAILABLE') from exc

    def _fallback_admit(self):
        if self.global_hint():
            raise TargetRefused('GLOBAL_TARGET_HELPER_UNAVAILABLE')
        pid = self._fallback_server(self.prefix)
        with self._pin_lock:
            expected = self.fallback_pid if self.fallback_pid is not None else (self.pin or {}).get('server_pid')
            if expected is not None and pid != expected:
                raise TargetRefused('TMUX_SOCKET_CHANGED')
            self.fallback_pid = pid

    def _helper_failure(self, exc):
        # Only the shared helper defines domain refusals. Broken/old helpers
        # use the same negative admission as a missing helper.
        if self.shared is not None and isinstance(exc, self.shared['TargetError']):
            reason = str(exc)
            if self.shared['REASONS'].get(reason) in ('target', 'transport'):
                raise TargetRefused(reason) from exc
        if self.global_hint():
            raise TargetRefused('GLOBAL_TARGET_HELPER_UNAVAILABLE') from exc

    def allow_new_session(self):
        # No target exists yet. Establish placement completeness before the
        # atomic tmux new-session; never create first and discover uncertainty.
        if self.shared is None:
            if self.global_hint():
                raise TargetRefused('GLOBAL_TARGET_HELPER_UNAVAILABLE')
            return
        try:
            self.shared['global_proofs'](self.home)
        except (Exception, SystemExit) as exc:
            self._helper_failure(exc)

    def admit(self, operation, *, session=None, pane=None):
        if self.shared is None:
            self._fallback_admit()
            return  # Proven pure legacy; preserve its existing target rules.
        try:
            refreshed = self.shared['legacy_transport'](binary=self.binary, environ=self.environment)
            public = refreshed.public()
            self.validate({'contract':self.shared['CONTRACT'],'ok':True,**public},
                          self.shared['result_schema']('legacy-transport'))
            with self._pin_lock:
                self.pin = self.shared['check_pinned_transport'](self.pin, public)
                if self.transport.identity is None:
                    self.transport = refreshed
                transport = self.transport
            value = self.shared['legacy_admission'](transport, self.home,
                session=session, pane=pane, operation=operation)
            self.validate(value, self.shared['result_schema']('legacy-target'))
            with self._pin_lock:
                self.shared['check_pinned_transport'](self.pin, value)
            return value
        except (Exception, SystemExit) as exc:
            self._helper_failure(exc)
            self._fallback_admit()
            return  # Helper unavailable, and fixed layout proves pure legacy.


def admit_creation(binary):
    if isinstance(binary, LegacyTargetBoundary):
        binary.allow_new_session()


def require_target(binary, operation, *, session=None, pane=None):
    if isinstance(binary, LegacyTargetBoundary):
        return binary.admit(operation, session=session, pane=pane)


def tmux_argv(binary, *args):
    """Transport is a value, never arguments hidden in an executable wrapper."""
    return [*(binary.prefix if isinstance(binary, LegacyTargetBoundary) else [binary]), *args]


def tmux_env(binary):
    return {'env': binary.env()} if isinstance(binary, LegacyTargetBoundary) else {}


def admit_command(binary, args, *, session):
    if not isinstance(binary, LegacyTargetBoundary):
        return  # Private pure helpers retain their legacy unit-test interface.
    target = None
    if '-t' in args and args.index('-t') + 1 < len(args):
        target = args[args.index('-t') + 1]
    operation = ('split' if args[0] == 'split-window' else
                 'close' if args[0] == 'kill-pane' else
                 'kill-session' if args[0] == 'kill-session' else
                 'capture' if args[0] in ('capture-pane', 'list-panes', 'display-message') else 'input')
    if isinstance(target, str) and re.fullmatch(r'%[0-9]+', target):
        binary.admit(operation, pane=target)
    else:
        binary.admit(operation, session=session)
