import json

from tools import theme_axis_inventory


def test_theme_axis_inventory_is_complete_and_current():
    inventory = theme_axis_inventory.build_inventory()

    assert inventory["validation"] == {
        "missing_manifest_records": [],
        "uncovered_effect_declarations": [],
    }
    for axis_name, axis in inventory["axes"].items():
        assert axis["source"]["expected"] > 0, axis_name
        if axis_name in {"small-text", "tracking"}:
            assert axis["mutation"]["expected_rule"]
        else:
            assert axis["mutation"]["expected"] > 0, axis_name

    committed = json.loads(theme_axis_inventory.SNAPSHOT.read_text())
    assert committed == inventory
