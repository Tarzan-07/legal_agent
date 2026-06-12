/* =====================================================================
   app.js  —  Invoice Agent frontend (session-aware)
   ===================================================================== */

// ── Session state ──────────────────────────────────────────────────────────
let currentSessionId = null;

// ── Staged files ───────────────────────────────────────────────────────────
const stagedFiles = new Map();
let fileCounter = 0;

// ── DOM refs ───────────────────────────────────────────────────────────────
const dropZone        = document.getElementById('dropZone');
const fileInput       = document.getElementById('fileInput');
const fileList        = document.getElementById('fileList');
const uploadBtn       = document.getElementById('uploadBtn');
const resultSection   = document.getElementById('resultSection');
const resultCards     = document.getElementById('resultCards');
const invoicesBody    = document.getElementById('invoicesBody');
const chatMessages    = document.getElementById('chatMessages');
const chatInput       = document.getElementById('chatInput');
const sendBtn         = document.getElementById('sendBtn');

// Sidebar
const hamburgerBtn    = document.getElementById('hamburgerBtn');
const sidebar         = document.getElementById('sidebar');
const sidebarOverlay  = document.getElementById('sidebarOverlay');
const sidebarClose    = document.getElementById('sidebarClose');
const sessionList     = document.getElementById('sessionList');
const newSessionBtn   = document.getElementById('newSessionBtn');
const sessionBadge    = document.getElementById('sessionBadge');
const sessionBadgeLabel = document.getElementById('sessionBadgeLabel');
const mainApp         = document.getElementById('mainApp');

// Sidebar tabs
const tabSessions     = document.getElementById('tabSessions');
const tabInvoices     = document.getElementById('tabInvoices');
const panelSessions   = document.getElementById('panelSessions');
const panelInvoices   = document.getElementById('panelInvoices');
const refreshBtn      = document.getElementById('refreshBtn');

const SUPPORTED = new Set(['.pdf', '.jpg', '.jpeg', '.png', '.tiff']);

// ── Helpers ────────────────────────────────────────────────────────────────

function ext(filename) {
    const i = filename.lastIndexOf('.');
    return i >= 0 ? filename.slice(i).toLowerCase() : '';
}

function formatBytes(bytes) {
    if (bytes < 1024)    return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}

function fmt(val) { return val != null ? val : '—'; }

function shortId(id) {
    return id ? id.slice(0, 8) + '…' : '?';
}

function relativeDate(isoStr) {
    if (!isoStr) return '';
    const d   = new Date(isoStr);
    const now  = new Date();
    const diff = (now - d) / 1000;
    if (diff < 60)   return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return d.toLocaleDateString();
}

function fileIcon(fileExt) {
    const icons = { '.pdf': '📄', '.jpg': '🖼️', '.jpeg': '🖼️', '.png': '🖼️',
                    '.tiff': '🖼️', '.doc': '📝', '.docx': '📝' };
    return icons[fileExt] || '📎';
}

// ── Sidebar open / close ───────────────────────────────────────────────────

function openSidebar() {
    sidebar.classList.add('open');
    sidebar.setAttribute('aria-hidden', 'false');
    sidebarOverlay.classList.add('visible');
    hamburgerBtn.classList.add('open');
    hamburgerBtn.setAttribute('aria-expanded', 'true');
    // Refresh whichever panel is active
    const activeTab = sidebar.querySelector('.sidebar-tab.active');
    if (activeTab && activeTab.dataset.tab === 'invoices') {
        loadInvoices();
    } else {
        loadSessions();
    }
}

function closeSidebar() {
    sidebar.classList.remove('open');
    sidebar.setAttribute('aria-hidden', 'true');
    sidebarOverlay.classList.remove('visible');
    hamburgerBtn.classList.remove('open');
    hamburgerBtn.setAttribute('aria-expanded', 'false');
}

hamburgerBtn.addEventListener('click', () => {
    sidebar.classList.contains('open') ? closeSidebar() : openSidebar();
});

sidebarClose.addEventListener('click', closeSidebar);
sidebarOverlay.addEventListener('click', closeSidebar);

// ── Sidebar tab switching ──────────────────────────────────────────────────

function switchTab(tab) {
    if (tab === 'invoices') {
        tabInvoices.classList.add('active');
        tabSessions.classList.remove('active');
        panelInvoices.hidden = false;
        panelSessions.hidden = true;
        loadInvoices();
    } else {
        tabSessions.classList.add('active');
        tabInvoices.classList.remove('active');
        panelSessions.hidden = false;
        panelInvoices.hidden = true;
        loadSessions();
    }
}

