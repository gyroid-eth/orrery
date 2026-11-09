/* Small roster annotation editor. Mail's registered task stays unchanged. */
(function(root){
  'use strict';
  const TASK_API=38;
  function effectiveTask(agent){
    const registered=Object.hasOwn(agent,'registered_task')?agent.registered_task:agent.task;
    return String(agent.annot?.task||registered||'').trim();
  }
  function taskTitle(agent){
    return agent.annot?.task?'Edited in cockpit · registered: '+(agent.registered_task||'—'):'';
  }
  function mount({container,getAgent,onSave,onOpen=()=>{},onError=()=>{},isSelecting=()=>false}){
    let editing=null,versionRequest=null;
    async function capability(){
      if(versionRequest)return versionRequest;
      versionRequest=(async()=>{
        const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),3000);
        try{
          const response=await fetch('/api/version',{cache:'no-store',signal:controller.signal});
          if(!response.ok)throw new Error('version unavailable');
          const version=await response.json();
          return {task:Number.isInteger(version.api)&&version.api>=TASK_API,
            available:!['global','fresh'].includes(version.runtime_mode)&&version.capabilities?.annotations!==false};
        }catch(_){versionRequest=null;return {task:false,available:true};}
        finally{clearTimeout(timer);}
      })();
      return versionRequest;
    }
    function close(focus=true){
      if(!editing||editing.saving)return;
      const {form,button}=editing;editing=null;form.remove();
      button.setAttribute('aria-expanded','false');
      if(focus&&button.isConnected)button.focus({preventScroll:true});
    }
    function reposition(){
      if(!editing)return;
      const tile=editing.button.closest('.agent');
      if(!tile?.isConnected||tile.parentElement!==container){editing.saving=false;close(false);return;}
      if(tile.nextElementSibling!==editing.form){
        const focused=editing.form.contains(document.activeElement)?document.activeElement:null;
        tile.after(editing.form);focused?.focus({preventScroll:true});
      }
      editing.form.hidden=tile.classList.contains('filtered-out');
    }
    async function save(state){
      if(editing!==state||state.saving)return;
      const agent=getAgent(state.name);if(!agent){close(false);return;}
      const payload={name:state.name,role:state.form.querySelector('.roster-edit-role').value.trim()};
      if(state.taskSupported)payload.task=state.form.querySelector('.roster-edit-task').value.trim();
      else{payload.emoji=agent.annot?.emoji||'';payload.group=agent.annot?.group||'';}
      state.saving=true;state.form.setAttribute('aria-busy','true');
      const controls=[...state.form.querySelectorAll('input,textarea,button')];
      controls.forEach(control=>{control.disabled=true;});
      const status=state.form.querySelector('.roster-edit-status');status.textContent='Saving…';
      try{
        const response=await fetch('/api/annotate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        const result=await response.json();
        if(!response.ok||result.ok!==true)throw new Error(result.error||'Could not save annotation');
        onSave(state.name,result.annot||null);
        state.saving=false;if(editing===state)close();
      }catch(error){
        if(editing===state){status.textContent=error.message;onError(error.message);}
      }finally{
        state.saving=false;state.form.removeAttribute('aria-busy');
        controls.forEach(control=>{control.disabled=false;});
      }
    }
    async function open(name,button){
      if(isSelecting()||editing?.saving)return;
      if(editing?.name===name){close();return;}
      button.disabled=true;
      const support=await capability();button.disabled=false;
      if(!button.isConnected||!getAgent(name)||isSelecting())return;
      if(!support.available){onError('Annotations are unavailable for this dashboard');return;}
      close(false);onOpen();
      const agent=getAgent(name),form=document.createElement('form');
      form.className='roster-edit';form.setAttribute('aria-label','Edit '+name);
      form.innerHTML='<label>Role<input class="roster-edit-role" maxlength="40" placeholder="Unassigned" autocomplete="off"></label>'+
        '<label class="roster-edit-task-field">Task<textarea class="roster-edit-task" maxlength="200" rows="2" title="Shift+Enter for a new line"></textarea></label>'+
        '<div class="roster-edit-hint">Empty clears override · Enter saves · Esc cancels</div>'+
        '<div class="roster-edit-actions"><button class="roster-edit-save" type="submit">Save</button><button class="roster-edit-cancel" type="button">Cancel</button></div>'+
        '<div class="roster-edit-status" role="status"></div>';
      const role=form.querySelector('.roster-edit-role'),task=form.querySelector('.roster-edit-task');
      role.value=agent.annot?.role||'';task.value=agent.annot?.task||'';
      task.placeholder=agent.registered_task||agent.task||'Use registered task';
      form.querySelector('.roster-edit-task-field').hidden=!support.task;
      const state={name,form,button,taskSupported:support.task,saving:false};editing=state;
      form.addEventListener('submit',event=>{event.preventDefault();save(state);});
      form.querySelector('.roster-edit-cancel').onclick=()=>close();
      form.addEventListener('keydown',event=>{
        event.stopPropagation();
        if(event.isComposing||event.keyCode===229)return;
        if(event.key==='Escape'){event.preventDefault();close();}
        else if(event.key==='Enter'&&!event.shiftKey&&event.target.matches('input,textarea')){event.preventDefault();save(state);}
      });
      button.setAttribute('aria-expanded','true');reposition();role.focus({preventScroll:true});
    }
    function bindTile(tile,name){
      const button=document.createElement('button');button.type='button';button.className='roster-edit-toggle';
      button.setAttribute('aria-label','Edit role and task for '+name);button.title='Edit role and task';
      button.setAttribute('aria-expanded','false');
      button.innerHTML='<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m10.5 2.5 3 3-8 8-4 1 1-4zM9 4l3 3"/></svg>';
      button.onclick=event=>{event.preventDefault();event.stopPropagation();open(name,button);};
      button.addEventListener('pointerdown',event=>event.stopPropagation());
      button.addEventListener('keydown',event=>event.stopPropagation());
      tile.querySelector('.crow1').appendChild(button);
    }
    return {bindTile,reposition,close,isEditing:name=>editing?.name===name};
  }
  root.OrreryRosterEdit=Object.freeze({mount,effectiveTask,taskTitle});
})(window);
