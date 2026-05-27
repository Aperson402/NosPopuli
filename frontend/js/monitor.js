const AGENTS = [
  { id: 'router',        label: 'Router',        icon: '⇄' },
  { id: 'search',        label: 'Search',        icon: '⌕' },
  { id: 'orchestrator',  label: 'Orchestrator',  icon: '◈' },
  { id: 'bill_fetcher',  label: 'Bill Fetcher',  icon: '↓' },
  { id: 'translator',    label: 'Translator',    icon: '✦' },
  { id: 'historian',     label: 'Historian',     icon: '◷' },
  { id: 'vote_parser',   label: 'Vote Parser',   icon: '⊙' },
  { id: 'vote_fetcher',  label: 'Vote Fetcher',  icon: '⊕' },
  { id: 'vote_mapper',   label: 'Vote Mapper',   icon: '⊞' },
  { id: 'member_search', label: 'Member Search', icon: '◉' },
  { id: 'title_search',      label: 'Title Search',  icon: '⊛' },
  { id: 'dispatcher',        label: 'Dispatcher',    icon: '⇢' },
  { id: 'result_validator',  label: 'Validator',     icon: '✓' },
  { id: 'api',               label: 'API',           icon: '⊳' },
  { id: 'state_search',      label: 'State Search',  icon: '◎' },
  { id: 'state_fetcher',     label: 'State Fetcher', icon: '↓' },
  { id: 'state_member',      label: 'State Member',  icon: '◉' },
];

let seenCount = 0;
let paused = false;
let activeFilter = null;
let agentCounts = {};
let lastActivity = {};

// Build sidebar
const agentList = document.getElementById('agent-list');
AGENTS.forEach(agent => {
  const pill = document.createElement('div');
  pill.className = 'agent-pill';
  pill.id = `pill-${agent.id}`;
  pill.innerHTML = `
    <div class="agent-dot"></div>
    <div class="agent-name">${agent.label}</div>
    <div class="agent-count" id="cnt-${agent.id}">0</div>
  `;
  pill.onclick = () => filterAgent(agent.id);
  agentList.appendChild(pill);
});

// Build flow nodes
const flowNodes = document.getElementById('flow-nodes');
AGENTS.forEach((agent, i) => {
  const node = document.createElement('div');
  node.className = 'flow-node';
  node.id = `flow-${agent.id}`;
  node.innerHTML = `
    <div class="flow-node-icon">${agent.icon}</div>
    <div class="flow-node-name">${agent.label}</div>
    <div class="flow-node-time" id="ftime-${agent.id}"></div>
  `;
  flowNodes.appendChild(node);

  if (i < AGENTS.length - 1) {
    const arrow = document.createElement('div');
    arrow.className = 'flow-arrow';
    arrow.id = `farrow-${agent.id}`;
    arrow.textContent = '↓';
    flowNodes.appendChild(arrow);
  }
});

function filterAgent(agentId) {
  if (activeFilter === agentId) {
    activeFilter = null;
    document.querySelectorAll('.agent-pill').forEach(p => p.classList.remove('active'));
  } else {
    activeFilter = agentId;
    document.querySelectorAll('.agent-pill').forEach(p => p.classList.remove('active'));
    document.getElementById(`pill-${agentId}`)?.classList.add('active');
  }
  rebuildFeed();
}

let allEntries = [];

function rebuildFeed() {
  const feed = document.getElementById('feed');
  const empty = document.getElementById('empty-state');

  const filtered = activeFilter
    ? allEntries.filter(e => e.agent === activeFilter)
    : allEntries;

  feed.innerHTML = '';

  if (filtered.length === 0) {
    feed.appendChild(empty || createEmpty());
    return;
  }

  filtered.forEach(entry => {
    feed.appendChild(createEntryEl(entry));
  });
}

function createEntryEl(entry) {
  const agent = entry.agent || 'unknown';
  const colorClass = `c-${agent}`;
  const time = (entry.timestamp || '').slice(11, 19);

  const el = document.createElement('div');
  el.className = 'entry';

  const inputKeys = Object.entries(entry.input || {}).filter(([k,v]) => v !== null && v !== '' && JSON.stringify(v) !== '{}');
  const outputKeys = Object.entries(entry.output || {}).filter(([k,v]) => v !== null && v !== '' && JSON.stringify(v) !== '{}');

  el.innerHTML = `
    <div class="entry-header">
      <span class="entry-agent ${colorClass}">${agent}</span>
      <span class="entry-action">${entry.action || ''}</span>
      <span class="entry-time">${time}</span>
    </div>
    ${inputKeys.length || outputKeys.length ? `
      <div class="entry-data">
        ${inputKeys.slice(0,2).map(([k,v]) => `
          <div class="data-block">
            <div class="data-label">IN · ${k}</div>
            <div class="data-value">${String(v).slice(0,120)}</div>
          </div>
        `).join('')}
        ${outputKeys.slice(0,4).map(([k,v]) => `
          <div class="data-block">
            <div class="data-label">OUT · ${k}</div>
            <div class="data-value">${String(v).slice(0,120)}</div>
          </div>
        `).join('')}
      </div>
    ` : ''}
  `;

  return el;
}

