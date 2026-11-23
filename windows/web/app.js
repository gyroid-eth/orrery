'use strict';
// ORRERY for Windows: roster, one live terminal per agent, a composer, and
// the agents' mail. The host owns the terminals; this page only views them,
// so reloading it never stops an agent.

const $ = (id) => document.getElementById(id);
const LABELS = {claude: 'Claude Code', agy: 'Antigravity'};
const ENGINE = {claude: 'CLAUDE', agy: 'ANTIGRAVITY'};
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

let state = {agents: [], portraits: []};
// ?agent=NAME opens that agent (links, screenshots); otherwise the last one viewed.
let selected = new URLSearchParams(location.search).get('agent')
  || localStorage.getItem('orrery-win.selected') || null;
let mailFilter = 'ALL';
let mailMessages = [];
const openMail = new Set();
const terminals = new Map();  // lower-case name -> view

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

function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  for (const child of children) if (child != null) node.append(child);
  return node;
}

function same(a, b) { return a != null && b != null && a.toLowerCase() === b.toLowerCase(); }
function current() { return state.agents.find((a) => same(a.name, selected)) || null; }
function agentNamed(name) { return state.agents.find((a) => same(a.name, name)) || null; }
function stateOf(agent) { return agent.status === 'running' ? agent.activity : agent.status; }

// A stable portrait per name, from the repository's public-domain set.
function portraitFor(name) {
  const list = state.portraits || [];
  if (!list.length || !agentNamed(name)) return null;
  let hash = 0;
  for (const ch of name.toLowerCase()) hash = (hash * 31 + ch.codePointAt(0)) >>> 0;
  return `/portraits/${encodeURIComponent(list[hash % list.length])}.png`;
}

function face(name, cls = 'face') {
  const src = portraitFor(name);
  if (src) return el('img', {className: cls, src, alt: '', title: name});
  return el('span', {className: `${cls} initial`, textContent: (name || '?')[0].toUpperCase(), title: name});
}

