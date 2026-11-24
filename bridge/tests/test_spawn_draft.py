import json
import time

from test_cockpit_tour import tour_browser


CATALOG = {
    "providers": [
        {"id": "claude", "program": "claude-code", "models": [{"id": "claude-fixture"}]},
        {"id": "codex", "program": "codex", "models": [{"id": "gpt-default"}, {"id": "gpt-review"}],
         "efforts": ["low", "high"], "effort_default": "low"},
    ],
    "dirs": [{"path": "/workspace"}],
    "naming": {"scientists": ["Curie"], "adjectives": ["Quiet"], "taken": []},
}

BOOTSTRAP = """
window.fixtureLaunchState='failed';
const fetchOriginal=window.fetch.bind(window);
window.fetch=(input,options)=>{
  const url=new URL(typeof input==='string'?input:input.url,location.href);
  let data;
  switch(url.pathname){
    case '/telemetry/spawn-catalog': data=CATALOG;break;
    case '/telemetry/fs/dirs': data={path:'/workspace',home:'/workspace',dirs:[]};break;
    case '/telemetry/spawn': data={ok:true,pending:true,child_name:'QuietCurie'};break;
    case '/telemetry/spawn-status': data={ok:true,state:window.fixtureLaunchState,error:'Fixture failure'};break;
    default:return fetchOriginal(input,options);
  }
  return Promise.resolve(Response.json(data));
};
""".replace("CATALOG", json.dumps(CATALOG))

FILL = """(async()=>{
  const enter=(control,value)=>{
    control.value=value;
    control.dispatchEvent(new Event('input',{bubbles:true}));
  };
  openSpawnModal();
  await loadSpawnCatalog();
  enter(spawnTask,'Review the plan');
  spawnNameButton.click();
  agentStrip.querySelector('[data-scientist=Curie]').click();
  enter(spawnAdjective,'Quiet');
  enter(spawnRole,'Reviewer');
  spawnModelButton.click();
  providerTabs.querySelector('[data-family=codex]').click();
  modelChoices.querySelector('[value=gpt-review]').click();
  const effort=effortChoices.querySelector('input[type=range]');
  enter(effort,effort.max);
  chooseSpawnDir('/workspace/review');
  spawnComputerUse.click();
  return spawnPayloadFromForm();
})()"""

REOPEN = """(async()=>{openSpawnModal();await loadSpawnCatalog();return spawnPayloadFromForm();})()"""


def reload_with_fixture(client, evaluate, source=BOOTSTRAP):
    client.call("Page.addScriptToEvaluateOnNewDocument", source=source)
    client.call("Page.reload")
    for _ in range(100):
        if evaluate("typeof openSpawnModal==='function'&&document.readyState==='complete'"):
            return
        time.sleep(.05)
    raise AssertionError("Cockpit did not reload")


def test_new_agent_draft_survives_dismissal_and_reload(tour_browser):
    client, evaluate = tour_browser
    evaluate(BOOTSTRAP)
    draft = evaluate(FILL)
    assert (draft["name"], draft["role"], draft["model"], draft["effort"], draft["dir"]) == (
        "QuietCurie", "Reviewer", "gpt-review", "high", "/workspace/review"
    )
    for action in (
        "spawnOverlay.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}))",
        "dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))",
    ):
        evaluate(action)
        assert not evaluate("spawnOverlay.classList.contains('on')")
        assert evaluate(REOPEN) == draft

    reload_with_fixture(client, evaluate)
    assert evaluate(REOPEN) == draft
    assert evaluate("!OrreryPrefs.synced(SPAWN_DRAFT_KEY)")


def test_discard_button_clears_saved_draft_and_resets_form(tour_browser):
    _, evaluate = tour_browser
    evaluate(BOOTSTRAP)
    evaluate(FILL)
    result = evaluate("""(async()=>{
      spawnDiscardDraft.click();
      await new Promise(resolve=>setTimeout(resolve,20));
      return {stored:localStorage.getItem(SPAWN_DRAFT_KEY),open:spawnOverlay.classList.contains('on'),
        hidden:spawnDiscardDraft.hidden,payload:spawnPayloadFromForm()};
    })()""")
    assert result["stored"] is None and result["open"] and result["hidden"]
    assert result["payload"]["task"] == "" and result["payload"]["name"] is None
    assert result["payload"]["model"] == "claude-fixture"


def test_restored_task_stays_masked_in_demo_mode(tour_browser):
    client, evaluate = tour_browser
    evaluate(BOOTSTRAP)
    evaluate(FILL)
    evaluate("""spawnTask.value='Review on FixtureHost';
      spawnTask.dispatchEvent(new Event('input',{bubbles:true}));""")
    reload_with_fixture(client, evaluate, BOOTSTRAP + """
      window.OrreryDemoBootstrap={on:true,words:[],identity:{users:[],hosts:['FixtureHost']}};
    """)
    evaluate("OrreryDemo.ready.then(()=>true)")
    assert evaluate(REOPEN)["task"] == "Review on FixtureHost"
    result = evaluate("""({mode:document.documentElement.dataset.demo,
      visible:spawnTask.__demoOverlay?.textContent})""")
    assert result["mode"] == "on"
    assert "Review on" in result["visible"] and "FixtureHost" not in result["visible"]


def test_only_successfully_ready_launch_clears_draft(tour_browser):
    _, evaluate = tour_browser
    evaluate(BOOTSTRAP)
    original = evaluate(FILL)
    failure = evaluate("""(async()=>{
      await submitSpawn(new Event('submit'));
      return {status:spawnStatus.textContent,stored:localStorage.getItem(SPAWN_DRAFT_KEY)};
    })()""")
    assert "Fixture failure" in failure["status"] and failure["stored"]
    assert evaluate("spawnPayloadFromForm()") == original
    evaluate("""(async()=>{
      fixtureLaunchState='ready';
      await submitSpawn(new Event('submit'));
    })()""")
    assert evaluate("localStorage.getItem(SPAWN_DRAFT_KEY)") is None
    assert not evaluate("spawnOverlay.classList.contains('on')")


def test_codex_browser_preflight_reason_is_visible_from_the_first_spawn_status(tour_browser):
    _, evaluate = tour_browser
    evaluate(BOOTSTRAP)
    evaluate(FILL)
    result = evaluate("""(async()=>{
      const route=window.fetch,queries=[];
      window.fetch=(input,options)=>{
        if(!input.startsWith('/telemetry/spawn-status?'))return route(input,options);
        queries.push(input);
        return Promise.resolve(Response.json({ok:true,state:'failed',error:'The selected tools could not be applied.',
          detail:"child_resume: tools.browser for a Codex child needs the user's chrome-devtools MCP server in config.toml\\n"
            +"unrelated diagnostic must stay out of the modal"}));
      };
      spawnBrowserUse.click();
      const notice=spawnStatus.textContent;
      await submitSpawn(new Event('submit'));
      return {queries,notice,status:spawnStatus.textContent,open:spawnOverlay.classList.contains('on'),
        draft:localStorage.getItem(SPAWN_DRAFT_KEY)};
    })()""")
    assert result["queries"] == ["/telemetry/spawn-status?name=QuietCurie"]
    assert result["status"] == result["notice"]
    assert "chrome-devtools" in result["status"] and "config.toml" in result["status"]
    assert result["open"] and result["draft"]
