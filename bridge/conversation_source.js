/* Data boundary for the read-only conversation view. No terminal operations. */
(function(root){
  'use strict';
  const MESSAGES={
    claude_next_phase:'Claude history is unavailable through this protected fresh projection.',
    provider_unavailable:'This provider has no supported conversation reader.',
    dashboard_upgrade_required:'This dashboard supports Codex history only. Claude, dsh and Hermes need telemetry API 35 or later.',
    history_stale:'Previous conversation · this record predates the current launch. Its contents are hidden.',
    dsh_decoder_unavailable:'dsh is unsupported on this cockpit: install the pinned zstandard dependency.',
    history_format_unsupported:'This native history format is not supported.',
    history_pending:'The provider has not completed its conversation header yet.',
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
  const REASONS=Object.create(null);
  function reasons(codes,text){for(const code of codes.split(' '))REASONS[code]=text;}
  reasons('receipt_unavailable receipt_missing binding_missing','This launch has no saved history link; open a newly launched child to read its history.');
  reasons('awaiting_hook launch_transition','This child is still preparing its history link; leave it running and retry shortly.');
  reasons('hook_not_observed','Codex has not recorded this run; enable the ORRERY plugin, review its hooks in /hooks, then start a new Codex process.');
  reasons('receipt_predates_session','Previous conversation · this recording belongs to an earlier launch; open history for a newly launched child instead.');
  reasons('no_transcript native_session_missing','The provider has not saved a usable conversation yet; retry after its first message or use a newly launched child.');
  reasons('invalid_binding identity_mismatch id_mismatch session_mismatch launch_mismatch ambiguous_binding session_conflict unsupported_source','This recording cannot be matched safely to the selected child; open a newly launched child instead.');
  reasons('artifact_changed','The saved recording changed; close and reopen History or use a newly launched child if it remains unavailable.');
  reasons('invalid_receipt','This launch has an invalid saved history link; start a new child to create a verified recording.');
  reasons('history_unavailable','The saved conversation is unavailable; retry after startup or use a newly launched child.');
  reasons('registration_missing','This child is no longer registered; refresh the roster or open a newly launched child.');
  reasons('write_failed','The child could not save its history link; check that its recording folder is writable, then start a new child.');
  reasons('disabled','This provider has history recording disabled; enable its recording setting and start a new child.');
  reasons('protected_history_required fresh_history_provider_unavailable','This runtime cannot expose this provider history yet; use a supported Codex conversation until telemetry adds support.');
  function bindingMessage(payload){
    const own=(values,key)=>Object.prototype.hasOwnProperty.call(values,key)?values[key]:null;
    if(!['history_unconfirmed','history_stale'].includes(payload.error))return own(MESSAGES,payload.error)||'Conversation history could not be loaded.';
    return own(REASONS,payload.reason_code)||(payload.error==='history_stale'?REASONS.receipt_predates_session:
      'History has no verified recording for this launch; retry after startup or use a newly launched child.');
  }
  class Source {
    constructor(fetcher=root.fetch.bind(root)){this.fetcher=fetcher;}
    async read(agent,{before=null,after=null,signal,wait=0,reader=null}={}){
      const query=new URLSearchParams({agent});
      if(before!==null)query.set('before',before);
      if(after!==null)query.set('after',after);
      // The server holds a poll of an unchanged record for up to `wait` s.
      if(after!==null&&Number.isInteger(wait)&&wait>0){
        query.set('wait',String(Math.min(wait,25)));
        // This reader's id: its next held poll takes over this one's slot.
        if(typeof reader==='string'&&/^[A-Za-z0-9_-]{16,64}$/.test(reader))query.set('reader',reader);
      }
      const response=await this.fetcher('/telemetry/conversation?'+query,{cache:'no-store',signal});
      const payload=await response.json();
      if(!response.ok||payload.ok!==true){
        const error=new Error(bindingMessage(payload));
        error.code=payload.error;error.reasonCode=payload.reason_code;throw error;
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
  root.OrreryConversationSource=Object.freeze({Source,MESSAGES,REASONS,bindingMessage});
  if(typeof module!=='undefined')module.exports={Source,MESSAGES,REASONS,bindingMessage};
})(typeof window==='undefined'?globalThis:window);
