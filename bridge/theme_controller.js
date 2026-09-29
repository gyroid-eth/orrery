(function(){
  'use strict';
  const core=window.OrreryThemeCore;
  if(!core)return;

  const STORAGE_KEY='orrery.color-theme.v1';
  const PREFERENCES=new Set(['dark','light','system']);
  const root=document.documentElement;
  const media=window.matchMedia('(prefers-color-scheme: light)');
  const theme=core.deriveWarmPaperLightTheme();
  const controlledProperties=Object.keys(theme.cssVariables);
  let preference='dark';
  try{
    const stored=localStorage.getItem(STORAGE_KEY);
    if(PREFERENCES.has(stored))preference=stored;
  }catch(_){/* dark remains the safe, pixel-identical default */}

  function resolved(){return preference==='system'?(media.matches?'light':'dark'):preference;}
  function clearLightProperties(){
    controlledProperties.forEach(property=>root.style.removeProperty(property));
    root.removeAttribute('data-color-theme');
  }
  function notifyNativeShell(mode){
    const invoke=window.__TAURI__?.core?.invoke;
    if(typeof invoke!=='function')return;
    invoke('set_native_color_theme',{preference,resolved:mode}).catch(error=>{
      console.warn('failed to apply native color theme',error);
    });
  }
  function notifyTelemetry(mode){
    const frame=document.getElementById('networkFrame');
    if(!frame?.contentWindow)return;
    frame.contentWindow.postMessage({
      type:'orrery-color-theme',version:1,preference,resolved:mode,
      themeId:mode==='light'?theme.id:'dark',
      /* Sent rather than re-derived on the far side: the embedded dashboard is
         a different codebase, and a second copy of this palette would be free
         to drift from the one the cockpit is painting itself with. */
      variables:mode==='light'?theme.cssVariables:null,
    },location.origin);
  }
  function handleTelemetryMessage(event){
    const frame=document.getElementById('networkFrame');
    if(!frame?.contentWindow||event.source!==frame.contentWindow||event.origin!==location.origin)return;
    const data=event.data;
    if(data?.type==='orrery-color-theme-ready'&&data.version===1){
      notifyTelemetry(resolved());
      return;
    }
    if(data?.type==='orrery-color-theme-result'&&data.version===1){
      window.dispatchEvent(new CustomEvent('orrery-color-theme-telemetry-result',{detail:data}));
    }
  }
  function apply({announce=true}={}){
    const mode=resolved();
    clearLightProperties();
    if(mode==='light'){
      Object.entries(theme.cssVariables).forEach(([property,value])=>root.style.setProperty(property,value));
      root.dataset.colorTheme='light';
    }
    root.dataset.colorThemePreference=preference;
    const control=document.getElementById('colorThemePreference');
    if(control&&control.value!==preference)control.value=preference;
    const status=document.getElementById('colorThemeStatus');
    if(status)status.textContent=preference==='system'?`currently ${mode}`:`${mode} · warm paper`;
    const detail=Object.freeze({preference,resolved:mode,theme:mode==='light'?theme:null});
    notifyNativeShell(mode);
    notifyTelemetry(mode);
    if(announce)window.dispatchEvent(new CustomEvent('orrery-color-theme-change',{detail}));
    return detail;
  }
  function setPreference(value){
    if(!PREFERENCES.has(value))throw new TypeError(`unknown color theme preference: ${value}`);
    preference=value;
    try{localStorage.setItem(STORAGE_KEY,value);}catch(_){/* preference remains live for this page */}
    return apply();
  }
  function bindControl(){
    const control=document.getElementById('colorThemePreference');
    if(!control)return;
    control.value=preference;
    control.addEventListener('change',()=>setPreference(control.value));
    document.getElementById('networkFrame')?.addEventListener('load',()=>notifyTelemetry(resolved()));
    apply({announce:false});
  }
  media.addEventListener?.('change',()=>{if(preference==='system')apply();});
  window.addEventListener('message',handleTelemetryMessage);
  window.OrreryColorTheme=Object.freeze({
    get preference(){return preference;},get resolved(){return resolved();},
    get lightTheme(){return theme;},setPreference,apply,
  });
  apply({announce:false});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bindControl,{once:true});
  else bindControl();
})();
