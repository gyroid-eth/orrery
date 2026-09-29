(async()=>{
  const waitFrame=()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  await document.fonts.ready;await waitFrame();
  localStorage.removeItem(THEME_AXIS_STORAGE_KEY);
  localStorage.removeItem(THEME_AXIS_HISTORY_STORAGE_KEY);
  if(activeThemeAxis())setThemeAxis(activeThemeAxis(),null);

  const capture=(axis,value)=>{
    const originalVerdict=themeAxisEffectVerdict;
    let effect=null,verdict=null,preReachedVisible=0;
    themeAxisEffectVerdict=current=>{
      effect=structuredClone(current);verdict=originalVerdict(current);
      const snapshot=themeAxisEffectSnapshots.get(axis)||[];
      preReachedVisible=snapshot.filter(record=>record.inViewport&&record.baseline===record.expected).length;
      return verdict;
    };
    let ok;
    try{ok=setThemeAxis(axis,value);}finally{themeAxisEffectVerdict=originalVerdict;}
    const stored=JSON.parse(localStorage.getItem(THEME_AXIS_STORAGE_KEY)||'null');
    return {axis,value,ok,effect,reason:verdict&&verdict.reason,
      preReachedVisible,active:activeThemeAxis(),stored};
  };
  const reset=()=>{if(activeThemeAxis())setThemeAxis(activeThemeAxis(),null);};
  const result={normal:[],zero:[],minimum:[],adversarial:{}};

  for(const axis of THEME_AXIS_IDS){
    for(const value of [.25,.5,.75,1]){
      reset();result.normal.push(capture(axis,value));
    }
  }
  reset();
  for(const axis of THEME_AXIS_IDS){result.zero.push(capture(axis,0));reset();}
  for(const axis of THEME_AXIS_IDS){result.minimum.push(capture(axis,Number.MIN_VALUE));reset();}

  /* The victim remains a generated token consumer. A later, higher
     specificity declaration may block the result, but cannot shrink the
     committed selector/channel membership or expected derivation. */
  const inventory=themeAxisStyleInventory();
  const tokenCandidates=themeAxisEffectCandidates('dim-contrast',inventory);
  const victim=tokenCandidates.find(record=>record.property==='color'&&record.element.matches('.brand .sub'))||
    tokenCandidates.find(record=>record.property==='color'&&themeAxisVisibility(record).inViewport);
  if(!victim)throw new Error('no visible dim-contrast token victim');
  const beforeMembership=themeAxisEffectSnapshot('dim-contrast',.5,inventory).length;
  const hadId=victim.element.hasAttribute('id'),oldId=victim.element.id;
  victim.element.id='theme-axis-important-victim';
  const important=document.createElement('style');important.dataset.themeAxisAdversarial='important';
  important.textContent='#theme-axis-important-victim{color:rgb(153,146,131)!important}';
  document.head.appendChild(important);
  const afterMembership=themeAxisEffectSnapshot('dim-contrast',.5,inventory).length;
  const partial=capture('dim-contrast',.5);
  important.remove();
  if(hadId)victim.element.id=oldId;else victim.element.removeAttribute('id');
  reset();
  result.adversarial.important={beforeMembership,afterMembership,...partial};

  const hidden=document.createElement('style');hidden.dataset.themeAxisAdversarial='hidden';
  hidden.textContent='body>*{visibility:hidden!important}';document.head.appendChild(hidden);
  result.adversarial.hidden=capture('small-text',.5);hidden.remove();reset();

  const offscreen=document.createElement('style');offscreen.dataset.themeAxisAdversarial='offscreen';
  offscreen.textContent='body>*{transform:translate(-20000px,-20000px)!important}';document.head.appendChild(offscreen);
  result.adversarial.offscreen=capture('tracking',.5);offscreen.remove();reset();

  result.final={active:activeThemeAxis(),runtimeStyle:!!document.getElementById(THEME_AXIS_RUNTIME_STYLE_ID)};
  return result;
})()
