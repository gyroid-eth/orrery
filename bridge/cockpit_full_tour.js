/* Selected Full tour steps. The checklist presentation belongs to OrreryTour. */
(function(root){
'use strict';
const STEPS=Object.freeze([
  {id:'full-start',title:'Start an agent',target:'#newAgentBtn',copy:'Start an agent in your workshop folder with a signed-in CLI. Give it a simple task and wait until it is ready.'},
  {id:'full-choose',title:'Choose your agent',target:'.col.roster',copy:'Choose your agent on the left. Its terminal opens in the center, and Agent Mail follows it.'},
  {id:'full-talk',title:'Send a prompt',target:'.promptbar',copy:'Say hello in the input below the terminal and press Enter or SEND. Use Shift+Enter for another line.'},
  {id:'full-shiritori',title:'Delegate a game of shiritori',target:'#mail',copy:'Copy the workshop prompt below and send it to your parent agent to create one child with /delegate and play over ORRERY Mail. This step checks off after the first numbered round appears in both directions; let all three rounds finish.'},
  {id:'full-split',title:'Work side by side',target:'.col.roster',copy:'Modifier-click your parent and child in the agent list to show both terminals together. Use ⌘click on macOS or Ctrl+click on WSL.'},
  {id:'full-drag',title:'Move a pane',target:'.tabstrip',copy:'Drag a pane tab or split label to move it, or move a floating pane by its header. You can arrange the workspace around your task.'},
  {id:'full-planetarium',title:'Open Planetarium',target:'#planetariumBtn',copy:'Open PLANETARIUM to see who spawned whom. Find the parent and child from your game, then close the view.'},
  {id:'full-usage',title:'Read what is left',target:'#usageBtn',copy:'Open LEFT to see the remaining account allowance and when its windows reset. A stale or unavailable reading is labelled rather than shown as a current value.',manual:'I’ve seen it'},
  {id:'full-telemetry',title:'Open Telemetry',target:'#networkBtn',copy:'Open TELEMETRY for the whole crew’s status and history. Cockpit is where you work with agents; Telemetry is where you observe and manage them.'},
  {id:'full-exit',title:'Exit from Deck',target:'#networkOverlay',copy:'On Deck, use EXIT on the shiritori child after the game has finished, then confirm. EXIT asks it to finish gracefully; your parent stays available.'},
  {id:'full-edge',title:'Read a Network edge',target:'#networkOverlay',copy:'Switch to Network and click the message count on the edge between your parent and child. Read the game’s Mail thread in the drawer.'},
  {id:'full-select',title:'Select several agents',target:'#networkOverlay',copy:'Turn on Select and click both agents, or drag a rectangle around them. The selection bar shows actions for the selected crew.'},
  {id:'full-replay',title:'Replay the collaboration',target:'#networkOverlay',copy:'Choose Replay to watch the selected agents’ history. Try play, pause or seeking, then close Replay before continuing.'},
  {id:'full-resume',title:'Resume the child',target:'#networkOverlay',copy:'Open the exited child’s details and use RESUME when it is available. After returning to Cockpit, reopen TELEMETRY to continue; an already-running agent does not count as a resume.'},
  {id:'full-network-settings',title:'Adjust the Network',target:'#networkOverlay',copy:'In Network, open SETTINGS and change a network slider such as Node size or Link distance. Watch the graph update before closing Settings.'},
  {id:'full-return',title:'Return to your agent',target:'#networkOverlay',copy:'Select a running agent in Telemetry and choose OPEN IN COCKPIT. Its terminal becomes your workspace again.'},
]);
const SHIRITORI_PROMPT="/delegate Start exactly one child agent, then play Japanese shiritori with it over ORRERY Mail (send_message), three turns each: exactly three round trips.\n\nRead and follow the installed ORRERY delegate skill. Use /delegate to create the child and ORRERY Mail (send_message) for every ready message and game move. Do not use Claude Code's built-in Agent or SendMessage tools. Include these same tool requirements in the child's embedded task. Use an available authenticated CLI: prefer a child from the other provider if available; otherwise use this provider. For a Claude child select Sonnet, never Haiku. Do not use --worktree for a Codex child. Keep the current working directory and existing ORRERY project identity. No native subagent tool, simulated dialogue, recursive delegation, game-output file edits, purchases, or external posting. Temporary task files required by the delegate skill are allowed.\n\nPut the complete rules in the child's embedded task. Its first action must send me ORRERY Mail with subject \"shiritori ready\" and body \"ready\", then wait through the documented Mail mechanism. Use the server-assigned names, not invented identities. If launch or Mail fails, report the exact failure and stop.\n\nRules: use common Japanese words in hiragana. Each word starts with the last hiragana character of the previous word. No repeated words; no word ending in ん. Match the exact ending character, including voicing; avoid small kana and long-vowel marks. Include romaji and a short English meaning so an English-speaking audience can follow.\n\nI am the parent player. My first word is りんご (ringo, apple). Send it to the child as \"shiritori round 1\". The child replies with a valid word; I validate it and send my next word for round 2; then repeat for round 3. This is six words total: parent/child, parent/child, parent/child. The ready message is not a word move. The child waits for actual messages and replies only once per numbered round. Permit one corrected reply if a move is invalid; report a failed game if it remains invalid.\n\nAt the end show a six-row table: round, sender, hiragana, romaji, meaning, and observed Mail ID when available. Check the chain and repetition explicitly. Distinguish actual messages from missing evidence; do not invent IDs. Tell the human which child was created and that cockpit EXIT is the cleanup action after accepting the result. Finish after three round trips, with no new game.";
const TELEMETRY_ACTIONS=Object.freeze({exit:'full-exit',edge:'full-edge',select:'full-select',
  replay:'full-replay',resume:'full-resume',settings:'full-network-settings',return:'full-return'});

function telemetryAction(event,origin,frame){
  const data=event&&event.data;
  if(!frame||!event||event.origin!==origin||event.source!==frame||!data||
     data.type!=='orrery-tour-action'||data.version!==1||typeof data.action!=='string')return null;
  return Object.prototype.hasOwnProperty.call(TELEMETRY_ACTIONS,data.action)
    ?TELEMETRY_ACTIONS[data.action]:null;
}

// A ready message is not a game move; old rounds and unrelated peers do not count.
function createShiritoriTracker(parent,since){
  const rounds=new Map(),seen=new Set();
  return {
    add(messages,agents){
      const children=new Set((Array.isArray(agents)?agents:[]).filter(a=>a&&a.parent===parent).map(a=>a.name));
      for(const m of Array.isArray(messages)?messages:[]){
        if(!m||m.id==null||seen.has(String(m.id)))continue;
        const rawTime=m.ts_unix??m.ts??m.created_ts??m.timestamp;
        const ts=typeof rawTime==='number'?rawTime*1000:Date.parse(rawTime);
        if(!Number.isFinite(ts)||ts<since||!/\bshiritori\b.*\bround\s*1\b/i.test(String(m.subject||'')))continue;
        const sender=String(m.sender||'');
        const recipients=(Array.isArray(m.recipients)?m.recipients:[]).filter(Boolean).map(r=>typeof r==='string'?r:r.name??r.recipient);
        if(m.recipient)recipients.push(m.recipient);
        let child=null,direction=null;
        if(sender===parent){child=recipients.find(r=>children.has(r));direction='out';}
        else if(children.has(sender)&&recipients.includes(parent)){child=sender;direction='in';}
        if(!child)continue;
        seen.add(String(m.id));
        const pair=rounds.get(child)||{};pair[direction]=String(m.id);rounds.set(child,pair);
      }
      return [...rounds.values()].some(pair=>pair.out&&pair.in&&pair.out!==pair.in);
    },
  };
}

const API={STEPS,SHIRITORI_PROMPT,TELEMETRY_ACTIONS,telemetryAction,createShiritoriTracker};
if(typeof module!=='undefined'&&module.exports)module.exports=API;
root.OrreryFullTour=API;
})(typeof window==='undefined'?globalThis:window);
