"""Settings → Phone: /telemetry/mobile runs Telemetry's agentstack-mobile and
makes the cockpit's "Send from phone" adapter follow it without a restart.

The helper is a fake on a temporary path; nothing here touches launchd, the
live reader or the real ~/.orrery/config.json.
"""
import asyncio
import json
import re

from test_static_assets import private_app, BRIDGE

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
log = os.environ['FAKE_MOBILE_LOG']
data = sys.stdin.read() if sys.argv[1] == 'apply' else ''
with open(log, 'a') as f:
    f.write(json.dumps([sys.argv[1:], data]) + '\n')
print(open(os.environ['FAKE_MOBILE_REPLY']).read())
'''


def status(send=True, access=True, reviewed=True, manual=False, saved=True):
    return {'ok': True, 'error': None, 'saved': saved,
            'settings': {'access': access, 'send': send, 'owner_login': 'owner@example.test',
                         'public_origin': 'https://computer.example.ts.net:9443',
                         'policy_reviewed_at': '2026-11-05T01:02:03Z' if reviewed else None},
            'effective': {'read': access, 'history': access and reviewed, 'send': access and send and reviewed},
            'relay': {'job': 'absent' if manual else 'loaded', 'listening': True, 'manual': manual,
                      'python_missing': False, 'port': 8781},
            'tailscale': {'found': True, 'signed_in': True, 'dns_name': 'computer.example.ts.net',
                          'login': 'owner@example.test', 'serve': 'ok', 'funnel': False},
            'suggest': {'owner_login': 'owner@example.test', 'public_origin': 'https://computer.example.ts.net:9443'}}


class Fake:
    def __init__(self, tmp_path, monkeypatch):
        self.helper = tmp_path / 'agentstack-mobile'
        self.helper.write_text(FAKE)
        self.helper.chmod(0o755)
        self.log = tmp_path / 'helper.log'
        self.log.write_text('')
        self.reply_file = tmp_path / 'reply.json'
        self.reply(status())
        self.config = tmp_path / 'orrery' / 'config.json'
        monkeypatch.setenv('ORRERY_MOBILE_HELPER', str(self.helper))
        monkeypatch.setenv('FAKE_MOBILE_LOG', str(self.log))
        monkeypatch.setenv('FAKE_MOBILE_REPLY', str(self.reply_file))

    def reply(self, value):
        self.reply_file.write_text(value if isinstance(value, str) else json.dumps(value))

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]


def run(monkeypatch, tmp_path, scenario, *, enabled=False):
    fake = Fake(tmp_path, monkeypatch)

    def configure(ob):
        import mobile_access
        monkeypatch.setattr(ob, 'CONFIG_PATH', fake.config)
        original = mobile_access.install

        def install(app, coordinator, **kw):
            fake.coordinator = coordinator
            coordinator.enabled = enabled
            return original(app, coordinator, **kw)
        monkeypatch.setattr(mobile_access, 'install', install)

    async def main():
        async with private_app(monkeypatch, tmp_path, configure) as (ob, client, base):
            await scenario(client, base, fake)
    asyncio.run(main())
    return fake



def test_status_is_the_helpers_answer_plus_the_cockpit_send_state(monkeypatch, tmp_path):
    async def scenario(client, base, fake):
        async with client.get(base + '/telemetry/mobile') as response:
            value = await response.json()
        assert value['settings']['owner_login'] == 'owner@example.test'
        # the adapter started off; telemetry says send is on, so it follows
        assert value['cockpit'] == {'send': True}
        assert response.headers['Cache-Control'] == 'no-store'
        assert fake.calls()[-1] == [['status'], '']
    run(monkeypatch, tmp_path, scenario)


def test_change_goes_to_the_helper_and_send_follows_without_a_restart(monkeypatch, tmp_path):
    async def scenario(client, base, fake):
        fake.config.parent.mkdir(parents=True)
        fake.config.write_text(json.dumps({'project_key': '/work/example', 'enable_mobile_terminal': False}))
        async with client.put(base + '/telemetry/mobile', json={'access': True, 'policy_reviewed': True}) as response:
            value = await response.json()
        assert fake.calls()[-1] == [['apply'], json.dumps({'access': True, 'policy_reviewed': True})]
        assert value['cockpit'] == {'send': True}
        saved = json.loads(fake.config.read_text())
        assert saved == {'project_key': '/work/example', 'enable_mobile_terminal': True}
        assert oct(fake.config.stat().st_mode & 0o777) == '0o600'
        assert fake.coordinator.enabled is True
        fake.reply(status(send=False))
        async with client.put(base + '/telemetry/mobile', json={'send': False}) as response:
            value = await response.json()
        assert value['cockpit'] == {'send': False} and fake.coordinator.enabled is False
        assert json.loads(fake.config.read_text())['enable_mobile_terminal'] is False
    run(monkeypatch, tmp_path, scenario)


def test_opening_settings_brings_send_in_line_with_telemetry(monkeypatch, tmp_path):
    # `agentstack-mobile off` from a terminal: the next look at Settings turns
    # the cockpit's Send adapter off too, and saves that for the next start.
    async def scenario(client, base, fake):
        fake.config.parent.mkdir(parents=True)
        fake.config.write_text(json.dumps({'enable_mobile_terminal': True}))
        fake.reply(status(access=False))
        async with client.get(base + '/telemetry/mobile') as response:
            assert (await response.json())['cockpit'] == {'send': False}
        assert fake.coordinator.enabled is False
        assert json.loads(fake.config.read_text())['enable_mobile_terminal'] is False
    run(monkeypatch, tmp_path, scenario, enabled=True)


def test_hand_started_reader_keeps_the_cockpit_send_as_configured(monkeypatch, tmp_path):
    # Today's Terminal users start the reader by hand with
    # enable_mobile_terminal in ~/.orrery/config.json. Settings does not own
    # that reader, so neither a look nor a change there turns their Send off.
    async def scenario(client, base, fake):
        fake.config.parent.mkdir(parents=True)
        fake.config.write_text(json.dumps({'enable_mobile_terminal': True}))
        fake.reply(status(access=False, manual=True))
        async with client.get(base + '/telemetry/mobile') as response:
            assert (await response.json())['cockpit'] == {'send': True}
        async with client.put(base + '/telemetry/mobile', json={'send': False}) as response:
            assert (await response.json())['cockpit'] == {'send': True}
        assert fake.coordinator.enabled is True
        assert json.loads(fake.config.read_text())['enable_mobile_terminal'] is True
    run(monkeypatch, tmp_path, scenario, enabled=True)


def test_settings_never_used_leave_the_existing_terminal_setting_alone(monkeypatch, tmp_path):
    async def scenario(client, base, fake):
        fake.reply(status(access=False, saved=False))
        async with client.get(base + '/telemetry/mobile') as response:
            assert (await response.json())['cockpit'] == {'send': True}
        assert fake.coordinator.enabled is True and not fake.config.exists()
    run(monkeypatch, tmp_path, scenario, enabled=True)


def test_turning_phone_access_off_turns_send_off_too(monkeypatch, tmp_path):
    async def scenario(client, base, fake):
        async with client.put(base + '/telemetry/mobile', json={'access': True}) as response:
            assert (await response.json())['cockpit'] == {'send': True}
        fake.reply(status(access=False))
        async with client.put(base + '/telemetry/mobile', json={'access': False}) as response:
            assert (await response.json())['cockpit'] == {'send': False}
    run(monkeypatch, tmp_path, scenario)


def test_unreviewed_policy_keeps_send_off_even_if_requested(monkeypatch, tmp_path):
    async def scenario(client, base, fake):
        fake.reply(status(send=True, reviewed=False))
        async with client.put(base + '/telemetry/mobile', json={'access': True, 'send': True}) as response:
            assert (await response.json())['cockpit'] == {'send': False}
    run(monkeypatch, tmp_path, scenario)


def test_bad_changes_are_refused_before_the_helper_runs(monkeypatch, tmp_path):
    async def scenario(client, base, fake):
        before = len(fake.calls())
        for body in ({}, {'history': False}, {'listen_port': 1}, [], 'x'):
            async with client.put(base + '/telemetry/mobile', json=body) as response:
                assert response.status == 400
                assert await response.json() == {'ok': False, 'error': 'change_invalid'}
        async with client.put(base + '/telemetry/mobile', data='{"access": true}',
                              headers={'Content-Type': 'text/plain'}) as response:
            assert response.status == 415
        async with client.put(base + '/telemetry/mobile', json={'access': True},
                              headers={'Origin': 'https://evil.example'}) as response:
            assert response.status == 403
        assert len(fake.calls()) == before
    run(monkeypatch, tmp_path, scenario)


def test_helper_errors_pass_only_as_fixed_codes(monkeypatch, tmp_path):
    async def scenario(client, base, fake):
        fake.reply({'ok': False, 'error': 'port_in_use'})
        async with client.put(base + '/telemetry/mobile', json={'access': True}) as response:
            assert await response.json() == {'ok': False, 'error': 'port_in_use'}
        fake.reply({'ok': False, 'error': '/Users/someone/.agentstack/mobile.json is bad'})
        async with client.get(base + '/telemetry/mobile') as response:
            assert await response.json() == {'ok': False, 'error': 'mobile_unavailable'}
        fake.reply('not json')
        async with client.get(base + '/telemetry/mobile') as response:
            assert await response.json() == {'ok': False, 'error': 'mobile_unavailable'}
        assert not fake.config.exists()
    run(monkeypatch, tmp_path, scenario)


def test_missing_telemetry_says_so(monkeypatch, tmp_path):
    async def scenario(client, base, fake):
        fake.helper.unlink()
        async with client.get(base + '/telemetry/mobile') as response:
            assert await response.json() == {'ok': False, 'error': 'telemetry_missing'}
    fake = Fake(tmp_path, monkeypatch)

    async def main():
        async with private_app(monkeypatch, tmp_path) as (ob, client, base):
            await scenario(client, base, fake)
    asyncio.run(main())


def test_unreadable_config_is_not_overwritten(monkeypatch, tmp_path):
    async def scenario(client, base, fake):
        fake.config.parent.mkdir(parents=True)
        fake.config.write_text('{broken')
        async with client.put(base + '/telemetry/mobile', json={'access': True}) as response:
            value = await response.json()
        assert value['warning'] == 'config_invalid' and value['cockpit'] == {'send': True}
        assert fake.config.read_text() == '{broken'
    run(monkeypatch, tmp_path, scenario)


def test_default_helper_is_telemetrys_installed_command(monkeypatch, tmp_path):
    import mobile_access
    monkeypatch.delenv('ORRERY_MOBILE_HELPER', raising=False)
    monkeypatch.setenv('AGENTSTACK_HOME', str(tmp_path / 'stack'))
    assert mobile_access.helper_path() == tmp_path / 'stack' / 'bin' / 'agentstack-mobile'


def test_send_off_drops_pending_choices(monkeypatch, tmp_path):
    from mobile_input import InputCoordinator
    c = InputCoordinator(None, None, enabled=True)
    c.choices['x'] = {'expires': 1e18}
    c.set_enabled(False)
    assert c.enabled is False and c.choices == {}
    c.set_enabled(True)
    assert c.enabled is True


def test_phone_settings_page_builds_no_html_from_data():
    source = (BRIDGE / 'phone_settings.js').read_text()
    assert not re.search(r'innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(|new Function', source)
    html = (BRIDGE / 'cockpit.html').read_text()
    assert '<script src="phone_settings.js"></script>' in html and 'id="phoneSettings"' in html


def test_desktop_conversation_history_is_on_unless_chosen_off():
    html = (BRIDGE / 'cockpit.html').read_text()
    assert "if(localStorage.getItem(key)===null)localStorage.setItem(key,'1');" in html
    assert 'On by default.' in html and 'Off by default.' not in html.split('id="conversationEnabled"')[0][-400:]
