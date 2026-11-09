"""Public task annotations survive the legacy bridge compatibility layer."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from orrery_backend import normalize_annotations, prepare_agents_payload


def test_task_only_annotation_survives_normalization():
    assert normalize_annotations({'annotations': {'BuilderFixture': {'task': ' User summary '}}}) == {
        'BuilderFixture': {'role': '', 'emoji': '', 'group': '', 'task': 'User summary'},
    }


def test_authoritative_roster_annotation_wins_over_cached_compatibility_labels():
    labels = {'BuilderFixture': {'role': 'stale', 'task': 'Stale summary'}}
    for annotation in (None, {'role': 'reviewer', 'task': 'New summary'}):
        payload = json.dumps({'agents': [{'name': 'BuilderFixture', 'annot': annotation}]}).encode()
        row = json.loads(prepare_agents_payload(payload, labels))['agents'][0]
        assert row['annot'] == annotation


def test_old_roster_still_uses_compatibility_annotations():
    label = {'role': 'builder', 'emoji': '', 'group': 'fixtures'}
    payload = json.dumps({'agents': [{'name': 'BuilderFixture'}]}).encode()
    assert json.loads(prepare_agents_payload(payload, {'BuilderFixture': label}))['agents'][0]['annot'] == label
