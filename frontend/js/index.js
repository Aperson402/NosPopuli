// ── State ──
let currentResults = [];
let currentSearchContext = {};
let previousPage = 'page-home';
let currentJurisdiction = 'federal';
let currentStateCode = null;
const tooltip = document.getElementById('tooltip');

// ── localStorage keys ──
const PREFS_KEY = 'np_preferences';

function getPrefs() {
  try { return JSON.parse(localStorage.getItem(PREFS_KEY)) || null; }
  catch { return null; }
}

function savePrefs(prefs) {
  localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
}

// ── Pages ──
function showPage(id) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function goHome() {
  showPage('page-home');
  document.getElementById('results-section').innerHTML = '';
  clearStatus();
}

function goBack() {
  showPage(previousPage);
}

// ── Search ──
const input = document.getElementById('search-input');
const btn = document.getElementById('search-btn');
const statusBar = document.getElementById('status-bar');
const statusInner = document.getElementById('status-inner');
const resultsSection = document.getElementById('results-section');

input.addEventListener('keydown', e => { if (e.key === 'Enter') runSearch(); });
function setQuery(q) { input.value = q; input.focus(); }

function setStatus(msg) {
  statusBar.classList.add('visible');
  const line = document.createElement('div');
  line.className = 'status-step';
  line.textContent = '› ' + msg;
  statusInner.appendChild(line);
  requestAnimationFrame(() => line.classList.add('visible'));
}
function clearStatus() {
  statusInner.innerHTML = '';
  statusBar.classList.remove('visible');
}

function billIdFromParts(type, number) {
  return (type || '').toUpperCase() + ' ' + number;
}

function formatCongress(n) {
  if (!n) return '';
  const s = n % 100;
  if (s >= 11 && s <= 13) return `${n}th`;
  switch (n % 10) {
    case 1: return `${n}st`;
    case 2: return `${n}nd`;
    case 3: return `${n}rd`;
    default: return `${n}th`;
  }
}

function formatTimelineDate(dateStr) {
  if (!dateStr) return { day: '', year: '' };
  const months = ['Jan','Feb','Mar','Apr','May','Jun',
                  'Jul','Aug','Sep','Oct','Nov','Dec'];
  const parts = dateStr.split('-');
  if (parts.length < 2) return { day: '', year: dateStr };
  const year = parts[0];
  const month = months[parseInt(parts[1]) - 1] || '';
  const day = parts[2] ? parseInt(parts[2]) : '';
  return { day: `${month} ${day}`, year };
}

function chamberLabel(event) {
  const c = (event.chamber || '').toLowerCase();
  const t = event.event_type;
  if (t === 'signed') return 'President · Signed into Law';
  if (t === 'vetoed') return 'President · Vetoed';
  if (t === 'conference') return 'Conference Committee';
  if (c === 'house') return `House · ${capitalize(t)}`;
  if (c === 'senate') return `Senate · ${capitalize(t)}`;
  return capitalize(t);
}

function capitalize(str) {
  if (!str) return '';
  return str.charAt(0).toUpperCase() + str.slice(1);
}

function renderTimeline(events, fallbackMarkdown) {
  const el = document.getElementById('detail-timeline');

  if (!events || !events.length) {
    el.innerHTML = renderMarkdown(fallbackMarkdown);
    return;
  }

  let html = '<div class="tl-entries"><div class="tl-spine"></div>';

  events.forEach(event => {
    const { day, year } = formatTimelineDate(event.date);
    const isSigned = event.event_type === 'signed';
    const isVetoed = event.event_type === 'vetoed';
    const isPassed = event.event_type === 'passed';
    const isCommittee = event.event_type === 'committee';

    const dotClass = isSigned ? 'tl-dot tl-dot-law'
                   : isVetoed ? 'tl-dot tl-dot-vetoed'
                   : isPassed || isCommittee ? 'tl-dot tl-dot-filled'
                   : 'tl-dot';

    const cardClass = isSigned ? 'tl-card tl-card-signed'
                    : isVetoed ? 'tl-card tl-card-vetoed'
                    : 'tl-card';

    const voteHtml = (event.yea !== null && event.nay !== null) ? `
      <div class="tl-vote-row">
        <span class="tl-vote-pill tl-vote-yea">Yea ${event.yea}</span>
        <span class="tl-vote-pill tl-vote-nay">Nay ${event.nay}</span>
      </div>` : '';

    html += `
      <div class="tl-entry">
        <div class="tl-date">
          <span>${day}</span>
          <span class="tl-date-year">${year}</span>
        </div>
        <div class="${dotClass}"></div>
        <div class="${cardClass}">
          <div class="tl-chamber-tag">${chamberLabel(event)}</div>
          <div class="tl-event">${event.text}</div>
          ${event.detail && event.detail !== event.text
            ? `<div class="tl-detail">${event.detail.slice(0, 200)}${event.detail.length > 200 ? '…' : ''}</div>`
            : ''}
          ${voteHtml}
        </div>
      </div>`;
  });

  html += '</div>';
  html += '<div class="tl-note">Data sourced from Congress.gov legislative actions.</div>';

  el.innerHTML = html;
}

