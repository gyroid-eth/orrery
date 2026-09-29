"""Spawn Agent: the telemetry's catalog, folded (2026-09-28).

The dashboard's /api/spawn-names names each provider's less-used models in
``overflow_models``; the backend marks them and the cockpit puts them under a
closed "more models · N" fold, open only when the selected model is one of
them. Without the list every model is shown as before. The local
spawn_catalog.json only decorates what the telemetry sent: the telemetry's
models, default, overflow list, efforts and errors are never replaced.

Run from bridge/: ``python -m pytest tests/test_spawn_model_overflow.py``.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = Path(os.environ.get("ORRERY_BRIDGE_SOURCES", ROOT))
COCKPIT = SOURCES / "cockpit.html"

sys.path.insert(0, str(ROOT))

import orrery_backend as ob  # noqa: E402

MODELS = ["claude-sonnet-5", "claude-opus-5-5", "claude-haiku-4-5-20251001",
          "claude-fable-5-1", "claude-opus-5", "claude-fable-5", "claude-opus-4-8"]
OVERFLOW = ["claude-opus-5", "claude-fable-5", "claude-opus-4-8"]


def _remote(**extra):
    provider = {"id": "claude", "label": "Claude", "models": list(MODELS),
                "default_model": "claude-opus-5-5", **extra}
    return {"providers": [provider], "dirs": [], "names": [], "adjectives": []}


# --- backend: the catalog carries the fold ---------------------------------------


def test_the_catalog_marks_the_previous_models():
    out = ob.normalize_spawn_catalog(_remote(overflow_models=OVERFLOW + ["claude-opus-5-5", 3]))
    provider = out["providers"][0]
    assert provider["overflow_models"] == OVERFLOW          # default and junk dropped
    marked = [m["id"] for m in provider["models"] if m.get("overflow")]
    assert marked == OVERFLOW
    default = next(m for m in provider["models"] if m["id"] == "claude-opus-5-5")
    assert default == {"id": "claude-opus-5-5", "label": "claude-opus-5-5", "default": True}


def test_a_catalog_without_the_list_is_unchanged():
    out = ob.normalize_spawn_catalog(_remote())
    provider = out["providers"][0]
    assert "overflow_models" not in provider
    assert not any(m.get("overflow") for m in provider["models"])


# --- cockpit: the real renderModels over a small DOM stand-in -----------------------

BLOCKS = (
    r"function splitOverflowModels\(provider\)\{.*?\n\}\n",
    r"function renderModels\(\)\{.*?\n\}\n",
    r"function effortsForModel\(provider,model\)\{.*?\n\}\n",
    r"function renderEfforts\(p\)\{.*?\n\}\n",
)

HARNESS = r"""
class El{
  constructor(tag){this.tag=tag;this.children=[];this.className='';this.textContent='';
    this.hidden=false;this.open=false;this.title='';this.attrs={};this.listeners={};}
  set innerHTML(v){this.children=[];}
  appendChild(c){this.children.push(c);return c;}
  append(...cs){cs.forEach(c=>this.children.push(c));}
  addEventListener(t,f){this.listeners[t]=f;}
  setAttribute(k,v){this.attrs[k]=v;}
}
const document={createElement:t=>new El(t)};
const modelChoices=new El('div'),effortChoices=new El('div'),effortRow=new El('div'),effortCaption=new El('div');
function renderEffortCaption(){}
let selProvider='claude',selModel=null,selEffort=null,spawnCatalog;
function providerById(id){return spawnCatalog.providers.find(p=>p.id===id);}
function names(el){return el.children.filter(c=>c.tag==='label')
  .map(l=>l.children[0].value);}