function flashAgent(agentId) {
  const pill = document.getElementById(`pill-${agentId}`);
  const flowNode = document.getElementById(`flow-${agentId}`);
  const arrow = document.getElementById(`farrow-${agentId}`);

  if (pill) {
    pill.classList.add('firing');
    setTimeout(() => pill.classList.remove('firing'), 800);
  }
  if (flowNode) {
    flowNode.classList.add('lit');
    if (arrow) arrow.classList.add('lit');
    setTimeout(() => {
      flowNode.classList.remove('lit');
      if (arrow) arrow.classList.remove('lit');
    }, 1500);
  }
}

let autoScroll = true;

async function poll() {
  if (paused) return;

  try {
    const res = await fetch('/monitor/stream');
    const log = await res.json();

    if (log.length > seenCount) {
      const newEntries = log.slice(seenCount);
      const empty = document.getElementById('empty-state');
      if (empty) empty.remove();

      newEntries.forEach(entry => {
        allEntries.push(entry);
        const agent = entry.agent || 'unknown';

        agentCounts[agent] = (agentCounts[agent] || 0) + 1;
        const cntEl = document.getElementById(`cnt-${agent}`);
        if (cntEl) cntEl.textContent = agentCounts[agent];

        flashAgent(agent);

        if (!activeFilter || activeFilter === agent) {
          const feed = document.getElementById('feed');
          const el = createEntryEl(entry);
          feed.appendChild(el);
          if (autoScroll) feed.scrollTop = feed.scrollHeight;
        }

        const ftimeEl = document.getElementById(`ftime-${agent}`);
        if (ftimeEl) ftimeEl.textContent = (entry.timestamp || '').slice(11, 19);
      });

      seenCount = log.length;
      document.getElementById('count-badge').textContent = `${seenCount} events`;
    }
  } catch(e) {
    document.getElementById('status-label').textContent = 'Disconnected';
    document.getElementById('status-dot').style.background = 'var(--red)';
  }
}

function togglePause() {
  paused = !paused;
  const btn = document.getElementById('pause-btn');
  btn.textContent = paused ? 'Resume' : 'Pause';
  btn.classList.toggle('active', paused);
  document.getElementById('status-label').textContent = paused ? 'Paused' : 'Monitoring';
  document.getElementById('status-dot').style.animation = paused ? 'none' : '';
  document.getElementById('status-dot').style.opacity = paused ? '0.3' : '';
}

function clearLog() {
  allEntries = [];
  seenCount = 0;
  agentCounts = {};
  document.getElementById('feed').innerHTML = `
    <div class="empty" id="empty-state">
      <div class="empty-icon">⬡</div>
      <div class="empty-text">Waiting for activity</div>
      <div class="empty-sub">Make a search in NosPopuli to see agents fire</div>
    </div>`;
  AGENTS.forEach(a => {
    const el = document.getElementById(`cnt-${a.id}`);
    if (el) el.textContent = '0';
  });
  document.getElementById('count-badge').textContent = '0 events';
}

function scrollToBottom() {
  const feed = document.getElementById('feed');
  feed.scrollTop = feed.scrollHeight;
}

document.getElementById('feed').addEventListener('scroll', function() {
  const feed = this;
  autoScroll = feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 50;
});

setInterval(poll, 500);
poll();

// ── Tab switching ──
function switchTab(tab) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.main, .analytics-panel').forEach(p => {
    p.style.display = 'none';
  });

  if (tab === 'agents') {
    document.getElementById('tab-agents').style.display = 'flex';
    document.querySelectorAll('.tab')[0].classList.add('active');
  } else if (tab === 'analytics') {
    document.getElementById('tab-analytics').style.display = 'block';
    document.querySelectorAll('.tab')[1].classList.add('active');
    loadAnalytics();
  } else if (tab === 'flags') {
    document.getElementById('tab-flags').style.display = 'block';
    document.querySelectorAll('.tab')[2].classList.add('active');
    loadFlags();
  }
}

