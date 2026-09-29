(async()=>{
  const clone=value=>JSON.parse(JSON.stringify(value));
  const values=(small=null,tracking=null)=>({
    'dim-contrast':null,'small-text':small,tracking,glow:null,background:null,
  });
  const waitFor=(predicate,timeout=7000)=>new Promise((resolve,reject)=>{
    const started=performance.now();
    const poll=()=>{
      if(predicate())return resolve();
      if(performance.now()-started>timeout)return reject(new Error('iframe fixture wait timed out'));
      setTimeout(poll,10);
    };poll();
  });
  const frame=networkFrame,ready={axis:0,profile:0,exact:true};
  const readyListener=event=>{
    if(event.data&&/agentstack-theme-(?:axis|profile)-ready/.test(event.data.type)){
      ready.exact&&=event.source===frame.contentWindow&&event.origin===location.origin&&
        event.data.version===1&&event.data.surface==='telemetry';
      if(event.data.type==='agentstack-theme-axis-ready')ready.axis+=1;
      if(event.data.type==='agentstack-theme-profile-ready')ready.profile+=1;
    }
  };
  addEventListener('message',readyListener);
  frame.src='/network/?embed=1&theme-profile-fixture=1';
  await waitFor(()=>ready.profile>0&&frame.contentWindow.__themeProfileReceiverFixture);
  const receiverValues=()=>frame.contentWindow.__themeProfileReceiverFixture.state;
  const control=options=>frame.contentWindow.postMessage({
    type:'theme-profile-fixture-control',...options,
  },location.origin);
  const fakeClock=()=>{
    const handles=[];
    return {handles,clock:{schedule(callback,delay){const handle={callback,delay,cancelled:false};handles.push(handle);return handle;},
      cancel(handle){if(handle)handle.cancelled=true;}}};
  };

  try{
    const successAccepted=await setThemeProfile(values(.25,.25));
    const success={accepted:successAccepted,readyExact:ready.exact,
      receiver:clone(receiverValues()),cockpit:clone(themeAxisCommittedState.values),
      axes:[...telemetryThemeAxisReports.keys()].sort()};

    const unitBefore=clone(themeAxisCommittedState.values);
    control({unitMismatchNext:true});
    const unitAccepted=await setThemeProfile(values(.5,.5));
    const unitMismatch={accepted:unitAccepted,reason:themeProfileLastTelemetryOutcome.reason,
      receiverRolledBack:themeAxisValuesEqual(receiverValues(),unitBefore),
      cockpitRolledBack:themeAxisValuesEqual(themeAxisCommittedState.values,unitBefore),
      recoveryIdle:themeProfileRecovery===null};

    const handlerErrors=[];
    const protocolListener=event=>handlerErrors.push(event.detail);
    document.addEventListener('oc:theme-profile-error',protocolListener);
    let cancelThrows=1;
    const handlerHandles=[];
    const handlerClock={schedule(callback,delay){const handle={callback,delay};handlerHandles.push(handle);return handle;},
      cancel(){if(cancelThrows-->0)throw new TypeError('iframe fixture cancel failure');}};
    const handlerBefore=clone(themeAxisCommittedState.values);
    const handlerStarted=performance.now();
    const handlerAccepted=await setThemeProfile(values(.5,.75),{clock:handlerClock});
    document.removeEventListener('oc:theme-profile-error',protocolListener);
    const handlerError={accepted:handlerAccepted,reason:themeProfileLastTelemetryOutcome.reason,
      observable:handlerErrors.some(error=>error.reason==='telemetry-profile-handler-error'),
      receiverRolledBack:themeAxisValuesEqual(receiverValues(),handlerBefore),
      cockpitRolledBack:themeAxisValuesEqual(themeAxisCommittedState.values,handlerBefore),
      elapsedMs:performance.now()-handlerStarted,
      timedOut:performance.now()-handlerStarted>=THEME_PROFILE_ACK_TIMEOUT_MS};

    const replyBefore=clone(themeAxisCommittedState.values),replyClock=fakeClock();
    control({dropReplies:1});
    const replyPromise=setThemeProfile(values(.75,.75),{clock:replyClock.clock});
    await waitFor(()=>replyClock.handles.length===1&&themeAxisValuesEqual(receiverValues(),values(.75,.75)));
    const appliedBeforeReplyLoss=true;replyClock.handles[0].callback();
    const replyAccepted=await replyPromise;
    const replyLoss={accepted:replyAccepted,appliedBeforeReplyLoss,
      receiverRolledBack:themeAxisValuesEqual(receiverValues(),replyBefore),
      cockpitRolledBack:themeAxisValuesEqual(themeAxisCommittedState.values,replyBefore),
      recoveryIdle:themeProfileRecovery===null};

    const recoveryBefore=clone(themeAxisCommittedState.values),recoveryClock=fakeClock();
    const profileReadyBefore=ready.profile;
    control({dropReplies:2});
    const recoveryPromise=setThemeProfile(values(1,.75),{clock:recoveryClock.clock});
    await waitFor(()=>recoveryClock.handles.length===1&&themeAxisValuesEqual(receiverValues(),values(1,.75)));
    recoveryClock.handles[0].callback();
    await waitFor(()=>recoveryClock.handles.length===2&&themeAxisValuesEqual(receiverValues(),recoveryBefore));
    recoveryClock.handles[1].callback();
    const recoveryAccepted=await recoveryPromise;
    await waitFor(()=>ready.profile>profileReadyBefore&&themeProfileRecovery===null);
    const recovery={accepted:recoveryAccepted,profileReadyObserved:ready.profile>profileReadyBefore,
      receiverRolledBack:themeAxisValuesEqual(receiverValues(),recoveryBefore),
      cockpitRolledBack:themeAxisValuesEqual(themeAxisCommittedState.values,recoveryBefore),
      controlsEnabled:themeAxisLevelButtons.every(button=>!button.disabled)};

    const lossBefore=clone(themeAxisCommittedState.values),lossClock=fakeClock();
    const lossReady={axis:ready.axis,profile:ready.profile};
    control({dropReplies:2,suppressProfileReady:1});
    const lossPromise=setThemeProfile(values(.75,1),{clock:lossClock.clock});
    await waitFor(()=>lossClock.handles.length===1&&themeAxisValuesEqual(receiverValues(),values(.75,1)));
    lossClock.handles[0].callback();
    await waitFor(()=>lossClock.handles.length===2&&themeAxisValuesEqual(receiverValues(),lossBefore));
    lossClock.handles[1].callback();await lossPromise;
    await waitFor(()=>themeProfileRecovery&&themeProfileRecovery.failed===true,8000);
    const readyLoss={axisReadyObserved:ready.axis>lossReady.axis,
      profileReadyNotSubstituted:ready.profile===lossReady.profile,
      observable:themeProfileLastProtocolError&&themeProfileLastProtocolError.reason==='recovery-failed',
      controlsDisabled:themeAxisLevelButtons.every(button=>button.disabled),
      persistentStatus:themeAbSince.dataset.status==='error'&&themeAbSince.textContent.includes('recovery failed'),
      receiverRolledBack:themeAxisValuesEqual(receiverValues(),lossBefore),
      cockpitRolledBack:themeAxisValuesEqual(themeAxisCommittedState.values,lossBefore)};

    return {success,unitMismatch,handlerError,replyLoss,recovery,readyLoss};
  }finally{
    removeEventListener('message',readyListener);
  }
})()
