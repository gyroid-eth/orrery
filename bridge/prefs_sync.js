/* Shared cockpit preferences.
 *
 * Every WebView has its own localStorage: the ORRERY.app window, each Chrome
 * tab, a Safari window. A setting changed in one of them (mini view, terminal
 * font, colour theme …) used to stay there, so the app and the browser drifted
 * apart and looked like different products. This script keeps a whitelist of
 * preference keys in the backend (~/.orrery/prefs.json) and mirrors them into
 * localStorage before any other script reads them, so the rest of the cockpit
 * keeps using localStorage as before.
 *
 *   load   : GET /telemetry/prefs (synchronous, same origin) → localStorage
 *   change : Storage.setItem / removeItem on a synced key → debounced PUT
 *   others : GET every few seconds; a key that changed elsewhere is written
 *            to localStorage and announced as `oc:prefs-changed` so the live
 *            appliers (mini view, theme, font) can pick it up without a reload
 *
 * Drafts, histories and caches are deliberately not synced: they are per
 * window by nature. The backend enforces the same whitelist.
 */
(function(){
  'use strict';
  var ENDPOINT='/telemetry/prefs';
  var POLL_MS=4000;
  var SYNC_RE=/^(oc-(term-|mini-|split-|pinned-)|orrery\.(color-theme|spawn-advanced)|agentstack\.theme-profile\.v1\.state$|agentdash\.(netparams|netctl|holdMs))/;
  var HISTORY_RE=/history/i;
  function synced(key){return typeof key==='string'&&SYNC_RE.test(key)&&!HISTORY_RE.test(key);}

  var store;
  try{store=window.localStorage;store.getItem('oc-prefs-probe');}catch(_){return;} /* storage blocked: nothing to sync */
  var rawSet=Storage.prototype.setItem,rawRemove=Storage.prototype.removeItem;
  var rev=null,pending={},flushTimer=null,applying=false;

  function request(method,body,sync,done){
    var xhr=new XMLHttpRequest();
    xhr.open(method,ENDPOINT,!sync);
    xhr.setRequestHeader('Accept','application/json');
    if(body!==undefined)xhr.setRequestHeader('Content-Type','application/json');
    xhr.onreadystatechange=function(){
      if(xhr.readyState!==4)return;
      var data=null;
      if(xhr.status>=200&&xhr.status<300){try{data=JSON.parse(xhr.responseText);}catch(_){data=null;}}
      if(done)done(data);
    };
    try{xhr.send(body===undefined?null:JSON.stringify(body));}catch(_){if(done)done(null);}
    return xhr;
  }

  function applyRemote(data,announce){
    if(!data||typeof data.prefs!=='object'||data.prefs===null)return;
    var changed=[];
    applying=true;
    try{
      Object.keys(data.prefs).forEach(function(key){
        if(!synced(key))return;
        var value=data.prefs[key];
        if(typeof value!=='string')return;
        if(store.getItem(key)!==value){rawSet.call(store,key,value);changed.push(key);}
      });
    }finally{applying=false;}
    rev=data.rev;
    if(announce&&changed.length){
      document.dispatchEvent(new CustomEvent('oc:prefs-changed',{detail:{keys:changed}}));
    }
  }

  function flush(){
    flushTimer=null;
    var batch=pending;pending={};
    var set={},remove=[];
    Object.keys(batch).forEach(function(key){
      if(batch[key]===null)remove.push(key);else set[key]=batch[key];
    });
    request('PUT',{set:set,remove:remove},false,function(data){if(data)rev=data.rev;});
  }
  function queue(key,value){
    if(applying||!synced(key))return;
    pending[key]=value;
    if(flushTimer)clearTimeout(flushTimer);
    flushTimer=setTimeout(flush,250);
  }

  Storage.prototype.setItem=function(key,value){
    rawSet.call(this,key,value);
    if(this===store)queue(key,String(value));
  };
  Storage.prototype.removeItem=function(key){
    rawRemove.call(this,key);
    if(this===store)queue(key,null);
  };

  /* Hydrate before the rest of the page runs. A synchronous same-origin GET
     of a few hundred bytes costs less than a frame; without it every reader
     would need to become asynchronous. */
  request('GET',undefined,true,function(data){applyRemote(data,false);});

  function poll(){
    if(document.hidden)return;
    request('GET',undefined,false,function(data){
      if(!data||data.rev===rev)return;
      applyRemote(data,true);
    });
  }
  setInterval(poll,POLL_MS);
  document.addEventListener('visibilitychange',function(){if(!document.hidden)poll();});
  window.OrreryPrefs=Object.freeze({synced:synced,get rev(){return rev;}});
})();
