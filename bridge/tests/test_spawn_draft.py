import json
import time

import pytest

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


@pytest.mark.parametrize(("state", "legacy", "expected"), [
    ("off", False, "off"), ("view", False, "view"),
    (False, True, "off"), (True, True, "control"),
])
def test_catalog_refresh_preserves_screen_choice_independently_of_browser(tour_browser, state, legacy, expected):
    _, evaluate = tour_browser
    evaluate(BOOTSTRAP)
    result = evaluate("""(async()=>{
      const state=STATE,legacy=LEGACY,fetchFixture=window.fetch;
      const catalog={...CATALOG,computer_modes:['off','view','control'],
        browser_modes:{'claude-code':['off','temporary','personal']}};
      window.fetch=(input,options)=>new URL(input,location.href).pathname==='/telemetry/spawn-catalog'
        ?Promise.resolve(Response.json(catalog)):fetchFixture(input,options);
      writeSpawnDraft(JSON.stringify({task:'Fixture task',selection:{
        family:'claude',provider:'claude',model:'claude-fixture',harness:'claude-code',
        tools:[legacy?state:false,false],computerMode:legacy?null:state,browserMode:'temporary',
      }}));
      openSpawnModal();
      await loadSpawnCatalog();
      const before=spawnPayloadFromForm().tools;
      catalog.browser_modes={'claude-code':['off','personal']};
      await loadSpawnCatalog();
      const after=spawnPayloadFromForm().tools;
      catalog.computer_modes=['off','control'];
      await loadSpawnCatalog();
      return {before,after,narrowed:spawnPayloadFromForm().tools};
    })()""".replace("CATALOG", json.dumps(CATALOG)).replace("STATE", json.dumps(state))
                      .replace("LEGACY", json.dumps(legacy)))
    choice = {"off": None, "view": {"access": "read"}, "control": {"access": "operate"}}[expected]
    assert result["before"].get("screen") == result["after"].get("screen") == choice
    assert result["before"]["browser_mode"] == "temporary" and result["after"]["browser_mode"] == "off"
    assert result["narrowed"].get("screen") == (choice if expected == "control" else None)


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


@pytest.mark.parametrize(("verdict", "reopen"), [("timeout", True), ("ready", True), ("timeout", False)],
                         ids=["reopen-timeout", "reopen-ready", "tools-changed"])
def test_previous_launch_does_not_interrupt_the_next_draft(tour_browser, verdict, reopen):
    client, evaluate = tour_browser
    client.call("Emulation.setEmulatedMedia", features=[dict(name="prefers-reduced-motion", value="reduce")])
    evaluate(BOOTSTRAP)
    evaluate(FILL)
    result = evaluate("""(async()=>{
      const originalFetch=window.fetch,originalNow=Date.now;
      let replyStatus,offset=0;
      const requestStarted=new Promise(resolve=>{
        window.fetch=(input,options)=>{
          if(input==='/telemetry/spawn')return Promise.resolve(Response.json({
            ok:true,pending:true,child_name:'QuietCurie',verdict_deadline_seconds:170}));
          if(input.startsWith('/telemetry/spawn-status?')){
            return new Promise(reply=>{replyStatus=reply;resolve();});
          }
          return originalFetch(input,options);
        };
      });
      Date.now=()=>originalNow()+offset;
      const box=()=>{const {x,y}=spawnSubmit.getBoundingClientRect();return [x,y];};
      try{
        const completion=submitSpawn(new Event('submit'));
        await requestStarted;
        if(REOPEN_MODAL){closeSpawnModal();openSpawnModal();await loadSpawnCatalog();}
        else spawnBrowserUse.click();
        await new Promise(r=>setTimeout(r,160));
        const editable=!spawnTask.readOnly&&spawnSubmit.disabled;
        spawnTask.value='A different draft';
        spawnTask.dispatchEvent(new Event('input',{bubbles:true}));
        spawnNameButton.focus();
        const before=box(),draft=localStorage.getItem(SPAWN_DRAFT_KEY),focusBefore=document.activeElement.id;
        offset=170001;
        replyStatus(Response.json({ok:true,state:VERDICT==='ready'?'ready':'launching'}));
        await completion;
        return {editable,before,after:box(),status:spawnStatus.textContent,toast:toastEl.textContent,
          open:spawnOverlay.classList.contains('on'),focusBefore,focusAfter:document.activeElement.id,
          preserved:localStorage.getItem(SPAWN_DRAFT_KEY)===draft,canSubmit:!spawnSubmit.disabled};
      }finally{window.fetch=originalFetch;Date.now=originalNow;}
    })()""".replace("VERDICT", json.dumps(verdict)).replace("REOPEN_MODAL", json.dumps(reopen)))
    assert result["editable"] and result["open"]
    assert result["focusBefore"] == result["focusAfter"] == "spawnNameButton", result
    assert result["preserved"] and result["canSubmit"]
    assert result["before"] == result["after"]
    assert "No launch result" not in result["status"]
    if verdict == "timeout":
        assert "Previous launch (QuietCurie)" in result["toast"]
        assert "No launch result after 170s" in result["toast"]
    else:
        assert result["toast"] == ""


@pytest.mark.parametrize("width", [1600, 390])
def test_current_launch_error_wraps_below_the_button(tour_browser, width):
    client, evaluate = tour_browser
    client.call("Emulation.setDeviceMetricsOverride", width=width, height=844, deviceScaleFactor=1, mobile=False)
    client.call("Emulation.setEmulatedMedia", features=[dict(name="prefers-reduced-motion", value="reduce")])
    evaluate(BOOTSTRAP)
    evaluate(FILL)
    result = evaluate("""(async()=>{
      const originalFetch=window.fetch;
      window.fetch=(input,options)=>input.startsWith('/telemetry/spawn-status?')
        ?Promise.resolve(Response.json({ok:true,state:'failed',error:'The launcher reported a configuration problem. '.repeat(5)}))
        :originalFetch(input,options);
      const box=()=>{const {x,y,bottom}=spawnSubmit.getBoundingClientRect();return {x,y,bottom};};
      const before=box();
      await submitSpawn(new Event('submit'));
      const status=spawnStatus.getBoundingClientRect();
      return {before,after:box(),statusTop:status.top,statusHeight:status.height,status:spawnStatus.textContent};
    })()""")
    assert result["before"] == result["after"]
    assert result["statusTop"] >= result["after"]["bottom"]
    assert result["statusHeight"] > 20 and "configuration problem" in result["status"]
