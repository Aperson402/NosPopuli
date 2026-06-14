// ── Auth state ──
const AUTH_KEY = 'np_auth_token';
let _authUser   = null;
let _currentBillContext = null; // set by openDetail / openStateBill

function getAuthToken()  { return localStorage.getItem(AUTH_KEY); }
function setAuthToken(t) { localStorage.setItem(AUTH_KEY, t); }
function clearAuthToken(){ localStorage.removeItem(AUTH_KEY); }
function isLoggedIn()    { return !!getAuthToken(); }

async function authFetch(path, opts = {}) {
  const token = getAuthToken();
  return fetch(path, {
    ...opts,
    headers: {
      ...(opts.headers || {}),
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
  });
}

async function loadAuthUser() {
  if (!isLoggedIn()) { _authUser = null; _renderAuthBar(); return; }
  try {
    const res = await authFetch('/auth/me');
    if (!res.ok) { clearAuthToken(); _authUser = null; }
    else _authUser = await res.json();
  } catch { _authUser = null; }
  _renderAuthBar();
}

function signOut() {
  clearAuthToken();
  _authUser = null;
  _renderAuthBar();
  closeWritePanel();
}

function signInWithGoogle() {
  if (_currentBillContext?._reopen) {
    sessionStorage.setItem('np_return', JSON.stringify(_currentBillContext._reopen));
  }
  window.location.href = '/auth/google';
}

// ── Auth bar (top of page, only when logged in) ──
function _renderAuthBar() {
  const bar = document.getElementById('auth-bar');
  if (!bar) return;
  if (!_authUser) { bar.innerHTML = ''; bar.style.display = 'none'; return; }
  bar.style.display = 'flex';
  bar.innerHTML = `
    <span class="auth-bar-email">${_authUser.gmail_address || _authUser.email}</span>
    <button class="auth-bar-link" onclick="showPage('page-correspondence');loadCorrespondencePage()">
      My Correspondence
    </button>
    <button class="auth-bar-link" onclick="signOut()">Sign out</button>
  `;
}

// ── Bill context (captured when a bill page opens) ──
function setCurrentBillContext(ctx) {
  _currentBillContext = ctx;
  const writeBtn = document.getElementById('write-reps-btn');
  if (writeBtn) writeBtn.style.display = ctx ? 'inline-flex' : 'none';
  if (!ctx) {
    const notifyBtn = document.getElementById('notify-btn');
    if (notifyBtn) notifyBtn.style.display = 'none';
    const cap = document.getElementById('notify-email-capture');
    if (cap) cap.style.display = 'none';
  }
}

// ── Write panel open / close ──
function openWritePanel() {
  const panel = document.getElementById('write-panel');
  if (!panel) return;
  panel.classList.add('open');

  if (!isLoggedIn()) {
    _showPanelState('wp-auth');
    return;
  }
  if (!_authUser) {
    loadAuthUser().then(() => _afterAuthCheck());
  } else {
    _afterAuthCheck();
  }
}

function closeWritePanel() {
  const panel = document.getElementById('write-panel');
  if (panel) panel.classList.remove('open');
  _wpState = {};
}

function _afterAuthCheck() {
  if (!_authUser.email_screened) {
    _showPanelState('wp-flagged');
    return;
  }
  _showPanelState('wp-pick');
  _renderRepPicker();
}

function _showPanelState(id) {
  document.querySelectorAll('.wp-state').forEach(s => s.style.display = 'none');
  const el = document.getElementById(id);
  if (el) el.style.display = 'block';
}

// ── Rep picker ──
let _wpState = {};

function _renderRepPicker() {
  const prefs = getPrefs();
  const container = document.getElementById('wp-reps-list');
  if (!container) return;

  const reps = [
    ...(prefs?.senators || []).map(s => ({ ...s, label: 'Senator' })),
    prefs?.representative ? { ...prefs.representative, label: 'Representative' } : null,
  ].filter(Boolean);

  if (!reps.length) {
    container.innerHTML = `<div class="wp-empty">No representatives found. Complete onboarding first.</div>`;
    return;
  }

  container.innerHTML = reps.map((r, i) => `
    <div class="wp-rep-row" onclick="selectRep(${i})" id="wp-rep-${i}">
      <div class="wp-rep-label">${r.label}</div>
      <div class="wp-rep-name">${r.name}</div>
      <div class="wp-rep-party">${r.party || ''}</div>
      ${r.contact_form
        ? '<div class="wp-rep-contact">✓ Contact form available</div>'
        : '<div class="wp-rep-contact wp-rep-noform">Contact form only</div>'}
    </div>
  `).join('');

  window._wpReps = reps;
}

function selectRep(idx) {
  document.querySelectorAll('.wp-rep-row').forEach(r => r.classList.remove('selected'));
  const el = document.getElementById(`wp-rep-${idx}`);
  if (el) el.classList.add('selected');
  _wpState.rep = window._wpReps[idx];
  document.getElementById('wp-pick-btn').disabled = false;
}

function goToImpact() {
  if (!_wpState.rep) return;
  _showPanelState('wp-impact');
  const repName = _wpState.rep.name;
  document.getElementById('wp-impact-heading').textContent =
    `Writing to ${repName}`;
}

function goToDraft() {
  const stmt = document.getElementById('wp-statement').value.trim();
  const name = document.getElementById('wp-fullname').value.trim();
  if (!stmt || !name) return;
  _wpState.statement = stmt;
  _wpState.fullName  = name;
  _generateDraft();
}

async function _generateDraft() {
  _showPanelState('wp-drafting');
  const ctx = _currentBillContext;
  const rep = _wpState.rep;

  try {
    const res = await authFetch('/correspondence/draft', {
      method: 'POST',
      body: JSON.stringify({
        bill_id:          ctx.bill_id,
        bill_title:       ctx.bill_title,
        bill_summary:     ctx.bill_summary || '',
        latest_action:    ctx.latest_action || '',
        legislator_name:  rep.name,
        legislator_office: `${rep.label}, ${rep.state}`,
        user_statement:   _wpState.statement,
        full_name:        _wpState.fullName || '',
      }),
    });

    if (res.status === 403) {
      _showPanelState('wp-flagged'); return;
    }
    if (res.status === 429) {
      _showPanelState('wp-limit'); return;
    }
    if (!res.ok) throw new Error(await res.text());

    const data = await res.json();
    _wpState.subject = data.subject;
    _wpState.footer  = data.footer;

    document.getElementById('wp-subject-display').textContent = data.subject;
    document.getElementById('wp-draft-body').value = data.draft;
    document.getElementById('wp-footer-display').textContent = data.footer;
    _showPanelState('wp-draft');

  } catch (err) {
    document.getElementById('wp-draft-error').textContent = 'Could not generate draft. Try again.';
    document.getElementById('wp-draft-error').style.display = 'block';
    _showPanelState('wp-draft');
  }
}

async function sendLetter() {
  const body = document.getElementById('wp-draft-body').value.trim();
  if (!body) return;

  const rep = _wpState.rep;
  const ctx = _currentBillContext;
  const sendBtn = document.getElementById('wp-send-btn');
  sendBtn.disabled = true;
  sendBtn.textContent = 'Sending…';

  document.getElementById('wp-draft-error').style.display = 'none';

  try {
    const res = await authFetch('/correspondence/send', {
      method: 'POST',
      body: JSON.stringify({
        bill_id:           ctx.bill_id,
        bill_title:        ctx.bill_title,
        legislator_name:   rep.name,
        legislator_office: `${rep.label}, ${rep.state}`,
        legislator_state:  rep.state,
        to_email:          rep.email || null,
        contact_form_url:  rep.contact_form || null,
        subject:           _wpState.subject,
        body:              body,
      }),
    });

    const data = await res.json();

    if (!res.ok) {
      document.getElementById('wp-draft-error').textContent = data.detail || 'Send failed.';
      document.getElementById('wp-draft-error').style.display = 'block';
      sendBtn.disabled = false;
      sendBtn.textContent = 'Send Letter';
      return;
    }

    _wpState.result = data;
    document.getElementById('wp-sent-name').textContent = rep.name;

    if (data.delivery_method === 'form' && data.contact_form_url) {
      document.getElementById('wp-sent-form-section').style.display = 'block';
      document.getElementById('wp-open-form-btn').onclick = () => {
        navigator.clipboard.writeText(body + _wpState.footer).catch(() => {});
        window.open(data.contact_form_url, '_blank');
      };
    } else {
      document.getElementById('wp-sent-form-section').style.display = 'none';
    }

    _showPanelState('wp-sent');

  } catch(err) {
    document.getElementById('wp-draft-error').textContent = 'Network error. Please try again.';
    document.getElementById('wp-draft-error').style.display = 'block';
    sendBtn.disabled = false;
    sendBtn.textContent = 'Send Letter';
  }
}

function writeAnotherRep() {
  _wpState = {};
  _showPanelState('wp-pick');
  _renderRepPicker();
}

// ── Correspondence page ──
async function loadCorrespondencePage() {
  const list = document.getElementById('corr-list');
  if (!list) return;
  list.innerHTML = `<div class="corr-loading">Loading…</div>`;

  if (!isLoggedIn()) {
    list.innerHTML = `
      <div class="corr-auth-prompt">
        <div class="corr-auth-title">Sign in to view your correspondence</div>
        <button class="corr-sign-in-btn" onclick="signInWithGoogle()">Sign in with Google</button>
      </div>`;
    return;
  }

  try {
    const res = await authFetch('/correspondence');
    if (!res.ok) throw new Error();
    const data = await res.json();
    _renderCorrList(data.items);
  } catch {
    list.innerHTML = `<div class="corr-loading">Could not load correspondence.</div>`;
  }
}

function _renderCorrList(items) {
  const list = document.getElementById('corr-list');
  if (!items.length) {
    list.innerHTML = `
      <div class="corr-empty">
        No letters sent yet. Open a bill and click "Write to Your Reps."
      </div>`;
    return;
  }

  list.innerHTML = items.map(item => {
    const statusClass = item.status === 'replied' ? 'corr-status-replied' : 'corr-status-sent';
    const statusLabel = item.status === 'replied' ? 'REPLIED' : 'SENT';
    const date = (item.sent_at || '').slice(0, 10);
    return `
      <div class="corr-item" id="corr-${item.id}">
        <div class="corr-item-top">
          <div class="corr-item-meta">
            <span class="corr-bill-id">${item.bill_id}</span>
            <span class="corr-sep">→</span>
            <span class="corr-rep">${item.legislator_name}</span>
          </div>
          <span class="corr-status ${statusClass}">${statusLabel}</span>
        </div>
        <div class="corr-bill-title">${item.bill_title || ''}</div>
        <div class="corr-date">${date}</div>
        <div class="corr-body-preview">${(item.body || '').slice(0, 120)}…</div>
        ${item.delivery_method === 'form' ? '<div class="corr-form-note">Sent via contact form</div>' : ''}
        <div class="corr-actions">
          <button class="corr-btn" onclick="checkReplies('${item.id}')">Check for reply</button>
        </div>
        <div class="corr-replies" id="replies-${item.id}"></div>
      </div>`;
  }).join('');
}

async function checkReplies(corrId) {
  const el = document.getElementById(`replies-${corrId}`);
  if (!el) return;
  el.innerHTML = '<div class="corr-loading">Checking Gmail…</div>';

  try {
    const res = await authFetch(`/correspondence/${corrId}/replies`);
    const data = await res.json();
    const replies = data.replies || [];

    if (!replies.length) {
      el.innerHTML = '<div class="corr-no-reply">No reply yet.</div>';
      return;
    }

    el.innerHTML = replies.map(r => `
      <div class="corr-reply">
        <div class="corr-reply-from">${r.preview_text || '(No preview available)'}</div>
        <div class="corr-reply-date">${(r.received_at || '').slice(0, 10)}</div>
      </div>`).join('');

    // Update status badge
    const badge = document.querySelector(`#corr-${corrId} .corr-status`);
    if (badge) { badge.textContent = 'REPLIED'; badge.className = 'corr-status corr-status-replied'; }

  } catch {
    el.innerHTML = '<div class="corr-no-reply">Could not check replies.</div>';
  }
}

// ── Bootstrap ──
(function init() {
  // Capture np_token from OAuth callback redirect
  const params = new URLSearchParams(window.location.search);
  const npToken = params.get('np_token');
  const authError = params.get('auth_error');

  if (npToken) {
    setAuthToken(npToken);
    // Clean URL without reload
    window.history.replaceState({}, '', '/');
  }

  if (authError) {
    console.warn('[AUTH] OAuth error:', authError);
    window.history.replaceState({}, '', '/');
  }

  loadAuthUser().then(() => {
    if (!npToken) return;
    const saved = sessionStorage.getItem('np_return');
    if (!saved) return;
    sessionStorage.removeItem('np_return');
    try {
      const r = JSON.parse(saved);
      setTimeout(() => {
        if (r.type === 'federal') {
          openDetail({ congress: parseInt(r.congress), type: r.billType, number: parseInt(r.number), title: r.title });
        } else if (r.type === 'state') {
          openStateBill({ ocd_id: r.ocd_id, identifier: r.identifier, title: r.title, state: r.state });
        }
      }, 300);
    } catch(e) { /* ignore malformed saved state */ }
  });
})();
