const stagedFiles = new Map();
let fileCounter = 0;

/* DOM Refs*/
const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const fileList = document.getElementById('fileList');
const uploadBtn = document.getElementById('uploadBtn');
const resultSection = document.getElementById('resultSection');
const resultCards = document.getElementById('resultCards');
const invoicesBody = document.getElementById('invoicesBody');
const refreshBtn = document.getElementById('refreshBtn');

const SUPPORTED = new Set(['.pdf', '.jpg', '.jpeg', '.png', '.tiff']);

/* Helper functions*/

/* Returns the lower case file extension for a given file name, */
function ext(filename) {
    const i = filename.lastIndexOf('.');
    return i >= 0 ? filename.slice(i).toLowerCase() : '';
}

/* Converts a raw byte count into human readable string (B / KB / MB)*/
function formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}

/* Returns the value as-is, or an em-dash when the value is null / undefined. */
function fmt(val) { return val != null ? val : '-';}

/* Staging files */
function stageFiles (fileArray) {
    Array.from(fileArray).forEach(file => {
        if (!SUPPORTED.has(ext(file.name))) {
            alert(`"${file.name}" is not supported file type.`);
            return;
        }

        if (stagedFiles.has(file.name)) return;
        stagedFiles.set(file.name, file);
        renderFileItem(file);
    });
    uploadBtn.disabled = stagedFiles.size === 0;
}

/* Renders a file */
function renderFileItem(file) {
    const id = `f-${fileCounter++}`;
    const li = document.createElement('li');
    li.id = id;
    li.innerHTML = `
    <span class = "file-name" title="${file.name}">${file.name}</span>
    <span class = "file-size">${formatBytes(file.size)}</span>
    <button class="remove-btn" title="Remove" data-name="${file.name}">x</button>
    `;
    li.querySelector('.remove-btn').addEventListener('click', () => {
        stagedFiles.delete(file.name);
        li.remove();
        uploadBtn.disabled = stagedFiles.size === 0;
    });
    fileList.appendChild(li);
}

/* Drag & Drop */
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
    stageFiles(e.dataTransfer.files)
});

dropZone.addEventListener('click', e => {
    if(e.target.closest('.btn-browse')) return;
    fileInput.click();
});

fileInput.addEventListener('change', () => {
    stageFiles(fileInput.files);
    fileInput.value = '';
});

/* Upload functionality */
uploadBtn.addEventListener('click', async () => {
    if (stagedFiles.size == 0) return;
    uploadBtn.disabled = true;
    uploadBtn.classList.add('loading');
    uploadBtn.innerHTML = '<span class="spinner"></span>Processing...';

    const formData = new FormData();
    stagedFiles.forEach(file => formData.append('files', file, file.name));

    try {
        const res = await fetch('upload', { method: 'POST', body: formData});
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

function renderResults(results) {
    resultCards.innerHTML = '';
    results.forEach(r => {
        const ok = r.success;
        const card = document.createElement('div');
        card.className = `result-card ${ok ? 'success' : 'failure'}`;
        card.innerHTML = `
            <div class="badge">${ok ? '✅' : '❌'}</div>
            <div class="card-body">
                <div class="card-filename">${r.filename ?? r.file}</div>
                ${ok ? `
                    <div class="card-meta">
                        <div class="meta-item">Vendor <span>${fmt(r.vendor_name)}</span></div>
                        <div class="meta-item">Invoice # <span>${fmt(r.invoice_number)}</span></div>
                        <div class="meta-item"> Date <span>${fmt(r.invoice_date)}</span></div>
                        <div class="meta-item"> ID <span>#${fmt(r.total)} ${fmt(r.currency)}</span></div>
                    </div>
                    ` : `<div class="card-detail">${r.error}</div>`}
                </div>
            `;
            resultCards.appendChild(card);
    });
    resultSection.hidden = false;
    resultSection.scrollIntoView({ behavior: 'smooth', block: 'start'});
}

async function loadInvoices() {
    try {
        const res = await fetch('/invoices');
        if (!res.ok) throw new Error(`Server error: ${res.status}`);
        const data = await res.json();
        renderTable(data.invoices);
    } catch (err) {
        invoicesBody.innerHTML = `<tr> <td colspan="empty" style="color:var(--danger)">Failed to load: ${err.message}</td></tr>`;
    }
    
}

function renderTable(invoices) {
    if (!invoices || invoices.length == 0) {
        invoicesBody.innerHTML = '<tr><td colspan="7" class="empty">No invoices yet.</td></tr>';
        return;
    }

    invoicesBody.innerHTML = invoices.map((inv, i) => `
    <tr>
        <td>${inv.id ?? i + 1}</td>
        <td>${fmt(inv.vendor_name)}</td>
        <td>${fmt(inv.invoice_number)}</td>
        <td>${fmt(inv.invoice_date)}</td>
        <td>${fmt(inv.due_date)}</td>
        <td>${inv.total != null ? Number(inv.total).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}): '-'}</td>
        <td>${fmt(inv.currency)}</td>
    </tr>
    `).join('');
}

refreshBtn.addEventListener('click', loadInvoices);

/* Chat functionality */

const chatMessages = document.getElementById('chatMessages');
const chatInput = document.getElementById('chatInput');
const sendBtn = document.getElementById('sendBtn');

function addBuble(text, role) {
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
    addBuble(text, 'user');

    const thinking = addBuble('Thinking...', 'agent thinking');

    sendBtn.disabled = true;

    try {
        const res = await fetch('/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text }),
        });
        if (!res.ok) throw new Error(`Server error ${res.status}`);
        const data = await res.json();
        thinking.remove();
        addBuble(data.reply || '(no response)', 'agent');
    } catch (err) {
        thinking.remove();
        addBuble('Error: ' + err.message, 'agent');
    } finally {
        sendBtn.disabled = false;
        chatInput.focus();
    }
}

sendBtn.addEventListener('click', sendMessage);
chatInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftkey) {
        e.preventDefault();
        sendMessage();
    }
});


/* Init */ 
loadInvoices();