function renderMarkdown(text) {
  return (text || '')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/^---$/gm, '<hr style="border:none;border-top:1px solid var(--rule);margin:0.75rem 0">');
}

// ── Tooltip ──
function showTooltip(e, seat) {
  const partyLabel = seat.party === 'D' ? 'Democrat' : seat.party === 'R' ? 'Republican' : 'Independent';
  tooltip.textContent = `${seat.name} · ${seat.state} · ${partyLabel} · ${seat.vote} — click to view profile`;
  tooltip.classList.add('visible');
  moveTooltip(e);
}
function moveTooltip(e) {
  tooltip.style.left = (e.clientX + 12) + 'px';
  tooltip.style.top  = (e.clientY - 28) + 'px';
}
function hideTooltip() { tooltip.classList.remove('visible'); }

let memberLoadingInProgress = false;

async function openMemberFromVote(seat) {
  if (memberLoadingInProgress) return;
  memberLoadingInProgress = true;
  hideTooltip();

  const loadingEl = document.getElementById('member-loading');
  const contentEl = document.getElementById('member-page-content');
  const steps = ['mstep-1', 'mstep-2', 'mstep-3'].map(id => document.getElementById(id));

  steps.forEach(s => s.classList.remove('visible', 'done'));
  loadingEl.style.display = 'block';
  contentEl.style.display = 'none';
  previousPage = document.querySelector('.page.active').id;
  showPage('page-member');

  steps[0].classList.add('visible');
  const t1 = setTimeout(() => steps[1].classList.add('visible'), 400);
  const t2 = setTimeout(() => steps[2].classList.add('visible'), 900);

  try {
    const res = await fetch('/member/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: seat.name })
    });
    const data = await res.json();
    clearTimeout(t1); clearTimeout(t2);
    steps.forEach(s => s.classList.add('done'));

    if (data.found) {
      renderMemberPage(data);
    } else {
      loadingEl.style.display = 'none';
      contentEl.style.display = 'block';
      setStatus(`No profile found for ${seat.name}`);
      setTimeout(clearStatus, 2500);
    }
  } catch {
    clearTimeout(t1); clearTimeout(t2);
    loadingEl.style.display = 'none';
    contentEl.style.display = 'block';
    setStatus('Could not load member profile');
    setTimeout(clearStatus, 2500);
  } finally {
    memberLoadingInProgress = false;
  }
}

