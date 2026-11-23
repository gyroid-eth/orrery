'use strict';
// ORRERY for Windows: roster, one live terminal per agent, recent mail.
// The host owns the terminals; this page only views them, so reloading it
// never stops an agent.

const $ = (id) => document.getElementById(id);
const ICONS = {claude: '/icons/anthropic.svg', agy: '/icons/google.svg'};
const LABELS = {claude: 'Claude Code', agy: 'Antigravity'};
const ACTIVITY = {
  idle: '待機中', busy: '作業中', attention: 'あなたの判断を待っています', starting: '起動中',
  stopped: '停止', exited: '終了',
};
const WAITING = {
  'not running': '起動していません', 'typing a notice': '通知を入力中', busy: '作業が終わるのを待っています',
  'needs you': 'あなたの判断が終わるのを待っています', starting: '起動を待っています',
  'you typed in this terminal': 'このターミナルに入力があったため、次の待機まで待っています',
  settling: 'まもなく通知します', 'wake limit reached': '1 時間に起こせる回数の上限に達しました',
};
const XTERM_THEME = {
  background: '#0b0d11', foreground: '#ece5d6', cursor: '#f2b65a', cursorAccent: '#0b0d11',
  selectionBackground: 'rgba(242,182,90,.28)',
  black: '#161a21', red: '#d9735f', green: '#83b06a', yellow: '#f2b65a', blue: '#6f9bd1',
  magenta: '#b58be0', cyan: '#5fb3a3', white: '#ece5d6', brightBlack: '#5f5c52',
  brightRed: '#e8907d', brightGreen: '#9cc883', brightYellow: '#f6c97f', brightBlue: '#8fb3e0',
  brightMagenta: '#c9a6ea', brightCyan: '#7fc8ba', brightWhite: '#fffaf0',
};

let state = {agents: []};
// ?agent=NAME opens that agent (links, screenshots); otherwise the last one viewed.
let selected = new URLSearchParams(location.search).get('agent')
  || localStorage.getItem('orrery-win.selected') || null;
const terminals = new Map();  // lower-case name -> {term, fit, ws, el, name}

