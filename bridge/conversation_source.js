/* Data boundary for the read-only conversation view. No terminal operations. */
(function(root){
  'use strict';
  const MESSAGES={
    claude_next_phase:'Claude Code history is planned for the next phase.',
    provider_unavailable:'Conversation history currently supports Codex.',
    history_unconfirmed:'This agent has no confirmed conversation binding yet.',
    agent_unavailable:'This agent is no longer available in the live roster.',
    history_changed:'The conversation changed. Reopen History to read the current session.',
    history_unreadable:'The bound conversation file cannot be read.',
    record_too_large:'A provider record exceeds the reader byte limit. Close and reopen History to resume from the latest messages.',
    history_unavailable:'The provider history is unavailable.',
    dashboard_unavailable:'The telemetry dashboard could not answer. Retry in a moment.',
    reference_expired:'This reference expired or its conversation changed. Reload History and select it again.',
    preview_path_denied:'This file is outside the permitted preview folders.',
    preview_type_denied:'This file type cannot be previewed safely.',
    preview_too_large:'This file exceeds the preview size or pixel limit.',
    preview_changed:'The file changed during this read. Select it again.',
    preview_unavailable:'This recorded reference cannot be previewed.',
  };
  class Source {
    constructor(fetcher=root.fetch.bind(root)){this.fetcher=fetcher;}
    async read(agent,{before=null,after=null,signal}={}){
      const query=new URLSearchParams({agent});
      if(before!==null)query.set('before',before);
      if(after!==null)query.set('after',after);
      const response=await this.fetcher('/telemetry/conversation?'+query,{cache:'no-store',signal});
      const payload=await response.json();
      if(!response.ok||payload.ok!==true){
        const error=new Error(MESSAGES[payload.error]||'Conversation history could not be loaded.');
        error.code=payload.error;throw error;
      }
      if(payload.agent!==agent||!Array.isArray(payload.events))throw new Error('Invalid conversation response.');
      return payload;
    }
    async reference(ref,{signal,reveal=false}={}){
      const options={cache:'no-store',signal};
      let url='/telemetry/conversation/preview?'+new URLSearchParams({ref});
      if(reveal){url='/telemetry/conversation/reveal';Object.assign(options,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ref})});}
      const response=await this.fetcher(url,options),payload=await response.json();
      if(!response.ok||payload.ok!==true){const error=new Error(MESSAGES[payload.error]||'Preview is unavailable.');error.code=payload.error;throw error;}
      return payload;
    }
  }
  root.OrreryConversationSource=Object.freeze({Source,MESSAGES});
  if(typeof module!=='undefined')module.exports={Source,MESSAGES};
})(typeof window==='undefined'?globalThis:window);
