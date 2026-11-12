"""Only the explicitly published display state is shared with the phone."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import orrery_backend as ob


def test_snapshot_defaults_off_and_omits_unrelated_preferences(monkeypatch):
    assert ob.shared_demo_state({'oc-term-font':'secret'})==dict(version=1,on=False,words=[],identity=None)
    monkeypatch.setattr(ob,'demo_identity',lambda:dict(home='/Users/mira',users=['mira'],hosts=['mira-node']))
    snapshot=ob.shared_demo_state({'orrery.demo.shared.v1':json.dumps(dict(version=1,on=True,words=['Orchid'])),'oc-term-font':'secret'})
    assert snapshot==dict(version=1,on=True,words=['Orchid'],identity=dict(users=['mira'],hosts=['mira-node']))
    assert ob.prefs_key_ok('orrery.demo.shared.v1')
    assert not ob.prefs_key_ok('orrery.demo.shared.v1.other')
    assert not ob.prefs_key_ok('orrery.demo-mode.v1')


@pytest.mark.parametrize('value',[None,{},dict(version=True,on=True,words=[]),dict(version=1,on=1,words=[]),dict(version=1,on=True,words=['x']),dict(version=1,on=True,words=[],extra='secret')])
def test_invalid_snapshot_never_becomes_an_unmasked_success(value):
    with pytest.raises((ValueError,TypeError)):
        ob.shared_demo_state({'orrery.demo.shared.v1':json.dumps(value)})