tabSessions.addEventListener('click', () => switchTab('sessions'));
tabInvoices.addEventListener('click', () => switchTab('invoices'));

// ── Session management ─────────────────────────────────────────────────────

async function createSession() {
    const res = await fetch('/sessions', { method: 'POST' });
    if (!res.ok) throw new Error('Failed to create session');
    const data = await res.json();
    return data.session_id;
}

async function loadSessions() {
    try {
        const res = await fetch('/sessions');
        if (!res.ok) throw new Error('Failed to load sessions');
        const data = await res.json();
        renderSessionList(data.sessions);
    } catch (err) {
        sessionList.innerHTML = `<p class="session-empty" style="color:var(--danger)">Error: ${err.message}</p>`;
    }
}

function renderSessionList(sessions) {
    if (!sessions || sessions.length === 0) {
        sessionList.innerHTML = '<p class="session-empty">No sessions yet.</p>';
        return;
    }

    sessionList.innerHTML = '';
    sessions.forEach(s => {
        const card = document.createElement('div');
        card.className = 'session-card' + (s.id === currentSessionId ? ' active-session' : '');
        card.dataset.sessionId = s.id;

        const preview = s.last_message
            ? `${s.last_message.role === 'user' ? '🧑' : '🤖'} ${s.last_message.text}`
            : 'No messages yet';

        card.innerHTML = `
            <div class="session-card-top">
                <span class="session-card-id">${shortId(s.id)}</span>
                <span class="session-card-date">${relativeDate(s.created_at)}</span>
            </div>
            <div class="session-card-preview">${escapeHtml(preview)}</div>
            <div class="session-card-meta">
                <span class="session-card-pill">
                    <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24"
                            fill="none" stroke="currentColor" stroke-width="2.5">
                        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                    </svg>
                    ${s.message_count} msg${s.message_count !== 1 ? 's' : ''}
                </span>
                <span class="session-card-pill">
                    <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24"
                            fill="none" stroke="currentColor" stroke-width="2.5">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                        <polyline points="14 2 14 8 20 8"/>
                    </svg>
                    ${s.file_count} file${s.file_count !== 1 ? 's' : ''}
                </span>
            </div>
        `;

        card.addEventListener('click', () => {
            openSessionDetail(s.id);
        });

        sessionList.appendChild(card);
    });
}

async function openSessionDetail(sessionId) {
    // Fetch full session
    try {
        const res = await fetch(`/sessions/${sessionId}`);
        if (!res.ok) throw new Error('Failed to load session');
        const data = await res.json();
        renderSessionDetail(data.session);
    } catch (err) {
        alert('Error loading session: ' + err.message);
    }
}

function renderSessionDetail(session) {
    const panel = document.getElementById('panelSessions');

    panel.innerHTML = `
        <button class="back-btn" id="detailBackBtn">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24"
                    fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
                <polyline points="15 18 9 12 15 6"/>
            </svg>
            All Sessions
        </button>
        <div class="session-detail" id="sessionDetailContent">
            <!-- Switch to this session -->
            <div>
                <p class="detail-section-title">Session ID</p>
                <div style="font-size:0.72rem;font-family:monospace;color:var(--accent);word-break:break-all;margin-bottom:4px;">
                    ${escapeHtml(session.id)}
                </div>
                ${session.id !== currentSessionId ? `
                <button class="btn-new-session" id="switchSessionBtn" style="margin-top:8px;">
                    Switch to this session
                </button>` : `
                <div style="font-size:0.75rem;color:var(--success);margin-top:6px;font-weight:600;">
                    ✓ Currently active
                </div>`}
            </div>

            <!-- Uploaded files -->
            <div>
                <p class="detail-section-title">Uploaded Files (${session.files.length})</p>
                ${session.files.length === 0
                    ? `<p class="session-empty" style="padding:12px 0;">No files uploaded yet.</p>`
                    : session.files.map(f => `
                        <div class="detail-file-item">
                            <span class="detail-file-icon">${fileIcon(f.file_ext)}</span>
                            <span class="detail-file-name" title="${escapeHtml(f.filename)}">${escapeHtml(f.filename)}</span>
                            <span class="detail-file-time">${relativeDate(f.uploaded_at)}</span>
                        </div>
                    `).join('')
                }
            </div>

            <!-- Chat history -->
            <div>
                <p class="detail-section-title">Chat History (${session.messages.length})</p>
                ${session.messages.length === 0
                    ? `<p class="session-empty" style="padding:12px 0;">No messages yet.</p>`
                    : session.messages.map(m => `
                        <div class="detail-msg-item ${m.role}">
                            <div class="detail-msg-role">${m.role === 'user' ? '🧑 You' : '🤖 Agent'}</div>
                            ${escapeHtml(m.text)}
                        </div>
                    `).join('')
                }
            </div>
        </div>
    `;

    document.getElementById('detailBackBtn').addEventListener('click', () => {
        restoreSessionListPanel();
        loadSessions();
    });

    const switchBtn = document.getElementById('switchSessionBtn');
    if (switchBtn) {
        switchBtn.addEventListener('click', () => {
            switchSession(session.id);
            closeSidebar();
        });
    }
}