function ago(ts) {
  const seconds = Math.max(0, (Date.now() - new Date(ts).getTime()) / 1000);
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function folderName(path) { return (path || '').split(/[\\/]/).filter(Boolean).pop() || path; }

// Header -----------------------------------------------------------------

function renderSummary() {
  const counts = {busy: 0, idle: 0, attention: 0};
  for (const agent of state.agents) {
    const s = stateOf(agent);
    if (s in counts) counts[s] += 1;
  }
  const box = $('summary');
  box.replaceChildren();
  const part = (cls, n, label) => el('span', {}, el('span', {className: `dot ${cls}`}), el('b', {textContent: n}), ` ${label}`);
  box.append(part('busy', counts.busy, 'working'), ' · ', part('idle', counts.idle, 'waiting'));
  if (counts.attention) box.append(' · ', part('attention', counts.attention, 'need you'));
}

function tick() { $('clock').textContent = new Date().toLocaleTimeString([], {hour12: false}); }

// Roster -----------------------------------------------------------------

function renderRoster() {
  const list = $('agents');
  const query = $('filter').value.trim().toLowerCase();
  list.replaceChildren();
  $('empty').hidden = state.agents.length > 0;
  for (const agent of state.agents) {
    const haystack = `${agent.name} ${LABELS[agent.program]} ${agent.cwd}`.toLowerCase();
    if (query && !haystack.includes(query)) continue;
    const s = stateOf(agent);
    const badges = el('span', {className: 'badges'});
    if (agent.paused) badges.append(el('span', {className: 'tag warn', textContent: 'PAUSED', title: '1 時間に起こせる回数の上限に達しました。時間が経つと再開します。'}));
    if (agent.queued) badges.append(el('span', {className: 'tag', textContent: `✉ ${agent.queued}`,
      title: `配送待ち: ${WAITING[agent.waiting] || agent.waiting || '待機中になったら通知します'}`}));
    if (agent.unread) badges.append(el('span', {className: 'badge', textContent: agent.unread, title: '未読メール'}));
    const card = el('li', {className: `card${same(agent.name, selected) ? ' selected' : ''}${s === 'attention' ? ' attention' : ''}`},
      face(agent.name),
      el('span', {className: 'cname', textContent: agent.name}),
      el('span', {className: 'chips-row'},
        el('span', {className: `chip ${agent.program}`, textContent: ENGINE[agent.program]})),
      el('span', {className: 'chips-row'},
        el('span', {className: 'chip', textContent: folderName(agent.cwd), title: agent.cwd})),
      el('span', {className: 'line'}, el('span', {className: `dot ${s}`}),
        el('span', {className: 'text', textContent: ACTIVITY[s] || s})),
      badges);
    card.addEventListener('click', () => select(agent.name));
    list.append(card);
  }
}

function renderStage() {
  const agent = current();
  $('stage-title').textContent = agent ? agent.name : '—';
  $('stage-meta').textContent = agent ? `${LABELS[agent.program]} · ${ACTIVITY[stateOf(agent)] || stateOf(agent)} · ${agent.cwd}` : '';
  const running = agent && agent.status === 'running';
  $('btn-start').hidden = !agent || running;
  $('btn-resume').hidden = !agent || running;
  $('btn-stop').hidden = !running;
  $('btn-remove').hidden = !agent;
  $('composer').hidden = !running;
  if (agent) {
    const img = face(agent.name, 'face sm');
    $('composer-face').replaceWith(Object.assign(img, {id: 'composer-face'}));
    $('composer-name').textContent = agent.name;
  }
  for (const [key, view] of terminals) view.el.hidden = !same(key, selected);
  if (agent) attach(agent.name);
}

function select(name) {
  selected = name;
  localStorage.setItem('orrery-win.selected', name);
  renderRoster();
  renderStage();
  const view = terminals.get(name.toLowerCase());
  if (view) requestAnimationFrame(() => fitView(view));
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
  const view = {name, term, fit, el: holder, ws: null, retry: 0, synced: false};
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
  if (view && view.ws && view.ws.readyState === WebSocket.OPEN) {
    view.ws.send(JSON.stringify(message));
    return true;
  }
  return false;
}

function sync(view) {
  if (view.synced) return;
  view.synced = true;
  fitView(view);
}

function fitView(view) {
  if (!view.synced || view.el.hidden) return;  // Until the replay is drawn, keep ConPTY's size.
  try { view.fit.fit(); } catch (_) { return; }
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

// Composer ---------------------------------------------------------------

function currentView() { return selected ? terminals.get(selected.toLowerCase()) : null; }

$('composer').addEventListener('submit', (event) => {
  event.preventDefault();
  const text = $('prompt').value;
  if (!text.trim()) return;
  if (send(currentView(), {type: 'submit', text})) $('prompt').value = '';
});

$('prompt').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    $('composer').requestSubmit();
  } else if (event.key === 'Escape') {
    event.preventDefault();
    send(currentView(), {type: 'interrupt'});
  }
});

$('btn-interrupt').addEventListener('click', () => send(currentView(), {type: 'interrupt'}));

// Mail -------------------------------------------------------------------

let lastMail = '';
async function refreshMail() {
  const {messages} = await api('GET', '/api/mail/recent?limit=100');
  mailMessages = messages;
  const signature = messages.map((m) => m.id).join(',') + '|' + mailFilter + '|' + [...openMail].join(',');
  renderOrbit();
  if (signature === lastMail) return;
  lastMail = signature;
  renderChips();
  renderMail();
}

function participants() {
  const names = new Map();
  for (const agent of state.agents) names.set(agent.name.toLowerCase(), agent.name);
  for (const m of mailMessages) {
    for (const name of [m.sender, ...(m.recipients || '').split(', ')]) {
      if (name && !names.has(name.toLowerCase())) names.set(name.toLowerCase(), name);
    }
  }
  return [...names.values()];
}

function renderChips() {
  const box = $('chips');
  box.replaceChildren();
  for (const name of ['ALL', ...participants()]) {
    const button = el('button', {className: same(name, mailFilter) ? 'on' : '', textContent: name, type: 'button'});
    button.addEventListener('click', () => { mailFilter = name; refreshMail(); });
    box.append(button);
  }
}

function involves(m, name) {
  return same(m.sender, name) || (m.recipients || '').split(', ').some((r) => same(r, name));
}

