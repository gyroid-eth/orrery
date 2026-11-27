'use strict';
// The Windows side of the original cockpit's view-module contract.
//
// bridge/orrery_view.js (the right-rail graph and its full-screen
// planetarium) is loaded unchanged from the repository's bridge/. It reads the
// cockpit only through a frozen window.OC and two document events:
//   'oc:agents' {agents}    the live roster, every poll
//   'oc:mail'   {messages}  mail not announced before
// This file builds those from the Windows host's own state, which app.js
// announces as 'win:state' / 'win:mail' / 'win:select'. Nothing here knows
// how the graph is drawn; a newer orrery_view.js should keep working as long
// as that contract holds.
//
// What the Windows host does not have, it leaves empty: there is no spawn
// lineage (every agent is a root, so the graph is the singleton grid), and no
// telemetry dashboard (the planetarium's OPEN TELEMETRY button is hidden).
(function () {
  const win = window.OrreryWin;
  if (!win) return;

  const PROVIDER = {
    claude: {asset: 'anthropic', label: 'Claude', engine: 'Claude Code'},
    agy: {asset: 'google', label: 'Gemini', engine: 'Antigravity'},
  };
  // The cockpit's act_state words: 'work' spins the amber arc, 'ask' raises
  // the "someone is waiting on you" glyph.
  const ACT_STATE = {busy: 'work', starting: 'work', attention: 'ask'};

  let agents = [];
  const backlog = [];    // Mail seen so far, oldest first (≤100), for OC.mailBacklog().
  const seen = new Set();
  let primed = false;    // The first mail poll only fills the backlog: no comets for old mail.

  function folder(path) { return (path || '').split(/[\\/]/).filter(Boolean).pop() || ''; }

  function toAgent(agent) {
    const running = agent.status === 'running';
    const activity = running ? agent.activity : agent.status;
    const provider = PROVIDER[agent.program];
    return {
      name: agent.name,
      running,
      act_state: running ? (ACT_STATE[activity] || 'idle') : 'idle',
      program: provider ? provider.engine : agent.program,
      model: provider ? provider.engine : agent.program,
      // The planetarium prints a role under each name; the working folder
      // is what tells two Windows agents apart.
      annot: {role: folder(agent.cwd)},
      cwd: agent.cwd,
      windows: agent,
    };
  }

  function toMessage(m) {
    return {...m, recipients: (m.recipients || '').split(', ').filter(Boolean)};
  }

  function providerPresentation(agent) {
    const program = agent && agent.windows ? agent.windows.program : '';
    const provider = PROVIDER[program] || null;
    const text = provider ? provider.engine : String((agent && agent.program) || 'agent');
    return {
      provider: provider && {asset: provider.asset, label: provider.label},
      text, compactText: Array.from(text).slice(0, 2).join('').toUpperCase(), cls: '', local: false,
    };
  }

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

  window.OC = Object.freeze({
    esc,
    relTime: (ts) => ts,
    jumpToAgent: (name) => win.select(name),
    rootOf: (name) => name,
    providerPresentation,
    renderPeerAvatar: () => null,
    lineageHue: new Map(),
    lineageParent: new Map(),
    agents: () => agents,
    activeAgent: () => win.selected(),
    miniView: () => ({mode: 'orrery', depth: 2}),
    mailBacklog: () => backlog.slice(),
  });

  document.addEventListener('win:state', (event) => {
    agents = (event.detail.state.agents || []).map(toAgent);
    document.dispatchEvent(new CustomEvent('oc:agents', {detail: {agents}}));
  });

  document.addEventListener('win:mail', (event) => {
    // The API lists newest first; announce in the order they were sent.
    const fresh = [...(event.detail.messages || [])].reverse()
      .filter((m) => !seen.has(m.id)).map(toMessage);
    fresh.forEach((m) => { seen.add(m.id); backlog.push(m); });
    if (backlog.length > 100) backlog.splice(0, backlog.length - 100);
    if (primed && fresh.length) {
      document.dispatchEvent(new CustomEvent('oc:mail', {detail: {messages: fresh}}));
    }
    primed = true;
  });

  document.addEventListener('win:select', () => {
    document.dispatchEvent(new CustomEvent('oc:stage-agent'));
  });

  // Clicking a node in the graph: the cockpit narrows its mail to that agent.
  document.addEventListener('oc:filter-agent', (event) => {
    if (event.detail && event.detail.agent) win.filterMail(event.detail.agent);
  });

  // A header button names the planetarium, as the cockpit's does.
  const button = document.getElementById('planetarium-btn');
  if (button) {
    button.addEventListener('click', () => {
      if (window.OrreryRail) window.OrreryRail.openPlanetarium();
    });
  }
})();