async function api(method, path, body) {
  const response = await fetch(path, {
    method, headers: {'Content-Type': 'application/json', 'X-Orrery': '1'},
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  for (const child of children) if (child != null) node.append(child);
  return node;
}

// Roster -----------------------------------------------------------------

function renderRoster() {
  const list = $('agents');
  list.replaceChildren();
  $('empty').hidden = state.agents.length > 0;
  for (const agent of state.agents) {
    const status = el('span', {className: 'status'});
    if (agent.paused) status.append(el('span', {className: 'tag warn', textContent: 'PAUSED', title: '1 時間に起こせる回数の上限に達しました。時間が経つと再開します。'}));
    if (agent.queued) status.append(el('span', {className: 'tag', textContent: `✉ ${agent.queued}`,
      title: `配送待ち: ${WAITING[agent.waiting] || agent.waiting || '待機中になったら通知します'}`}));
    if (agent.unread) status.append(el('span', {className: 'badge', textContent: agent.unread, title: '未読メール'}));
    const state = agent.status === 'running' ? agent.activity : agent.status;
    status.append(el('span', {className: `dot ${state}`, title: ACTIVITY[state] || state}));
    const card = el('li', {className: 'card' + (same(agent.name, selected) ? ' selected' : '')},
      el('img', {className: 'icon', src: ICONS[agent.program], alt: ''}),
      el('span', {className: 'cname', textContent: agent.name}),
      status,
      el('span', {className: 'cmeta', textContent: `${LABELS[agent.program]} · ${agent.cwd}`, title: agent.cwd}));
    card.addEventListener('click', () => select(agent.name));
    list.append(card);
  }
}

function same(a, b) { return a != null && b != null && a.toLowerCase() === b.toLowerCase(); }
function current() { return state.agents.find((a) => same(a.name, selected)) || null; }

function renderStage() {
  const agent = current();
  $('stage-title').textContent = agent ? agent.name : '—';
  const state = agent && (agent.status === 'running' ? agent.activity : agent.status);
  $('stage-meta').textContent = agent ? `${LABELS[agent.program]} · ${ACTIVITY[state] || state} · ${agent.cwd}` : '';
  const running = agent && agent.status === 'running';
  $('btn-start').hidden = !agent || running;
  $('btn-resume').hidden = !agent || running;
  $('btn-stop').hidden = !running;
  $('btn-remove').hidden = !agent;
  for (const [key, view] of terminals) view.el.hidden = !same(key, selected);
  if (agent) attach(agent.name);
}

function select(name) {
  selected = name;
  localStorage.setItem('orrery-win.selected', name);
  renderRoster();
  renderStage();
  const view = terminals.get(name.toLowerCase());
  if (view) requestAnimationFrame(() => { fitView(view); view.term.focus(); });
}

// Terminals --------------------------------------------------------------

function attach(name) {
  const key = name.toLowerCase();
  if (terminals.has(key)) return terminals.get(key);
  const holder = el('div', {className: 'term'});
  $('terminals').append(holder);
  const term = new Terminal({
    fontFamily: "'IBM Plex Mono', Consolas, monospace", fontSize: 13, lineHeight: 1.0,
    cursorBlink: true, scrollback: 6000, theme: XTERM_THEME, allowProposedApi: true,
    // ConPTY reflows its own buffer on resize and repaints only what changed;
    // xterm.js must not reflow too, or the two screens disagree.
    windowsPty: {backend: 'conpty', buildNumber: state.windows_build || 22621},
  });
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.loadAddon(new WebLinksAddon.WebLinksAddon((event, uri) => window.open(uri, '_blank', 'noopener')));
  term.open(holder);
  const view = {name, term, fit, el: holder, ws: null, retry: 0};
  terminals.set(key, view);
  // Before the replay is drawn, anything xterm "types" is its own answers to
  // queries in old output; the live program must not receive those.
  term.onData((data) => { if (view.synced) send(view, {type: 'input', data}); });
  new ResizeObserver(() => { if (!holder.hidden) fitView(view); }).observe(holder);
  connect(view);
  return view;
}

// ConPTY's output is itself a drawing of its screen at its current size, so
// the replay is drawn at exactly that size first. Only then does this view
// fit its own box; the resize makes ConPTY repaint the screen to match.
function connect(view) {
  const ws = new WebSocket(`ws://${location.host}/ws/${encodeURIComponent(view.name)}`);
  view.ws = ws;
  view.synced = false;
  ws.onopen = () => { view.retry = 0; };
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type === 'hello') {
      view.term.reset();
      view.term.resize(message.cols, message.rows);
      if (!message.replay) sync(view);
    } else if (message.type === 'reset') view.term.reset();
    else if (message.type === 'output' && !view.synced) view.term.write(message.data, () => sync(view));
    else if (message.type === 'output') view.term.write(message.data);
    else if (message.type === 'exit') {
      view.term.write(`\r\n\x1b[2m[exited${message.exit_code == null ? '' : ' ' + message.exit_code}]\x1b[0m\r\n`);
      refresh();
    }
  };
  ws.onclose = () => {
    if (!terminals.has(view.name.toLowerCase()) || view.ws !== ws) return;
    view.retry = Math.min(view.retry + 1, 6);
    setTimeout(() => { if (terminals.get(view.name.toLowerCase()) === view) connect(view); }, 250 * 2 ** view.retry);
  };
}

function send(view, message) {
  if (view.ws && view.ws.readyState === WebSocket.OPEN) view.ws.send(JSON.stringify(message));
}

function sync(view) {
  if (view.synced) return;
  view.synced = true;
  fitView(view);
}

function fitView(view) {
  if (!view.synced || view.el.hidden) return;  // Until the replay is drawn, keep ConPTY's size.
  try { view.fit.fit(); } catch (_) { return; }
  sendSize(view);
}