// ── Flags loading ──
async function loadFlags() {
  try {
    const res = await fetch('/monitor/flags');
    const flags = await res.json();

    const searchFlags = flags.filter(f => f.event === 'search_flag');
    const billFlags   = flags.filter(f => f.event === 'bill_flag');

    const searchEl = document.getElementById('search-flags-list');
    searchEl.innerHTML = searchFlags.length
      ? searchFlags.slice().reverse().map(f => `
          <div class="query-row">
            <div class="query-text">
              <div style="color:var(--text)">"${f.query}"</div>
              <div style="color:var(--red);font-size:0.6rem">${f.reason}</div>
              ${f.notes ? `<div style="color:var(--muted);font-size:0.6rem">${f.notes}</div>` : ''}
            </div>
            <div class="query-count">${(f.timestamp || '').slice(11,19)}</div>
          </div>
        `).join('')
      : '<div style="color:var(--muted);font-size:0.7rem">No search flags yet</div>';

    const billEl = document.getElementById('bill-flags-list');
    billEl.innerHTML = billFlags.length
      ? billFlags.slice().reverse().map(f => `
          <div class="query-row">
            <div class="query-text">
              <div style="color:var(--text)">${f.bill_id} · ${f.flagged_section}</div>
              <div style="color:var(--red);font-size:0.6rem">${f.reason}</div>
              ${f.notes ? `<div style="color:var(--muted);font-size:0.6rem">${f.notes}</div>` : ''}
            </div>
            <div class="query-count">${(f.timestamp || '').slice(11,19)}</div>
          </div>
        `).join('')
      : '<div style="color:var(--muted);font-size:0.7rem">No bill flags yet</div>';

  } catch(e) {
    console.error('Failed to load flags:', e);
  }
}

// ── Analytics loading ──
async function loadAnalytics() {
  document.getElementById('analysis-report').textContent = 'Analyzing...';

  try {
    const res = await fetch('/monitor/analysis');
    const data = await res.json();
    const stats = data.stats || {};

    document.getElementById('stat-searches').textContent = stats.total_searches || 0;
    document.getElementById('stat-bills').textContent = stats.total_bill_opens || 0;
    document.getElementById('stat-members').textContent = stats.total_member_opens || 0;

    document.getElementById('analysis-report').textContent = data.report || 'No report generated.';

    const topQ = document.getElementById('top-queries');
    topQ.innerHTML = (stats.top_queries || []).map(([q, count]) => `
      <div class="query-row">
        <div class="query-text">${q}</div>
        <div class="query-count">${count}x</div>
      </div>
    `).join('') || '<div style="color:var(--muted);font-size:0.7rem">No searches yet</div>';

    const zeroEl = document.getElementById('zero-results');
    const zeros = stats.zero_result_searches || [];
    zeroEl.innerHTML = zeros.length
      ? zeros.map(q => `
          <div class="query-row">
            <div class="query-text zero-result">${q}</div>
            <div class="query-count" style="color:var(--red)">0 results</div>
          </div>
        `).join('')
      : '<div style="color:var(--muted);font-size:0.7rem">No zero-result searches</div>';

    const topB = document.getElementById('top-bills');
    topB.innerHTML = (stats.top_bills || []).map(([bill, count]) => `
      <div class="query-row">
        <div class="query-text">${bill}</div>
        <div class="query-count">${count}x</div>
      </div>
    `).join('') || '<div style="color:var(--muted);font-size:0.7rem">No bills opened yet</div>';

  } catch(e) {
    document.getElementById('analysis-report').textContent = 'Failed to load analysis. Is the server running?';
  }
}

async function clearSearchLog() {
  if (!confirm('Clear all search log data? This cannot be undone.')) return;
  try {
    await fetch('/monitor/clear-search-log', { method: 'POST' });
    document.getElementById('stat-searches').textContent = '0';
    document.getElementById('stat-bills').textContent = '0';
    document.getElementById('stat-members').textContent = '0';
    document.getElementById('analysis-report').textContent = 'Search log cleared.';
    document.getElementById('top-queries').innerHTML = '';
    document.getElementById('zero-results').innerHTML = '';
    document.getElementById('top-bills').innerHTML = '';
  } catch(e) {
    alert('Failed to clear search log.');
  }
}

// Initialize — show agent feed by default
document.getElementById('tab-analytics').style.display = 'none';