function renderMail() {
  const list = $('mail');
  list.replaceChildren();
  const shown = mailMessages.filter((m) => mailFilter === 'ALL' || involves(m, mailFilter));
  $('mail-count').textContent = shown.length ? `${shown.length}` : '';
  for (const m of shown) {  // The API returns newest first.
    const item = el('li', {className: `msg ${m.importance}${openMail.has(m.id) ? ' open' : ''}`},
      el('div', {className: 'route'}, el('b', {textContent: m.sender}), ' → ', m.recipients,
        el('span', {className: 'imp', textContent: m.importance.toUpperCase()})),
      el('div', {className: 'subject', textContent: m.subject}),
      el('time', {textContent: ago(m.ts), title: m.ts}),
      el('div', {className: 'body', textContent: m.body}));
    item.addEventListener('click', () => {
      if (openMail.has(m.id)) openMail.delete(m.id); else openMail.add(m.id);
      item.classList.toggle('open');
    });
    list.append(item);
  }
  if (!shown.length) list.append(el('li', {className: 'hint', textContent: 'まだメールはありません。'}));
}

// Agents on an orbit; a line for each pair that has written, thicker for
// more messages and brighter for recent ones. Only agents on the roster get a
// node: mail outlives a removed agent, and its name should not linger here.
function renderOrbit() {
  const box = $('orbit');
  const names = state.agents.map((agent) => agent.name);
  const cx = 150, cy = 85, rx = 112, ry = 58;
  const nodes = new Map(names.map((name, i) => {
    const angle = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(names.length, 1);
    return [name.toLowerCase(), {name, x: cx + rx * Math.cos(angle), y: cy + ry * Math.sin(angle)}];
  }));
  const pairs = new Map();
  const now = Date.now();
  for (const m of mailMessages) {
    for (const r of (m.recipients || '').split(', ')) {
      if (!r) continue;
      const key = [m.sender.toLowerCase(), r.toLowerCase()].sort().join('|');
      const entry = pairs.get(key) || {count: 0, last: 0};
      entry.count += 1;
      entry.last = Math.max(entry.last, new Date(m.ts).getTime());
      pairs.set(key, entry);
    }
  }
  const parts = [svg('ellipse', {class: 'ring', cx, cy, rx, ry}),
    svg('ellipse', {class: 'ring', cx, cy, rx: rx * 0.55, ry: ry * 0.55})];
  for (const [key, {count, last}] of pairs) {
    const [a, b] = key.split('|').map((n) => nodes.get(n));
    if (!a || !b || a === b) continue;
    const fresh = Math.max(0.15, 1 - (now - last) / 600000);  // Fades over ten minutes.
    parts.push(svg('line', {class: 'edge', x1: a.x, y1: a.y, x2: b.x, y2: b.y,
      'stroke-width': Math.min(1 + count * 0.5, 4), 'stroke-opacity': fresh.toFixed(2)}));
  }
  names.forEach((name, i) => {
    const node = nodes.get(name.toLowerCase());
    const agent = agentNamed(name);
    const busy = agent && stateOf(agent) === 'busy' ? ' busy' : '';
    const id = `clip-${i}`;
    parts.push(svg('circle', {class: `node-ring${busy}`, cx: node.x, cy: node.y, r: 13}));
    const src = portraitFor(name);
    if (src) {
      parts.push(svg('clipPath', {id}, svg('circle', {cx: node.x, cy: node.y, r: 11.5})));
      parts.push(svg('image', {href: src, x: node.x - 11.5, y: node.y - 11.5, width: 23, height: 23,
        'clip-path': `url(#${id})`, style: 'filter:grayscale(1)'}));
    } else {
      parts.push(svg('text', {class: 'initial', x: node.x, y: node.y}, document.createTextNode(name[0].toUpperCase())));
    }
    parts.push(svg('text', {class: 'node-label', x: node.x, y: node.y + 23}, document.createTextNode(name)));
  });
  box.replaceChildren(...parts);
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
  renderSummary();
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

$('filter').addEventListener('input', renderRoster);

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

tick();
setInterval(tick, 1000);
refresh();
setInterval(refresh, 2000);