function restoreSessionListPanel() {
    const panel = document.getElementById('panelSessions');
    panel.innerHTML = `
        <div class="session-panel-header">
            <button class="btn-new-session" id="newSessionBtn">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24"
                        fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <line x1="12" y1="5" x2="12" y2="19"/>
                    <line x1="5" y1="12" x2="19" y2="12"/>
                </svg>
                New Session
            </button>
        </div>
        <div class="session-list" id="sessionList">
            <p class="session-empty">Loading…</p>
        </div>
    `;
    document.getElementById('newSessionBtn').addEventListener('click', handleNewSession);
}

async function handleNewSession() {
    try {
        const id = await createSession();
        switchSession(id);
        await loadSessions();
    } catch (err) {
        alert('Could not create session: ' + err.message);
    }
}

function switchSession(id) {
    currentSessionId = id;
    updateSessionBadge(id);
    // Clear chat UI so it reflects the new session context
    chatMessages.innerHTML = `
        <div class="chat-bubble agent">
            Session switched. Ask anything about your invoices in this session.
        </div>`;
}

function updateSessionBadge(id) {
    if (id) {
        sessionBadgeLabel.textContent = shortId(id);
        sessionBadge.classList.add('active');
        sessionBadge.title = `Active session: ${id}`;
    } else {
        sessionBadgeLabel.textContent = 'No session';
        sessionBadge.classList.remove('active');
    }
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// ── File staging ───────────────────────────────────────────────────────────

function stageFiles(fileArray) {
    Array.from(fileArray).forEach(file => {
        if (!SUPPORTED.has(ext(file.name))) {
            alert(`"${file.name}" is not a supported file type.`);
            return;
        }
        if (stagedFiles.has(file.name)) return;
        stagedFiles.set(file.name, file);
        renderFileItem(file);
    });
    uploadBtn.disabled = stagedFiles.size === 0;
}

function renderFileItem(file) {
    const id = `f-${fileCounter++}`;
    const li = document.createElement('li');
    li.id = id;
    li.innerHTML = `
        <span class="file-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</span>
        <span class="file-size">${formatBytes(file.size)}</span>
        <button class="remove-btn" title="Remove" data-name="${escapeHtml(file.name)}">✕</button>
    `;
    li.querySelector('.remove-btn').addEventListener('click', () => {
        stagedFiles.delete(file.name);
        li.remove();
        uploadBtn.disabled = stagedFiles.size === 0;
    });
    fileList.appendChild(li);
}

// ── Drag & Drop ────────────────────────────────────────────────────────────

dropZone.addEventListener('dragover', e => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
});

['dragleave', 'dragend'].forEach(ev =>
    dropZone.addEventListener(ev, () => dropZone.classList.remove('drag-over'))
);

dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    stageFiles(e.dataTransfer.files);
});

dropZone.addEventListener('click', e => {
    if (e.target.closest('.btn-browse')) return;
    fileInput.click();
});

fileInput.addEventListener('change', () => {
    stageFiles(fileInput.files);
    fileInput.value = '';
});

// ── Upload ─────────────────────────────────────────────────────────────────