function sendSize(view) {
  send(view, {type: 'resize', rows: view.term.rows, cols: view.term.cols});
}

function detach(name) {
  const key = name.toLowerCase();
  const view = terminals.get(key);
  if (!view) return;
  terminals.delete(key);
  if (view.ws) view.ws.close();
  view.term.dispose();
  view.el.remove();
}

function size() {
  const view = selected && terminals.get(selected.toLowerCase());
  return view ? {rows: view.term.rows, cols: view.term.cols} : {rows: 30, cols: 120};
}

// Mail -------------------------------------------------------------------

let lastMail = '';
async function refreshMail() {
  const {messages} = await api('GET', '/api/mail/recent?limit=50');
  const signature = messages.map((m) => m.id).join(',');
  if (signature === lastMail) return;
  lastMail = signature;
  const list = $('mail');
  list.replaceChildren();
  for (const m of [...messages].reverse()) {
    const route = el('div', {className: 'route'}, el('b', {textContent: m.sender}), ' → ', m.recipients);
    list.append(el('li', {className: `msg ${m.importance}`},
      el('time', {textContent: new Date(m.ts).toLocaleTimeString(), title: m.ts}),
      route,
      el('div', {className: 'subject', textContent: m.subject}),
      el('div', {className: 'body', textContent: m.body})));
  }
  if (!messages.length) list.append(el('li', {className: 'hint', textContent: 'まだメールはありません。'}));
}

// State ------------------------------------------------------------------

async function refresh() {
  try {
    state = await api('GET', '/api/state');
  } catch (error) {
    showNotice(`host に接続できません: ${error.message}`);
    return;
  }
  if (state.agy_hub === false) {
    showNotice('Antigravity に orrery-hub が登録されていません。', 'REGISTER', async () => {
      await api('POST', '/api/agy/register-hub');
      refresh();
    });
  } else {
    showNotice('');
  }
  if (selected && !current()) selected = null;
  if (!selected && state.agents.length) selected = state.agents[0].name;
  renderRoster();
  renderStage();
  refreshMail().catch(() => {});
}

function showNotice(text, label, action) {
  const box = $('notice');
  box.replaceChildren();
  box.hidden = !text;
  if (!text) return;
  box.append(el('span', {textContent: text}));
  if (label) {
    const button = el('button', {className: 'btn accent', textContent: label});
    button.addEventListener('click', () => action().catch((e) => alert(e.message)));
    box.append(button);
  }
}

// Actions ----------------------------------------------------------------

$('new-agent').addEventListener('click', () => {
  $('create-error').hidden = true;
  $('create').showModal();
});

$('create-form').addEventListener('submit', async (event) => {
  if (event.submitter && event.submitter.value === 'cancel') return;
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    await api('POST', '/api/agents', {
      name: form.get('name').trim(), program: form.get('program'), cwd: form.get('cwd').trim(),
      resume: form.get('resume') === 'on', start: true, ...size(),
    });
    $('create').close();
    event.target.reset();
    selected = form.get('name').trim();
    await refresh();
  } catch (error) {
    $('create-error').textContent = error.message;
    $('create-error').hidden = false;
  }
});

async function act(path, body) {
  try { await api('POST', path, body); } catch (error) { alert(error.message); }
  refresh();
}

$('btn-start').addEventListener('click', () => act(`/api/agents/${encodeURIComponent(selected)}/start`, {resume: false, ...size()}));
$('btn-resume').addEventListener('click', () => act(`/api/agents/${encodeURIComponent(selected)}/start`, {resume: true, ...size()}));
$('btn-stop').addEventListener('click', () => act(`/api/agents/${encodeURIComponent(selected)}/stop`));
$('btn-remove').addEventListener('click', async () => {
  const name = selected;
  if (!confirm(`${name} を roster から外します。動いていれば停止します。`)) return;
  try { await api('DELETE', `/api/agents/${encodeURIComponent(name)}`); } catch (error) { alert(error.message); }
  detach(name);
  selected = null;
  refresh();
});

refresh();
setInterval(refresh, 2000);
