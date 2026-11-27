"""Unavailable picker choices explain preparation without changing launch guards."""
import json
import subprocess
from pathlib import Path

import pytest

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
      picker.unavailableReason({available:false,reason:'disabled_by_opt_in'}),
      picker.unavailableReason({available:false,reason:'unsupported_credential_store'}),
      picker.unavailableReason({available:false,reason:'private-account-and-path'}),
      picker.unavailableReason({available:false,reason:'constructor'}),
      picker.unavailableReason({available:true,reason:'runtime_not_prepared'})
    ]));''')
    assert result == ['Install or repair this harness', 'Unavailable on this OS',
                      'Enable this harness in setup', 'Use the supported OS key store',
                      'Check setup and compatibility', 'Check setup and compatibility', '']


def test_unavailable_harness_explains_preparation_and_recovers_when_ready(tour_browser):
    _, evaluate = tour_browser
    result = evaluate('''(()=>{
      spawnCatalog={providers:[{id:'deepseek',models:[{id:'deepseek-fixture',
        harnesses:[{id:'dsh',available:false,reason:'runtime_not_prepared'}]}]}],naming:{},dirs:[]};
      selFamily=null;selProvider=null;selModel=null;selHarness=null;spawnTask.value='Fixture task';
      renderProviderTabs();
      const blocked={reason:spawnHarnesses.querySelector('button').title,disabled:spawnSubmit.disabled,
        link:spawnHarnessHelp.href,linkVisible:!spawnHarnessHelp.hidden,harnessHidden:spawnHarnesses.hidden,status:spawnStatus.textContent};
      spawnCatalog.providers[0].models[0].harnesses[0].available=true;
      renderHarnesses();
      return {blocked,ready:!spawnSubmit.disabled,status:spawnStatus.textContent,
        staleHelp:!spawnHarnessHelp.hidden};
    })()''')
    assert result['blocked']['disabled']
    assert 'Install or repair dsh' in result['blocked']['reason']
    assert result['blocked']['link'].endswith('/docs/en/native-setup.md')
    assert result['blocked']['linkVisible'] and result['blocked']['harnessHidden']
    assert result['blocked']['status'] == 'Install or repair dsh. Open model settings for setup.'
    assert result['ready'] and result['status'] == ''
    assert not result['staleHelp']


@pytest.mark.parametrize(('provider', 'harness', 'name', 'guide'), [
    ('claude', 'claude-code', 'Claude Code CLI', 'install.md'),
    ('codex', 'codex-cli', 'Codex CLI', 'install.md'),
    ('gemini', 'antigravity', 'Antigravity CLI (agy)', 'antigravity.md'),
    ('deepseek', 'hermes', 'Hermes', 'native-setup.md'),
])
def test_missing_cli_uses_setup_guide_and_keeps_draft(tour_browser, provider, harness, name, guide):
    _, evaluate = tour_browser
    choice = json.dumps({'id': provider, 'models': [{'id': 'fixture'}],
                         'harnesses': [{'id': harness, 'available': True}]})
    result = evaluate('''(()=> {
      spawnCatalog={providers:[CHOICE],naming:{},dirs:[]};
      selFamily=null;selModel=null;selHarness=null;spawnChooseAgain=false;spawnProblem='';
      spawnTask.value='Keep this draft';renderProviderTabs();
      const ready=!spawnSubmit.disabled;
      const offered=spawnCatalog.providers[0].harnesses[0];
      Object.assign(offered,{available:false,reason:'runtime_not_prepared'});
      renderProviderTabs(true);
      const missing={disabled:spawnSubmit.disabled,notice:spawnStatus.textContent,link:spawnHarnessHelp.href,
        visible:!spawnHarnessHelp.hidden,sheet:!spawnHarnessNotice.hidden&&spawnHarnessNotice.textContent,
        model:selModel,draft:spawnTask.value};
      offered.available=true;
      renderProviderTabs(true);
      return {ready,missing,recovered:!spawnSubmit.disabled&&!spawnStatus.textContent&&spawnHarnessHelp.hidden};
    })()'''.replace('CHOICE', choice))
    assert result['ready'] and result['recovered']
    assert result['missing'] == {
        'disabled': True, 'notice': f'Install or repair {name}. Open model settings for setup.',
        'link': f'https://github.com/gyroid-eth/orrery/blob/master/docs/en/{guide}',
        'visible': True, 'sheet': f'Install or repair {name}', 'model': 'fixture', 'draft': 'Keep this draft',
    }


def test_local_discovery_without_a_runtime_links_to_harness_setup(tour_browser):
    _, evaluate = tour_browser
    result = evaluate('''(()=> {
      spawnCatalog={providers:[{id:'local-fixture',locality:'local',dynamic_models:true,
        model_error:'runtime_not_prepared',models:[]}],naming:{},dirs:[]};
      selFamily='local';selProvider=null;selModel=null;selUrlIndex=null;selHarness=null;
      spawnChooseAgain=false;spawnProblem='';spawnTask.value='Fixture';
      renderProviderTabs();
      return {disabled:spawnSubmit.disabled,notice:spawnHarnessNotice.textContent,
        link:!spawnHarnessHelp.hidden&&spawnHarnessHelp.href};
    })()''')
    assert result['disabled']
    assert result['notice'] == 'Install or repair dsh or Hermes'
    assert result['link'].endswith('/docs/en/native-setup.md')