uploadBtn.addEventListener('click', async () => {
    if (stagedFiles.size === 0) return;

    uploadBtn.disabled = true;
    uploadBtn.classList.add('loading');
    uploadBtn.innerHTML = '<span class="spinner"></span>Processing…';

    const formData = new FormData();
    stagedFiles.forEach(file => formData.append('files', file, file.name));
    if (currentSessionId) formData.append('session_id', currentSessionId);

    try {
        const res = await fetch('upload', { method: 'POST', body: formData });
        if (!res.ok) throw new Error(`Server error: ${res.status}`);
        const data = await res.json();
        renderResults(data.results);
        await new Promise(r => setTimeout(r, 1500));
        await loadInvoices();
    } catch (err) {
        alert('Upload failed: ' + err.message);
    } finally {
        uploadBtn.innerHTML = 'Upload &amp; Process';
        uploadBtn.disabled = false;
        uploadBtn.classList.remove('loading');
        stagedFiles.clear();
        fileList.innerHTML = '';
    }
});

// ── Result cards ───────────────────────────────────────────────────────────

function renderResults(results) {
    resultCards.innerHTML = '';
    results.forEach(r => {
        const ok = r.success;
        const card = document.createElement('div');
        card.className = `result-card ${ok ? 'success' : 'failure'}`;
        card.innerHTML = `
            <div class="badge">${ok ? '✅' : '❌'}</div>
            <div class="card-body">
                <div class="card-filename">${escapeHtml(r.filename ?? r.file)}</div>
                ${ok ? `
                    <div class="card-meta">
                        <div class="meta-item">Vendor <span>${fmt(r.vendor_name)}</span></div>
                        <div class="meta-item">Invoice # <span>${fmt(r.invoice_number)}</span></div>
                        <div class="meta-item">Date <span>${fmt(r.invoice_date)}</span></div>
                        <div class="meta-item">Total <span>${fmt(r.total)} ${fmt(r.currency)}</span></div>
                    </div>
                ` : `<div class="card-detail">${escapeHtml(r.error)}</div>`}
            </div>
        `;
        resultCards.appendChild(card);
    });
    resultSection.hidden = false;
    resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ── Invoices table ─────────────────────────────────────────────────────────

async function loadInvoices() {
    try {
        const res = await fetch('/invoices');
        if (!res.ok) throw new Error(`Server error: ${res.status}`);
        const data = await res.json();
        renderTable(data.invoices);
    } catch (err) {
        invoicesBody.innerHTML = `<tr><td colspan="7" class="empty" style="color:var(--danger)">Failed to load: ${err.message}</td></tr>`;
    }
}

function renderTable(invoices) {
    if (!invoices || invoices.length === 0) {
        invoicesBody.innerHTML = '<tr><td colspan="5" class="empty">No invoices yet.</td></tr>';
        return;
    }
    invoicesBody.innerHTML = invoices.map((inv, i) => `
        <tr>
            <td>${inv.id ?? i + 1}</td>
            <td>${fmt(inv.vendor_name)}</td>
            <td>${fmt(inv.invoice_number)}</td>
            <td>${fmt(inv.invoice_date)}</td>
            <td>${inv.total != null ? Number(inv.total).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}</td>
        </tr>
    `).join('');
}

refreshBtn.addEventListener('click', loadInvoices);

// ── Chat ───────────────────────────────────────────────────────────────────

function addBubble(text, role) {
    const div = document.createElement('div');
    div.className = `chat-bubble ${role}`;
    div.textContent = text;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return div;
}

async function sendMessage() {
    const text = chatInput.value.trim();
    if (!text) return;

    chatInput.value = '';
    addBubble(text, 'user');
    const thinking = addBubble('Thinking…', 'agent thinking');
    sendBtn.disabled = true;

    try {
        const res = await fetch('/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text, session_id: currentSessionId }),
        });
        if (!res.ok) throw new Error(`Server error ${res.status}`);
        const data = await res.json();
        thinking.remove();
        addBubble(data.reply || '(no response)', 'agent');
    } catch (err) {
        thinking.remove();
        addBubble('Error: ' + err.message, 'agent');
    } finally {
        sendBtn.disabled = false;
        chatInput.focus();
    }
}

sendBtn.addEventListener('click', sendMessage);
chatInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

// ── New session button (initial render) ───────────────────────────────────

newSessionBtn.addEventListener('click', handleNewSession);

// ── Init ──────────────────────────────────────────────────────────────────

async function init() {
    // Auto-create a session on page load
    try {
        const id = await createSession();
        currentSessionId = id;
        updateSessionBadge(id);
    } catch (err) {
        console.warn('Could not auto-create session:', err);
    }

    loadInvoices();
}

init();