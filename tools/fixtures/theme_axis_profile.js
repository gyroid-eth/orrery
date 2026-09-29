(async()=>{
  const clone=value=>JSON.parse(JSON.stringify(value));
  const values=(small=null,tracking=null)=>({
    'dim-contrast':null,'small-text':small,tracking,glow:null,background:null,
  });
  const originalPost=postThemeProfileToTelemetry;
  const originalReload=reloadTelemetryProfileReceiver;
  const sent=[];
  let telemetryValues=values(),mode='ack',dropRemaining=0,dropped=null,staleIgnored=null;
  let reloads=0;

  const axesFor=requested=>Object.fromEntries(THEME_AXIS_IDS
    .filter(axis=>requested[axis]!==null)
    .map(axis=>{
      const report=themeAxisReports.get(axis);
      return [axis,{status:'applied',source:clone(report.source),
        mutation:clone(report.mutation),effect:clone(report.effect)}];
    }));
  const resultFor=(requestId,requested,applied=requested)=>({
    type:'agentstack-theme-profile-result',version:1,requestId,surface:'telemetry',
    requested:clone(requested),applied:clone(applied),status:'applied',axes:axesFor(requested),
  });

  postThemeProfileToTelemetry=(requestId,requested)=>{
    const message={requestId,values:clone(requested)};sent.push(message);
    telemetryValues=clone(requested);
    if(mode==='drop'||mode==='drop-many'){
      dropped=message;
      if(mode==='drop')mode='ack';
      else if(--dropRemaining<=0)mode='ack';
      return true;
    }
    if(mode==='stale-then-ack'){
      mode='ack';queueMicrotask(()=>{
        staleIgnored=handleTelemetryThemeProfileResult(resultFor(`${requestId}-stale`,requested))===false;
        handleTelemetryThemeProfileResult(resultFor(requestId,requested));
      });
      return true;
    }
    queueMicrotask(()=>handleTelemetryThemeProfileResult(resultFor(requestId,requested)));
    return true;
  };
  reloadTelemetryProfileReceiver=()=>{reloads+=1;};

  const set=(small,tracking,options)=>setThemeProfile(values(small,tracking),options);
  const reset=()=>set(null,null);
  const sameMeasurement=(first,second)=>{
    if(JSON.stringify(first.membership)!==JSON.stringify(second.membership))return false;
    if(first.members.length!==second.members.length)return false;
    return first.members.every((member,index)=>JSON.stringify(member)===JSON.stringify(second.members[index]));
  };

  try{
    localStorage.removeItem(THEME_PROFILE_STORAGE_KEY);
    localStorage.removeItem(THEME_PROFILE_HISTORY_STORAGE_KEY);

    mode='stale-then-ack';
    const normalOk=await set(.25,.25);
    const normal={
      ok:normalOk,
      staleIgnored,
      values:clone(themeAxisCommittedState.values),
      stored:JSON.parse(localStorage.getItem(THEME_PROFILE_STORAGE_KEY)||'null'),
      header:themeAbCurrent.textContent,
      settingsHeader:settingsBtn.textContent,
      axes:[...telemetryThemeAxisReports.keys()].sort(),
    };

    const handlerErrors=[];
    const handlerListener=event=>handlerErrors.push(event.detail);
    document.addEventListener('oc:theme-profile-error',handlerListener);
    let cancelThrows=1;
    const handlerClockHandles=[];
    const handlerClock={
      schedule(callback,delay){const handle={callback,delay};handlerClockHandles.push(handle);return handle;},
      cancel(){if(cancelThrows-->0)throw new TypeError('fixture cancel receiver failure');},
    };
    const handlerBefore=clone(themeAxisCommittedState.values);
    const handlerStarted=performance.now();
    const handlerAccepted=await set(.5,.75,{clock:handlerClock});
    document.removeEventListener('oc:theme-profile-error',handlerListener);
    const handlerError={accepted:handlerAccepted,reason:themeProfileLastTelemetryOutcome.reason,
      observable:handlerErrors.some(error=>error.reason==='telemetry-profile-handler-error'),
      rolledBack:themeAxisValuesEqual(themeAxisCommittedState.values,handlerBefore)&&
        themeAxisValuesEqual(telemetryValues,handlerBefore),
      elapsedMs:performance.now()-handlerStarted,
      timeoutCallbacksRun:handlerClockHandles.some(handle=>handle.ran===true)};

    const levels=[.25,.5,.75,1],order=[];
    for(const small of levels)for(const tracking of levels){
      await reset();
      const smallFirst=await set(small,null);
      const smallFinal=await set(small,tracking);
      const first=clone(themeProfileLastCandidateMeasurement);

      await reset();
      const trackingFirst=await set(null,tracking);
      const trackingFinal=await set(small,tracking);
      const second=clone(themeProfileLastCandidateMeasurement);
      order.push({small,tracking,smallFirst,smallFinal,trackingFirst,trackingFinal,
        membershipEqual:JSON.stringify(first.membership)===JSON.stringify(second.membership),
        computedEqual:sameMeasurement(first,second),members:first.members.length});
    }

    const reference=order.find(record=>record.small===.5&&record.tracking===.5);
    await reset();await set(null,.5);
    const negativeAccepted=await set(.5,.5,{localOptions:{negativeTrackingBaseline:true}});
    const negative=clone(themeProfileLastCandidateMeasurement);
    await reset();await set(.5,.5);
    const correct=clone(themeProfileLastCandidateMeasurement);
    const negativeControl={accepted:negativeAccepted,
      comparatorDetected:!sameMeasurement(negative,correct),
      correctPairPassed:Boolean(reference&&reference.computedEqual),
      reason:negative.reason};

    await reset();await set(.5,.25);
    const previousMeasurement=clone(themeProfileLastCandidateMeasurement);
    const before={
      values:clone(themeAxisCommittedState.values),
      storage:localStorage.getItem(THEME_PROFILE_STORAGE_KEY),
      history:localStorage.getItem(THEME_PROFILE_HISTORY_STORAGE_KEY),
      header:themeAbCurrent.textContent,settingsHeader:settingsBtn.textContent,
      members:previousMeasurement.members,
    };
    const scheduled=[];
    const clock={
      schedule(callback,delay){const handle={callback,delay,cancelled:false};scheduled.push(handle);return handle;},
      cancel(handle){if(handle)handle.cancelled=true;},
    };
    mode='drop';
    const timeoutPromise=set(.75,.75,{clock});
    const candidateAppliedBeforeReplyLoss=themeAxisValuesEqual(telemetryValues,values(.75,.75));
    const candidateRequest=dropped&&dropped.requestId;
    scheduled[0].callback();
    const timeoutAccepted=await timeoutPromise;
    const afterMembers=themeProfileComputedMembers(themeAxisMutationSnapshots);
    const rollbackRequest=sent.find(message=>message.requestId!==candidateRequest&&
      message.requestId.includes('-rollback-')&&themeAxisValuesEqual(message.values,before.values));
    const lateAccepted=handleTelemetryThemeProfileResult(resultFor(candidateRequest,values(.75,.75)));
    const timeout={
      accepted:timeoutAccepted,
      candidateAppliedBeforeReplyLoss,
      rollbackFreshId:Boolean(rollbackRequest&&rollbackRequest.requestId!==candidateRequest),
      telemetryRolledBack:themeAxisValuesEqual(telemetryValues,before.values),
      cockpitRolledBack:themeAxisValuesEqual(themeAxisCommittedState.values,before.values)&&
        JSON.stringify(afterMembers)===JSON.stringify(before.members),
      storageUnchanged:localStorage.getItem(THEME_PROFILE_STORAGE_KEY)===before.storage,
      historyUnchanged:localStorage.getItem(THEME_PROFILE_HISTORY_STORAGE_KEY)===before.history,
      headerUnchanged:themeAbCurrent.textContent===before.header&&settingsBtn.textContent===before.settingsHeader,
      lateIgnored:lateAccepted===false&&themeAxisValuesEqual(themeAxisCommittedState.values,before.values),
      scheduledDelays:scheduled.map(item=>item.delay),
      recoveryIdle:themeProfilePending===null&&themeProfileRecovery===null,
    };

    const recoveryBefore=clone(themeAxisCommittedState.values);
    const recoveryClockHandles=[];
    const recoveryClock={
      schedule(callback,delay){const handle={callback,delay};recoveryClockHandles.push(handle);return handle;},
      cancel(){},
    };
    mode='drop-many';dropRemaining=2;
    const recoveryPromise=set(1,.75,{clock:recoveryClock});
    const recoveryCandidateApplied=themeAxisValuesEqual(telemetryValues,values(1,.75));
    recoveryClockHandles[0].callback();await Promise.resolve();
    recoveryClockHandles[1].callback();
    const recoveryAccepted=await recoveryPromise;
    const busyBeforeReady=themeProfileRecovery!==null&&themeAxisLevelButtons.every(button=>button.disabled);
    mode='ack';await acknowledgeTelemetryThemeProfileRecovery();
    const recovery={accepted:recoveryAccepted,recoveryCandidateApplied,
      reloads,recoveryCompleted:themeProfileRecovery===null&&themeProfilePending===null,
      busyBeforeReady,telemetryRolledBack:themeAxisValuesEqual(telemetryValues,recoveryBefore),
      controlsEnabled:themeAxisLevelButtons.every(button=>!button.disabled)};

    const readyErrors=[];
    const readyListener=event=>readyErrors.push(event.detail);
    document.addEventListener('oc:theme-profile-error',readyListener);
    const readyHandles=[];
    const readyClock={schedule(callback,delay){const handle={callback,delay};readyHandles.push(handle);return handle;},
      cancel(handle){if(handle)handle.cancelled=true;}};
    beginTelemetryThemeProfileRecovery(recoveryBefore,readyClock);
    const busyWithoutReady=themeAxisLevelButtons.every(button=>button.disabled);
    readyHandles[0].callback();
    const readyFailure={busyWithoutReady,
      observable:readyErrors.some(error=>error.reason==='recovery-failed'&&
        error.message==='telemetry-profile-ready-timeout'),
      bounded:readyHandles.length===1&&readyHandles[0].delay===THEME_PROFILE_READY_TIMEOUT_MS&&
        themeProfileRecovery.failed===true};
    mode='ack';await acknowledgeTelemetryThemeProfileRecovery();
    readyFailure.completedAfterReady=themeProfileRecovery===null&&themeAxisLevelButtons.every(button=>!button.disabled);
    document.removeEventListener('oc:theme-profile-error',readyListener);

    await reset();
    const aLevels=Object.fromEntries(THEME_PROFILE_AXES.map(axis=>[axis,
      document.querySelector(`[data-theme-axis-level="${axis}"][data-theme-axis-value="null"]`)
        .getAttribute('aria-pressed')]));
    return {normal,handlerError,order,negativeControl,timeout,recovery,readyFailure,aLevels,
      final:{values:clone(themeAxisCommittedState.values),pending:themeProfilePending!==null}};
  }finally{
    postThemeProfileToTelemetry=originalPost;
    reloadTelemetryProfileReceiver=originalReload;
  }
})()