function pick(id){selModel=id;renderEfforts(providerById(selProvider));return shape();}
function shape(){
  const fold=modelChoices.children.find(c=>c.tag==='details');
  return {current:names(modelChoices),
    fold:fold?{open:fold.open,summary:fold.children[0].textContent,models:names(fold.children[1])}:null,
    selected:selModel,effortShown:!effortRow.hidden,efforts:names(effortChoices),effort:selEffort,
    error:(modelChoices.children.find(c=>c.className==='model-error')||{}).textContent||null};
}
function render(catalog,selected=null){spawnCatalog=catalog;selModel=selected;renderModels();return shape();}
console.log(JSON.stringify(run()));
"""


def _run(body: str) -> dict:
    html = COCKPIT.read_text(encoding="utf-8")
    parts = []
    for pattern in BLOCKS:
        match = re.search(pattern, html, re.DOTALL)
        assert match, f"missing block in cockpit.html: {pattern}"
        parts.append(match.group(0))
    script = "\n".join([f"function run(){{\n{body}\n}}", *parts, HARNESS])
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _catalog(**extra) -> str:
    return json.dumps(ob.normalize_spawn_catalog(_remote(**extra)))


def test_previous_models_fold_closed_under_the_current_ones():
    r = _run(f"return render({_catalog(overflow_models=OVERFLOW)});")
    assert r["current"] == ["claude-sonnet-5", "claude-opus-5-5",
                            "claude-haiku-4-5-20251001", "claude-fable-5-1"]
    assert r["fold"] == {"open": False, "summary": "more models · 3", "models": OVERFLOW}
    assert r["selected"] == "claude-opus-5-5"


def test_without_the_list_every_model_is_shown_as_before():
    for extra in ({}, {"overflow_models": []}):
        r = _run(f"return render({_catalog(**extra)});")
        assert r["current"] == MODELS
        assert r["fold"] is None


def test_the_fold_is_open_when_the_selected_model_is_a_previous_one():
    r = _run(f"return render({_catalog(overflow_models=OVERFLOW)},'claude-fable-5');")
    assert r["fold"]["open"] is True
    assert r["selected"] == "claude-fable-5"


def test_the_list_alone_folds_even_without_the_backend_marks():
    """An older backend passes overflow_models through without marking models."""
    raw = {"providers": [{"id": "claude", "overflow_models": OVERFLOW,
                          "models": [{"id": m, "label": m, **({"default": True} if m == "claude-opus-5-5" else {})}
                                     for m in MODELS]}]}
    r = _run(f"return render({json.dumps(raw)});")
    assert r["fold"]["models"] == OVERFLOW


# --- the telemetry is authoritative; the local file only decorates -------------------

CODEX_TELEMETRY = {
    "id": "codex", "label": "Codex", "program": "codex-cli",
    "models": ["gpt-6-sol", "gpt-5.6-sol", "gpt-6-astra", "gpt-5.6-luna"],
    "default_model": "gpt-6-sol",
    "overflow_models": ["gpt-5.6-sol"],
    "efforts": ["low", "medium", "high"],
    "effort_default": "medium",
    "model_efforts": {"gpt-6-sol": ["low", "medium", "high", "xhigh"], "gpt-5.6-sol": ["low", "high"],
                      "gpt-6-astra": ["high", "max"], "gpt-5.6-luna": []},
    "model_effort_defaults": {"gpt-6-sol": "xhigh", "gpt-6-astra": "max"},
    "model_error": "",
}


def _merged(*providers, names=True):
    raw = {"providers": [dict(p) for p in providers], "dirs": [], "names": [], "adjectives": []}
    return json.loads(ob.merge_spawn_catalog(json.dumps(raw).encode("utf-8")))


def test_the_telemetrys_codex_catalog_survives_the_local_file():
    provider = _merged(CODEX_TELEMETRY)["providers"][0]
    assert [m["id"] for m in provider["models"]] == CODEX_TELEMETRY["models"]
    assert [m["id"] for m in provider["models"] if m.get("default")] == ["gpt-6-sol"]
    assert provider["default_model"] == "gpt-6-sol"
    assert provider["overflow_models"] == ["gpt-5.6-sol"]
    assert provider["efforts"] == ["low", "medium", "high"]
    assert provider["effort_default"] == "medium"
    assert provider["model_efforts"] == CODEX_TELEMETRY["model_efforts"]
    assert provider["model_effort_defaults"] == CODEX_TELEMETRY["model_effort_defaults"]
    assert provider["program"] == "codex-cli"
    # ...and the local file still names what it knows
    astra = next(m for m in provider["models"] if m["id"] == "gpt-6-astra")
    assert astra["label"] == "GPT-6 Astra" and astra["hint"]
    assert provider["label"] == "Codex · GPT"
    assert set(provider["effort_hints"]) <= {"low", "medium", "high", "xhigh", "max"}
    unknown = next(m for m in provider["models"] if m["id"] == "gpt-6-sol")
    assert unknown == {"id": "gpt-6-sol", "label": "gpt-6-sol", "default": True}


def test_the_local_file_adds_no_provider_and_fills_no_failed_list():
    claude = {"id": "claude", "models": ["claude-opus-5-5"], "default_model": "claude-opus-5-5"}
    broken = {"id": "codex", "models": [], "default_model": "",
              "model_error": "AGENTSTACK_CODEX_MODELS contains invalid model IDs"}
    out = _merged(claude, broken)
    assert [p["id"] for p in out["providers"]] == ["claude", "codex"]
    codex = out["providers"][1]
    assert codex["models"] == []
    assert codex["model_error"].startswith("AGENTSTACK_CODEX_MODELS")
    only_claude = _merged(claude)
    assert [p["id"] for p in only_claude["providers"]] == ["claude"]


def test_an_older_telemetry_shows_every_model_unfolded():
    old = {"id": "codex", "models": ["gpt-5.6-sol", "gpt-6-astra"], "default_model": "gpt-5.6-sol",
           "efforts": ["low", "high"], "effort_default": "high"}
    catalog = json.dumps(_merged(old))
    r = _run(f"selProvider='codex';return render({catalog});")
    assert r["current"] == ["gpt-5.6-sol", "gpt-6-astra"] and r["fold"] is None
    assert r["efforts"] == ["low", "high"] and r["effort"] == "high"


def test_codex_folds_and_follows_the_per_model_efforts():
    catalog = json.dumps(_merged(CODEX_TELEMETRY))
    r = _run(f"""selProvider='codex';const out={{first:render({catalog})}};
      out.astra=pick('gpt-6-astra');out.luna=pick('gpt-5.6-luna');
      out.older=render({catalog},'gpt-5.6-sol');return out;""")
    first = r["first"]
    assert first["current"] == ["gpt-6-sol", "gpt-6-astra", "gpt-5.6-luna"]
    assert first["fold"] == {"open": False, "summary": "more models · 1", "models": ["gpt-5.6-sol"]}
    assert first["selected"] == "gpt-6-sol"
    assert first["efforts"] == ["low", "medium", "high", "xhigh"] and first["effort"] == "xhigh"
    assert r["astra"]["efforts"] == ["high", "max"] and r["astra"]["effort"] == "max"
    # an empty per-model list: no effort row, no effort sent
    assert r["luna"]["effortShown"] is False and r["luna"]["effort"] is None
    assert r["older"]["fold"]["open"] is True
    assert r["older"]["efforts"] == ["low", "high"]


def test_a_configuration_error_is_shown_not_papered_over():
    broken = {"id": "codex", "models": [], "model_error": "AGENTSTACK_CODEX_MODELS contains invalid model IDs"}
    catalog = json.dumps(_merged(broken))
    r = _run(f"selProvider='codex';return render({catalog});")
    assert r["current"] == [] and r["fold"] is None
    assert r["error"] == "CONFIGURATION ERROR · AGENTSTACK_CODEX_MODELS contains invalid model IDs"


import pytest  # noqa: E402


@pytest.mark.parametrize("local", [None, "{not json", "{}", '{"providers": "x"}'])
def test_a_missing_or_broken_local_file_still_serves_the_normalized_telemetry(monkeypatch, tmp_path, local):
    """The local file only annotates; without it the telemetry must still
    arrive normalized (review of 04729de: the raw payload came back and the
    page rendered nameless radios, no selection and no fold)."""
    path = tmp_path / "spawn_catalog.json"
    if local is not None:
        path.write_text(local, encoding="utf-8")
    monkeypatch.setattr(ob, "SPAWN_CATALOG_PATH", path)
    provider = _merged(CODEX_TELEMETRY)["providers"][0]
    assert [m["id"] for m in provider["models"]] == CODEX_TELEMETRY["models"]
    assert all(m["label"] == m["id"] for m in provider["models"])       # no annotations
    assert provider["overflow_models"] == ["gpt-5.6-sol"]
    assert provider["model_efforts"] == CODEX_TELEMETRY["model_efforts"]
    catalog = json.dumps(_merged(CODEX_TELEMETRY))
    r = _run(f"selProvider='codex';return render({catalog});")
    assert r["current"] == ["gpt-6-sol", "gpt-6-astra", "gpt-5.6-luna"]
    assert r["selected"] == "gpt-6-sol"
    assert r["fold"] == {"open": False, "summary": "more models · 1", "models": ["gpt-5.6-sol"]}


def test_a_payload_that_is_not_a_catalog_is_passed_through():
    assert ob.merge_spawn_catalog(b"not json") == b"not json"
    assert ob.merge_spawn_catalog(b"[1,2]") == b"[1,2]"
