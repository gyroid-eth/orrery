"""Unavailable picker choices explain preparation without changing launch guards."""
import json
import subprocess
from pathlib import Path

from test_cockpit_tour import tour_browser  # noqa: F401

BRIDGE = Path(__file__).resolve().parents[1]


def node(body):
    result = subprocess.run(['node', '-e',
        f'const picker=require({json.dumps(str(BRIDGE / "spawn_picker.js"))});\n' + body],
        capture_output=True, text=True, check=True, timeout=20)
    return json.loads(result.stdout)


def test_unavailable_explanations_hide_unknown_catalog_details():
    result = node('''console.log(JSON.stringify([
      picker.unavailableReason({available:false,reason:'runtime_not_prepared'}),
      picker.unavailableReason({available:false,reason:'unsupported_platform'}),
      picker.unavailableReason({available:false,reason:'private-account-and-path'}),
      picker.unavailableReason({available:false,reason:'constructor'}),
      picker.unavailableReason({available:true,reason:'runtime_not_prepared'})
    ]));''')
    assert result == ['Install or repair this harness', 'Unavailable on this OS',
                      'Check setup and compatibility', 'Check setup and compatibility', '']


def test_unavailable_harness_explains_preparation_and_recovers_when_ready(tour_browser):
    _, evaluate = tour_browser
    result = evaluate('''(()=>{
      spawnCatalog={providers:[{id:'deepseek',models:[{id:'deepseek-fixture',
        harnesses:[{id:'dsh',available:false,reason:'runtime_not_prepared'}]}]}],naming:{},dirs:[]};
      selFamily=null;selProvider=null;selModel=null;selHarness=null;spawnStatus.textContent='ready';
      renderProviderTabs();
      const blocked={text:spawnHarnesses.textContent,disabled:spawnSubmit.disabled,
        link:spawnHarnesses.querySelector('a').href,status:spawnStatus.textContent};
      spawnCatalog.providers[0].models[0].harnesses[0].available=true;
      renderHarnesses();
      return {blocked,ready:!spawnSubmit.disabled,status:spawnStatus.textContent,
        staleHelp:Boolean(spawnHarnesses.querySelector('a'))};
    })()''')
    assert result['blocked']['disabled']
    assert 'Install or repair this harness' in result['blocked']['text']
    assert result['blocked']['link'].endswith('/docs/native-setup.en.md')
    assert result['blocked']['status'] == 'No available harness for this model'
    assert result['ready'] and result['status'] == 'ready'
    assert not result['staleHelp']