// ── Chamber SVG ──
function renderChamber(title, data, svgW, svgH) {
  if (!data || !data.seats || !data.seats.length) return null;
  const s = data.summary;
  const block = document.createElement('div');
  block.className = 'chamber-block';
  const titleEl = document.createElement('div');
  titleEl.className = 'chamber-title';
  titleEl.textContent = title;
  block.appendChild(titleEl);
  const summary = document.createElement('div');
  summary.className = 'vote-summary';
  summary.innerHTML = `
    <span class="vote-count-yea">YEA ${s.yea}</span>
    <span class="vote-count-nay">NAY ${s.nay}</span>
    ${s.present > 0 ? `<span class="vote-count-other">PRESENT ${s.present}</span>` : ''}
    ${s.not_voting > 0 ? `<span class="vote-count-other">NOT VOTING ${s.not_voting}</span>` : ''}
  `;
  block.appendChild(summary);
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${svgW} ${svgH}`);
  svg.setAttribute('class', 'chamber-svg');
  data.seats.forEach(seat => {
    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('cx', seat.x);
    circle.setAttribute('cy', seat.y);
    circle.setAttribute('r', title.includes('House') ? 4.5 : 6);
    circle.setAttribute('fill', seat.color);
    circle.setAttribute('opacity', '0.9');
    circle.style.cursor = 'pointer';
    circle.addEventListener('mouseenter', e => showTooltip(e, seat));
    circle.addEventListener('mousemove',  e => moveTooltip(e));
    circle.addEventListener('mouseleave', hideTooltip);
    circle.addEventListener('click', () => openMemberFromVote(seat));
    svg.appendChild(circle);
  });
  block.appendChild(svg);
  return block;
}

function renderVotes(votes) {
  const section = document.getElementById('votes-section');
  const grid = document.getElementById('chambers-grid');
  grid.innerHTML = '';
  const hasHouse  = votes && votes.house  && votes.house.seats  && votes.house.seats.length;
  const hasSenate = votes && votes.senate && votes.senate.seats && votes.senate.seats.length;
  if (!hasHouse && !hasSenate) { section.style.display = 'none'; return; }
  section.style.display = 'block';
  if (hasHouse) { const b = renderChamber('House of Representatives', votes.house, 500, 260); if (b) grid.appendChild(b); }
  if (hasSenate) { const b = renderChamber('Senate', votes.senate, 300, 200); if (b) grid.appendChild(b); }
  grid.style.gridTemplateColumns = (hasHouse && hasSenate) ? '1fr 1fr' : '1fr';
}

// ── Bill detail ──
async function openDetail(bill) {
  bill = {
    ...bill,
    congress: parseInt(bill.congress) || bill.congress,
    number: parseInt(bill.number) || bill.number,
    law_number: bill.law_number ? parseInt(bill.law_number) : null
  };
  const activePage = document.querySelector('.page.active').id;
  if (activePage !== 'page-detail') previousPage = activePage;
  const billId = bill.is_law
    ? `Public Law ${bill.congress}-${bill.law_number}`
    : billIdFromParts(bill.type, bill.number);

  document.getElementById('detail-bill-id').textContent = billId;
  document.getElementById('detail-bill-title').textContent = bill.title || billId;
  document.getElementById('detail-loading').style.display = 'block';
  document.getElementById('detail-content').style.display = 'none';
  document.getElementById('votes-section').style.display = 'none';

  const steps = ['lstep-1', 'lstep-2', 'lstep-3', 'lstep-4'];
  steps.forEach((id, i) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.remove('visible', 'done');
    setTimeout(() => el.classList.add('visible'), i * 700);
  });

  showPage('page-detail');

  try {
    const endpoint = bill.is_law ? '/law' : '/bill';
    const body = bill.is_law
      ? { congress: bill.congress, law_number: bill.law_number }
      : { congress: parseInt(bill.congress), bill_type: bill.type, number: parseInt(bill.number), user_context: getPrefs() };

    const response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });

    if (!response.ok) throw new Error(`Error: ${response.status}`);
    const data = await response.json();
    steps.forEach(id => document.getElementById(id).classList.add('done'));

    setTimeout(() => {
      document.getElementById('detail-loading').style.display = 'none';
      document.getElementById('detail-explanation').innerHTML = renderMarkdown(data.translation);
      renderTimeline(data.timeline_events, data.timeline);
      renderVotes(data.votes);
      document.getElementById('detail-content').style.display = 'block';
    }, 400);

  } catch (err) {
    document.getElementById('detail-loading').innerHTML = `
      <div class="empty-state">
        <p>This couldn't be loaded right now.</p>
        <p style="margin-top:0.5rem">The data may be temporarily unavailable.</p>
        <button class="example-pill"
          style="margin-top:1rem"
          onclick="openDetail(${JSON.stringify(bill).replace(/"/g, '&quot;')})">
          Try again
        </button>
      </div>`;
    document.getElementById('detail-loading').style.display = 'block';
    document.getElementById('detail-content').style.display = 'none';
    btn.disabled = false;
  }
}

function openDetailFromBill(bill) {
  openDetail({ congress: bill.congress, type: bill.type, number: parseInt(bill.number), title: bill.title });
}

// ── Member profile ──
function renderMemberPage(data) {
  const activeMemberPage = document.querySelector('.page.active').id;
  if (activeMemberPage !== 'page-member') previousPage = activeMemberPage;
  document.getElementById('member-loading').style.display = 'none';
  document.getElementById('member-page-content').style.display = 'block';
  const backBtn = document.querySelector('#member-page-content .detail-back');
  backBtn.textContent = previousPage === 'page-detail' ? '← Back to bill' : '← Back to search';
  const m = data.member;
  const leg = data.legislation;

  document.getElementById('member-party-tag').textContent =
    [m.party || 'Independent', m.chambers ? m.chambers.join(' & ') : m.chamber || ''].filter(Boolean).join('  ·  ');
  document.getElementById('member-name').textContent = m.name || '';
  document.getElementById('member-meta-line').textContent = [
    m.state,
    m.start_year ? `${m.start_year}–${m.end_year || 'present'}` : '',
    m.birth_year ? `b. ${m.birth_year}` : ''
  ].filter(Boolean).join('  ·  ');
  document.getElementById('member-status').textContent = m.current ? 'Currently serving' : 'Former member';

  const photo = document.getElementById('member-photo');
  if (m.bioguide_id) { photo.style.display = 'block'; photo.src = `/member/photo/${m.bioguide_id.toLowerCase()}`; photo.alt = m.name; }

  const statsGrid = document.getElementById('member-stats-grid');
  const stats = [
    { number: m.years_served || '—', label: 'Years Served' },
    { number: (leg.sponsored_count || 0).toLocaleString(), label: 'Bills Sponsored' },
    { number: (leg.cosponsored_count || 0).toLocaleString(), label: 'Cosponsored' },
    { number: Object.keys(leg.policy_areas || {}).filter(k => k && k !== 'None').length, label: 'Policy Areas' },
  ];
  statsGrid.innerHTML = stats.map(s => `
    <div class="stat-block">
      <div class="stat-number">${s.number}</div>
      <div class="stat-label">${s.label}</div>
    </div>
  `).join('');

  const policyChart = document.getElementById('policy-chart');
  const areas = Object.entries(leg.policy_areas || {})
    .filter(([k]) => k && k !== 'None' && k !== 'Other' && k !== 'null')
    .sort((a, b) => b[1] - a[1]);
  if (areas.length) {
    const max = areas[0][1];
    policyChart.innerHTML = areas.map(([label, count]) => `
      <div class="policy-bar-row">
        <div class="policy-bar-label">${label}</div>
        <div class="policy-bar-track"><div class="policy-bar-fill" style="width:${(count/max*100).toFixed(1)}%"></div></div>
        <div class="policy-bar-count">${count}</div>
      </div>
    `).join('');
  }

  const billsEl = document.getElementById('member-bills');
  const validBills = (leg.sponsored || []).filter(b => b.title && b.number);
  billsEl.innerHTML = validBills.map(b => `
    <div class="member-bill-row" onclick='openDetailFromBill(${JSON.stringify(b)})'>
      <div class="member-bill-id">${(b.type || '').toUpperCase()} ${b.number}</div>
      <div class="member-bill-title">${(b.title || '').slice(0, 100)}${(b.title || '').length > 100 ? '…' : ''}</div>
      <div class="member-bill-date">${b.date || ''}</div>
    </div>
  `).join('') || '<p style="font-family:\'IBM Plex Mono\',monospace;font-size:0.7rem;color:var(--muted)">No recent bills found</p>';

  showPage('page-member');
}

// ── Feed rendering ──
function renderFeedSection(items, prefs) {
  const feedSection = document.getElementById('feed-section');

  if (!items || !items.length) {
    feedSection.innerHTML = `
      <div class="feed-header">
        <h2>Your Feed</h2>
        <div class="feed-header-right">
          <button class="feed-settings-btn" onclick="showPage('page-onboarding');showStep(1)">Edit preferences</button>
        </div>
      </div>
      <div class="empty-state">
        <p>No recent legislation found for your interests.</p>
        <p style="margin-top:0.5rem">Try updating your topics.</p>
      </div>`;
    return;
  }

  feedSection.innerHTML = `
    <div class="feed-header">
      <h2>Your Feed</h2>
      <div class="feed-header-right">
        <span class="feed-location">${prefs.state}</span>
        <button class="feed-settings-btn" onclick="showPage('page-onboarding');showStep(1)">Edit</button>
      </div>
    </div>
  `;

  items.forEach((item, i) => {
    const card = document.createElement('div');
    card.className = 'feed-card';
    card.style.animationDelay = (i * 0.06) + 's';
    if (item.is_state_bill) {
      card.onclick = () => openStateBill(item);
    } else {
      card.onclick = () => openDetail({
        congress: parseInt(item.congress),
        type: item.type,
        number: parseInt(item.number),
        title: item.title
      });
    }

    const isRep = item.feed_reason === 'your_rep';
    const isState = item.feed_reason === 'state_legislature';
    const reasonText = isRep
      ? `Your representative sponsored this`
      : isState
      ? `Virginia Legislature`
      : `${item.feed_interest ? item.feed_interest.replace('_', ' ') : item.feed_reason}`;

    const billId = item.is_state_bill
      ? `${item.identifier} · Virginia`
      : `${(item.type || '').toUpperCase()} ${item.number}`;

    card.innerHTML = `
      <div class="feed-card-inner">
        <div class="feed-reason ${isRep ? 'reason-rep' : 'reason-topic'}">
          ${isRep ? '⚡ ' : ''}${reasonText}
        </div>
        <div class="feed-bill-id">${billId}</div>
        <div class="feed-bill-title">${item.title || billId}</div>
        ${item.latest_action ? `<div class="feed-bill-action">${item.latest_action}</div>` : ''}
      </div>
      <div class="feed-card-footer">
        <div class="feed-date">${item.date || ''}</div>
        <div class="feed-arrow">Read more →</div>
      </div>
    `;

    feedSection.appendChild(card);
  });
}

async function loadFeed() {
  const prefs = getPrefs();
  const feedSection = document.getElementById('feed-section');

  if (!prefs) {
    feedSection.innerHTML = `
      <div class="onboarding-prompt">
        <div class="onboarding-prompt-title">Your personal civic feed</div>
        <div class="onboarding-prompt-text">
          Tell us where you live and what issues matter to you.<br>
          We'll curate a daily feed of legislation that affects you.<br>
          No account needed. Stored only in your browser.
        </div>
        <button class="onboarding-start-btn" onclick="showPage('page-onboarding');showStep(1)">
          Set up my feed →
        </button>
      </div>`;
    return;
  }

  feedSection.innerHTML = `<div style="padding:2rem 0;text-align:center;font-family:'IBM Plex Mono',monospace;font-size:0.7rem;color:var(--muted)">Loading your feed...</div>`;

  try {
    const response = await fetch('/feed', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        interests: prefs.interests,
        senator_bioguides: prefs.senators.map(s => s.bioguide_id),
        rep_bioguide: prefs.representative ? prefs.representative.bioguide_id : null,
        state_code: prefs.state || null
      })
    });

    const data = await response.json();
    renderFeedSection(data.items, prefs);

  } catch(err) {
    feedSection.innerHTML = `<div class="empty-state"><p>Could not load feed.</p></div>`;
  }
}

// ── Committee page ──
function renderCommitteePage(data) {
  const c = data.committee;
  resultsSection.innerHTML = '';

  const header = document.createElement('div');
  header.className = 'results-header';
  header.innerHTML = `
      <h2>${c.name}</h2>
      <span class="results-count">${c.chamber}</span>`;
  resultsSection.appendChild(header);

  if (!data.bills || !data.bills.length) {
      resultsSection.innerHTML += `<div class="empty-state"><p>No recent bills found for this committee.</p></div>`;
      return;
  }

  data.bills.forEach((bill, i) => {
      const card = document.createElement('div');
      card.className = 'result-card';
      card.style.animationDelay = (i * 0.05) + 's';
      card.onclick = () => openDetail({
          congress: parseInt(bill.congress),
          type: bill.type,
          number: parseInt(bill.number),
          title: bill.title,
          date: bill.date,
          latest_action: bill.latest_action,
      });

      const billId = billIdFromParts(bill.type, bill.number);

      card.innerHTML = `
          <div class="result-card-inner">
              <div class="result-card-left">
                  <div class="result-bill-id">${billId}</div>
                  <div class="result-bill-title">${bill.title || billId}</div>
              </div>
              <div class="result-card-arrow">Read more →</div>
          </div>
          <div class="result-meta">
              <div class="meta-item"><strong>${formatCongress(bill.congress)} Congress</strong></div>
              <div class="meta-item"><strong>${bill.date || ''}</strong></div>
              <div class="meta-item">${bill.latest_action ? bill.latest_action.slice(0,50) : ''}</div>
          </div>`;

      resultsSection.appendChild(card);
  });
}

// ── Search results ──
function renderResults(data) {
  resultsSection.innerHTML = '';
  currentResults = data.results || [];

  currentSearchContext = {
    query: input.value.trim(),
    expanded_terms: data.query?.expanded_terms || [],
    congress_numbers: data.query?.congress_numbers || [],
    confidence: data.confidence || 1.0,
    results_shown: currentResults.map(r => ({
      bill_id: `${(r.type||'').toUpperCase()}${r.number}`,
      title: r.title,
      date: r.date_issued
    }))
  };

  if (!currentResults.length) {
    resultsSection.innerHTML = `
      <div class="empty-state">
        <p>No bills found for that query.</p>
        <p style="margin-top:0.5rem">Try different keywords or a broader question.</p>
      </div>`;
    return;
  }

  const header = document.createElement('div');
  header.className = 'results-header';
  header.innerHTML = `
    <h2>Search Results</h2>
    <span class="results-count">${currentResults.length} bill${currentResults.length !== 1 ? 's' : ''} found</span>`;
  resultsSection.appendChild(header);

  currentResults.forEach((bill, i) => {
    const card = document.createElement('div');
    card.className = 'result-card';
    card.style.animationDelay = (i * 0.05) + 's';
    card.onclick = () => openDetail({
      congress: parseInt(bill.congress),
      type: bill.type,
      number: parseInt(bill.number),
      title: bill.title,
      is_law: bill.is_law,
      law_number: bill.law_number ? parseInt(bill.law_number) : null
    });

    const billId = bill.is_law
      ? `Public Law ${bill.congress}-${bill.law_number}`
      : billIdFromParts(bill.type || '', bill.number || '');
    const congress = bill.congress ? `${formatCongress(bill.congress)} Congress` : '';
    const date = bill.date_issued ? bill.date_issued.slice(0, 4) : '';

    card.innerHTML = `
      <div class="result-card-inner">
        <div class="result-card-left">
          <div class="result-bill-id">${billId}</div>
          <div class="result-bill-title">${bill.title || billId}</div>
        </div>
        <div class="result-card-arrow">Read more →</div>
      </div>
      <div class="result-meta">
        <div class="meta-item"><strong>${congress}</strong></div>
        <div class="meta-item"><strong>${date}</strong></div>
        <div class="meta-item">Click for full analysis</div>
      </div>`;

    resultsSection.appendChild(card);
  });

  const flagRow = document.createElement('div');
  flagRow.style.cssText = 'margin-top:1.5rem;padding-top:1rem;border-top:1px solid var(--rule);text-align:center';
  flagRow.innerHTML = `
    <button class="feed-settings-btn" onclick="showSearchFlag()">
      Didn't find what you were looking for? Flag this search
    </button>`;
  resultsSection.appendChild(flagRow);
}

// ── Clarification bar ──
function showClarificationBar(confidence, reason, question) {
  if (confidence >= 0.7 || !reason) return;

  const bar = document.createElement('div');
  bar.style.cssText = `
      border-left: 2px solid var(--accent);
      padding: 0.75rem 1rem;
      margin-bottom: 1.5rem;
      background: var(--card-bg);
      border: 1px solid var(--rule);
  `;
  bar.innerHTML = `
      <div style="font-family:'IBM Plex Mono',monospace;font-size:0.6rem;
                  letter-spacing:0.15em;text-transform:uppercase;
                  color:var(--muted);margin-bottom:0.5rem">
          Ambiguous query · confidence ${Math.round(confidence * 100)}%
      </div>
      <div style="font-size:0.88rem;color:var(--ink);margin-bottom:0.75rem">
          ${reason}
      </div>
      <div style="display:flex;gap:0.5rem;flex-wrap:wrap">
          <button class="example-pill"
              onclick="setQuery('${question} legislation');runSearch()">
              Search as legislation
          </button>
          <button class="example-pill"
              onclick="setQuery('${question} senator');runSearch()">
              Search as person
          </button>
      </div>
  `;
  resultsSection.insertBefore(bar, resultsSection.firstChild);
}

// ── Jurisdiction toggle ──
function setJurisdiction(j, el) {
  currentJurisdiction = j;
  document.querySelectorAll('.jurisdiction-btn').forEach(b => b.classList.remove('active'));
  el.classList.add('active');
}

function updateJurisdictionToggle(prefs) {
  const stateBtn = document.getElementById('state-toggle-btn');
  if (!prefs || !prefs.state) { stateBtn.style.display = 'none'; return; }
  const ENABLED = ['VA'];
  if (ENABLED.includes(prefs.state)) {
    currentStateCode = prefs.state;
    stateBtn.textContent = prefs.state === 'VA' ? 'Virginia' : prefs.state;
    stateBtn.style.display = 'block';
  } else {
    stateBtn.style.display = 'none';
  }
}

// ── State search ──
async function runStateSearch(question, stateCode) {
  btn.disabled = true;
  resultsSection.innerHTML = '';
  clearStatus();
  showPage('page-home');
  setStatus('Searching Virginia legislation...');

  try {
    const response = await fetch('/state/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, state_code: stateCode, max_results: 10 })
    });
    if (!response.ok) throw new Error(`Server error: ${response.status}`);
    const data = await response.json();
    clearStatus();
    renderStateResults(data);
    resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (err) {
    clearStatus();
    resultsSection.innerHTML = `
      <div class="empty-state">
        <p>State search failed. Please try again.</p>
      </div>`;
  } finally {
    btn.disabled = false;
  }
}

function renderStateResults(data) {
  resultsSection.innerHTML = '';
  const results = data.results || [];

  if (!results.length) {
    resultsSection.innerHTML = `
      <div class="empty-state">
        <p>No Virginia bills found.</p>
        <p style="margin-top:0.5rem">Try different keywords.</p>
      </div>`;
    return;
  }

  const header = document.createElement('div');
  header.className = 'results-header';
  header.innerHTML = `
    <h2>Virginia Results</h2>
    <span class="results-count">${results.length} bill${results.length !== 1 ? 's' : ''} found</span>`;
  resultsSection.appendChild(header);

  results.forEach((bill, i) => {
    const card = document.createElement('div');
    card.className = 'result-card';
    card.style.animationDelay = (i * 0.05) + 's';
    card.onclick = () => openStateBill(bill);

    card.innerHTML = `
      <div class="result-card-inner">
        <div class="result-card-left">
          <div class="result-bill-id">${bill.identifier} · Virginia ${bill.session}</div>
          <div class="result-bill-title">${bill.title}</div>
        </div>
        <div class="result-card-arrow">Read more →</div>
      </div>
      <div class="result-meta">
        <div class="meta-item"><strong>${bill.chamber === 'lower' ? 'House' : 'Senate'}</strong></div>
        <div class="meta-item"><strong>${bill.latest_action_date || ''}</strong></div>
        <div class="meta-item">${(bill.latest_action || '').slice(0, 50)}</div>
      </div>`;

    resultsSection.appendChild(card);
  });
}

async function openStateBill(bill) {
  previousPage = document.querySelector('.page.active').id;

  document.getElementById('detail-bill-id').textContent = `${bill.identifier} · Virginia`;
  document.getElementById('detail-bill-title').textContent = bill.title || bill.identifier;
  document.getElementById('detail-loading').style.display = 'block';
  document.getElementById('detail-content').style.display = 'none';

  const steps = ['lstep-1', 'lstep-2', 'lstep-3', 'lstep-4'];
  steps.forEach((id, i) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.remove('visible', 'done');
    setTimeout(() => el.classList.add('visible'), i * 700);
  });

  showPage('page-detail');

  try {
    const response = await fetch('/state/bill', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ocd_id: bill.ocd_id, state_code: bill.state || 'VA' })
    });
    if (!response.ok) throw new Error(`Error: ${response.status}`);
    const data = await response.json();

    steps.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.classList.add('done');
    });

    setTimeout(() => {
      document.getElementById('detail-loading').style.display = 'none';
      document.getElementById('detail-explanation').innerHTML = renderMarkdown(data.translation);
      renderTimeline(data.timeline_events, data.timeline);
      document.getElementById('votes-section').style.display = 'none';
      document.getElementById('detail-content').style.display = 'block';
    }, 400);

  } catch (err) {
    document.getElementById('detail-loading').innerHTML = `
      <div class="empty-state">
        <p>This bill couldn't be loaded right now.</p>
      </div>`;
  }
}

// ── Main search ──
async function runSearch() {
  const question = input.value.trim();
  if (!question) return;

  if (currentJurisdiction === 'state' && currentStateCode) {
    return await runStateSearch(question, currentStateCode);
  }

  btn.disabled = true;
  resultsSection.innerHTML = '';
  clearStatus();
  showPage('page-home');

  setStatus('Understanding your question...');

  try {
    setTimeout(() => setStatus('Searching federal legislation...'), 500);

    const response = await fetch('/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, max_results: 10 })
    });

    if (!response.ok) throw new Error(`Server error: ${response.status}`);
    const data = await response.json();
    clearStatus();

    if (data.confidence < 0.7 && data.ambiguity_reason) {
      showClarificationBar(data.confidence, data.ambiguity_reason, question);
    }

    if (data.query_type === 'member') {
      if (data.found) {
        renderMemberPage(data);
      } else {
        resultsSection.innerHTML = `
          <div class="empty-state">
            <p>Member not found.</p>
            <p style="margin-top:0.5rem">Try using their full name.</p>
          </div>`;
      }
    } else if (data.query_type === 'committee') {
      if (data.found) {
        renderCommitteePage(data);
      } else {
        resultsSection.innerHTML = `
          <div class="empty-state">
            <p>Committee not found.</p>
            <p style="margin-top:0.5rem">Try the full committee name.</p>
          </div>`;
      }
    } else {
      renderResults(data);
      resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

  } catch (err) {
    clearStatus();
    resultsSection.innerHTML = `
      <div class="empty-state">
        <p>Something went wrong. Is the server running?</p>
        <p style="margin-top:0.5rem;font-size:0.6rem">${err.message}</p>
      </div>`;
  } finally {
    btn.disabled = false;
  }
}

// ── Onboarding ──
let onboardingData = { zip: null, state: null, senators: [], representative: null, interests: [] };

function showStep(n) {
  document.querySelectorAll('.onboarding-step').forEach(s => s.classList.remove('active'));
  document.getElementById(`step-${n}`).classList.add('active');
}

async function handleZipInput(val) {
  if (val.length === 5 && /^\d{5}$/.test(val)) {
    await lookupZip(val);
  } else {
    document.getElementById('zip-result').classList.remove('visible');
    document.getElementById('step1-btn').disabled = true;
  }
}

async function lookupZip(zip) {
  zip = zip || document.getElementById('zip-input').value;
  if (!/^\d{5}$/.test(zip)) return;

  try {
    const res = await fetch('/resolve-zip', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ zip_code: zip })
    });

    if (!res.ok) throw new Error('Not found');
    const data = await res.json();

    onboardingData.zip = zip;
    onboardingData.state = data.state;
    onboardingData.senators = data.senators || [];
    onboardingData.representative = data.representative;

    const repsEl = document.getElementById('zip-reps');
    const all = [
      ...data.senators.map(s => ({ ...s, label: 'Senator' })),
      data.representative ? { ...data.representative, label: 'Rep.' } : null
    ].filter(Boolean);

    repsEl.innerHTML = all.map(p => `
      <div class="zip-rep-row">
        <div class="zip-rep-chamber">${p.label}</div>
        <div class="zip-rep-name">${p.name}</div>
        <div class="zip-rep-party">${p.party}</div>
      </div>
    `).join('');

    document.getElementById('zip-result').classList.add('visible');
    document.getElementById('step1-btn').disabled = false;

  } catch(e) {
    document.getElementById('zip-result').innerHTML = '<div style="font-family:\'IBM Plex Mono\',monospace;font-size:0.7rem;color:var(--accent)">Could not find representatives for this zip code.</div>';
    document.getElementById('zip-result').classList.add('visible');
  }
}

function goToStep2() {
  showPage('page-onboarding');
  showStep(2);
}

function toggleInterest(el) {
  el.classList.toggle('selected');
  const selected = document.querySelectorAll('.interest-pill.selected');
  document.getElementById('step2-btn').disabled = selected.length === 0;
}

function finishOnboarding() {
  const selected = [...document.querySelectorAll('.interest-pill.selected')]
    .map(el => el.dataset.interest);

  const prefs = {
    zip: onboardingData.zip,
    state: onboardingData.state,
    senators: onboardingData.senators,
    representative: onboardingData.representative,
    interests: selected,
    created: new Date().toISOString()
  };

  savePrefs(prefs);
  updateJurisdictionToggle(prefs);
  showPage('page-home');
  loadFeed();
}

async function checkServer() {
  try {
    const r = await fetch('/health', { signal: AbortSignal.timeout(3000) });
    if (!r.ok) throw new Error();
  } catch {
    document.getElementById('results-section').innerHTML = `
      <div class="empty-state">
        <p>Cannot connect to NosPopuli server.</p>
        <p style="margin-top:0.5rem;font-size:0.6rem">
          Make sure uvicorn is running: uvicorn api:app --reload
        </p>
      </div>`;
  }
}

// ── Flag system ──
let currentFlagType = null;
let currentFlagContext = {};

const SEARCH_REASONS = [
  "Results not relevant",
  "Missing important bills",
  "Wrong time period",
  "Misunderstood my question",
  "Other"
];

const BILL_REASONS = [
  "Translation is inaccurate",
  "Missing key information",
  "Wrong bill details",
  "Timeline is incorrect",
  "Other"
];

function showSearchFlag() {
  currentFlagType = 'search';
  currentFlagContext = currentSearchContext;
  document.getElementById('flag-modal-title').textContent = 'What was wrong with these results?';
  renderFlagReasons(SEARCH_REASONS);
  openFlagModal();
}

function showBillFlag(section) {
  currentFlagType = 'bill';
  currentFlagContext = { section };
  document.getElementById('flag-modal-title').textContent = 'What is inaccurate?';
  renderFlagReasons(BILL_REASONS);
  openFlagModal();
}

function renderFlagReasons(reasons) {
  const container = document.getElementById('flag-reasons');
  container.innerHTML = reasons.map((r, i) => `
    <label style="display:flex;align-items:center;gap:0.5rem;
                  margin-bottom:0.5rem;cursor:pointer;
                  font-size:0.88rem;font-family:'Source Serif 4',serif">
      <input type="radio" name="flag-reason" value="${r}" ${i === 0 ? 'checked' : ''}>
      ${r}
    </label>
  `).join('');
}

function openFlagModal() {
  document.getElementById('flag-notes').value = '';
  document.getElementById('flag-success').style.display = 'none';
  const modal = document.getElementById('flag-modal');
  modal.style.display = 'flex';
}

function closeFlagModal() {
  document.getElementById('flag-modal').style.display = 'none';
  currentFlagType = null;
  currentFlagContext = {};
}

async function submitFlag() {
  const reason = document.querySelector('input[name="flag-reason"]:checked')?.value;
  const notes = document.getElementById('flag-notes').value.trim();
  if (!reason) return;

  try {
    if (currentFlagType === 'search') {
      await fetch('/flag/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: currentFlagContext.query,
          results_shown: currentFlagContext.results_shown,
          expanded_terms: currentFlagContext.expanded_terms,
          congress_numbers: currentFlagContext.congress_numbers,
          confidence: currentFlagContext.confidence,
          reason, notes
        })
      });
    } else if (currentFlagType === 'bill') {
      const billId = document.getElementById('detail-bill-id').textContent;
      await fetch('/flag/bill', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bill_id: billId,
          congress: 0,
          bill_type: currentFlagContext.section || 'translation',
          reason, notes,
          flagged_section: currentFlagContext.section || 'translation'
        })
      });
    }
    document.getElementById('flag-success').style.display = 'block';
    setTimeout(closeFlagModal, 1500);
  } catch(err) {
    console.error('Flag submission failed:', err);
  }
}

document.getElementById('flag-modal').addEventListener('click', function(e) {
  if (e.target === this) closeFlagModal();
});

// ── Init ──
checkServer();
updateJurisdictionToggle(getPrefs());
loadFeed();
