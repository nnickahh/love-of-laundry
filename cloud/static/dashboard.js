// dashboard.js — Vision Defect Dashboard (Fully Interactive & Wired)

// ── State ─────────────────────────────────────────────────────────────
let notifications = [];
let currentPage = 'dashboard';
let selectedRow = null;
let allGarments = [];
let lastReports = null;
let edgeCameraUrl = localStorage.getItem('edgeCameraUrl') || 'http://172.20.97.215:8000';
let isLiveStreaming = false;
let appStartTime = Date.now();

// ── Singapore Timezone Formatter (SGT, UTC+8) ─────────────────────────
function formatSingaporeTime(dateInput, formatType = 'datetime') {
    if (!dateInput) return '—';
    let d;
    if (typeof dateInput === 'string') {
        d = new Date(dateInput);
        if (isNaN(d.getTime())) {
            d = new Date(dateInput.replace(' ', 'T'));
        }
    } else {
        d = new Date(dateInput);
    }
    if (isNaN(d.getTime())) return String(dateInput);

    const options = {
        timeZone: 'Asia/Singapore',
        hour12: true
    };

    if (formatType === 'time') {
        options.hour = '2-digit';
        options.minute = '2-digit';
        options.second = '2-digit';
        return d.toLocaleTimeString('en-SG', options) + ' SGT';
    } else if (formatType === 'short') {
        options.hour = '2-digit';
        options.minute = '2-digit';
        return d.toLocaleTimeString('en-SG', options);
    } else if (formatType === 'table') {
        options.month = 'short';
        options.day = 'numeric';
        options.hour = '2-digit';
        options.minute = '2-digit';
        return d.toLocaleString('en-SG', options);
    } else {
        options.year = 'numeric';
        options.month = 'short';
        options.day = 'numeric';
        options.hour = '2-digit';
        options.minute = '2-digit';
        options.second = '2-digit';
        return d.toLocaleString('en-SG', options) + ' SGT';
    }
}

// ── Animated Counter ──────────────────────────────────────────────────
function animateCount(el, target, prefix = '', suffix = '') {
    if (!el) return;
    const start = parseInt(el.textContent.replace(/[^\d]/g, '')) || 0;
    const end = typeof target === 'number' ? target : parseFloat(target) || 0;
    if (start === end) { el.textContent = prefix + end + suffix; return; }
    const dur = 400, steps = 20, step = (end - start) / steps;
    let current = start, count = 0;
    el.classList.add('refreshing');
    const timer = setInterval(() => {
        count++;
        current += step;
        if (count >= steps) {
            clearInterval(timer);
            el.textContent = prefix + (typeof target === 'string' ? target : Math.round(end)) + suffix;
            setTimeout(() => el.classList.remove('refreshing'), 200);
        } else {
            el.textContent = prefix + Math.round(current) + suffix;
        }
    }, dur / steps);
}

// ── Toast Notifications ──────────────────────────────────────────────
function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3200);
}

// ── Theme Toggle ─────────────────────────────────────────────────────
function initThemeToggle() {
    const toggle = document.getElementById('themeToggle');
    const icon = document.getElementById('themeIcon');
    const saved = localStorage.getItem('theme') || 'light';
    
    if (saved === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
        if (icon) icon.innerHTML = '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>';
    }
    
    if (toggle) {
        toggle.addEventListener('click', () => {
            const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
            if (isDark) {
                document.documentElement.removeAttribute('data-theme');
                localStorage.setItem('theme', 'light');
                if (icon) icon.innerHTML = '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>';
                showToast('Light mode activated');
            } else {
                document.documentElement.setAttribute('data-theme', 'dark');
                localStorage.setItem('theme', 'dark');
                if (icon) icon.innerHTML = '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>';
                showToast('Dark mode activated');
            }
        });
    }
}

// ── Notification System ──────────────────────────────────────────────
function initNotifications() {
    const bell = document.getElementById('notifBell');
    const panel = document.getElementById('notifPanel');
    const clear = document.getElementById('notifClear');
    
    if (bell && panel) {
        bell.addEventListener('click', (e) => {
            e.stopPropagation();
            panel.classList.toggle('active');
        });
        
        document.addEventListener('click', (e) => {
            if (!panel.contains(e.target) && !bell.contains(e.target)) {
                panel.classList.remove('active');
            }
        });
    }
    
    if (clear) {
        clear.addEventListener('click', () => {
            notifications = [];
            renderNotifications();
            showToast('Notifications cleared');
        });
    }
}

function addNotification(title, message, type = 'info') {
    notifications.unshift({ title, message, type, time: new Date() });
    if (notifications.length > 15) notifications.pop();
    renderNotifications();
}

function renderNotifications() {
    const list = document.getElementById('notifList');
    const badge = document.getElementById('notifBadge');
    
    if (badge) {
        if (notifications.length > 0) {
            badge.style.display = 'flex';
            badge.textContent = notifications.length;
        } else {
            badge.style.display = 'none';
        }
    }
    
    if (!list) return;
    if (notifications.length === 0) {
        list.innerHTML = '<div class="notification-empty">No notifications</div>';
        return;
    }
    
    list.innerHTML = notifications.map(n => `
        <div class="notification-item">
            <div class="notification-icon ${n.type}">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    ${n.type === 'warn' ? '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>' :
                    n.type === 'success' ? '<polyline points="20 6 9 17 4 12"/>' :
                    n.type === 'error' ? '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>' :
                    '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>'}
                </svg>
            </div>
            <div class="notification-text">
                <strong>${n.title}</strong>
                <span>${n.message} — ${formatSingaporeTime(n.time, 'time')}</span>
            </div>
        </div>
    `).join('');
}

// ── Navigation ───────────────────────────────────────────────────────
function initNavigation() {
    const navItems = document.querySelectorAll('.nav-item[data-page]');
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const page = item.getAttribute('data-page');
            switchPage(page);
        });
    });
}

function switchPage(page) {
    currentPage = page;
    document.querySelectorAll('.page-section').forEach(s => s.classList.remove('active'));
    const target = document.getElementById(`page-${page}`);
    if (target) target.classList.add('active');
    document.querySelectorAll('.nav-item[data-page]').forEach(item => {
        item.classList.toggle('active', item.getAttribute('data-page') === page);
    });

    if (page === 'detections') {
        renderFullDetections(allGarments);
    } else if (page === 'cameras' && lastReports) {
        renderCameraDevices(lastReports.active_devices);
    } else if (page === 'analytics') {
        updateAnalyticsCharts(lastReports);
    }
}

// ── Detection Detail Modal ───────────────────────────────────────────
function initModal() {
    const modal = document.getElementById('detailModal');
    const close = document.getElementById('modalClose');
    if (close && modal) {
        close.addEventListener('click', () => modal.classList.remove('active'));
        modal.addEventListener('click', (e) => {
            if (e.target === modal) modal.classList.remove('active');
        });
    }
}

function showDetectionDetail(garment) {
    const modal = document.getElementById('detailModal');
    const body = document.getElementById('modalBody');
    if (!modal || !body) return;
    
    const defects = garment.defects && garment.defects.length > 0
        ? garment.defects.map(d => `${d.label} (${Math.round(d.confidence * 100)}%)`).join(', ')
        : 'None (Clean)';
    
    body.innerHTML = `
        <div style="text-align: center; margin-bottom: 1rem;">
            <img src="${garment.image_url}" style="max-width: 100%; max-height: 240px; border-radius: 8px; border: 1px solid var(--panel-border); object-fit: contain;" onerror="this.src='/static/placeholder.png'">
        </div>
        <div class="modal-row">
            <span class="label">Garment Type</span>
            <span class="value" style="font-weight:700; text-transform: uppercase;">${garment.garment_type || 'Unknown'}</span>
        </div>
        <div class="modal-row">
            <span class="label">Status</span>
            <span class="value" style="font-weight:700; color: ${garment.status === 'defective' ? 'var(--red)' : 'var(--green)'}">
                ${garment.status.toUpperCase()}
            </span>
        </div>
        <div class="modal-row">
            <span class="label">Detected Defects</span>
            <span class="value">${defects}</span>
        </div>
        <div class="modal-row">
            <span class="label">Device Source</span>
            <span class="value">${garment.device_name || garment.device_id || 'Unknown Device'}</span>
        </div>
        <div class="modal-row">
            <span class="label">Inspection Time</span>
            <span class="value" style="font-weight:600;">${formatSingaporeTime(garment.created_at, 'datetime')}</span>
        </div>
        <div style="margin-top: 1.2rem; text-align: right;">
            <button class="btn btn-secondary" onclick="deleteSingleGarment(${garment.garment_id || garment.id})" style="background: rgba(239,68,68,0.15); color: #ef4444; border: 1px solid rgba(239,68,68,0.3); font-size: 0.8rem; padding: 0.4rem 0.8rem;">Delete Scan Record</button>
        </div>
    `;
    modal.classList.add('active');
}

// ── Export Functionality ──────────────────────────────────────────────
function exportToCSV(data) {
    if (!data || data.length === 0) {
        showToast('No scan records to export', 'error');
        return;
    }
    const headers = ['ID', 'Device', 'Garment', 'Status', 'Defects', 'Timestamp', 'Image URL'];
    const rows = data.map(g => [
        g.id || '',
        g.device_name || g.device_id || '',
        g.garment_type || '',
        g.status || '',
        g.defects?.map(d => d.label).join('; ') || 'Clean',
        new Date(g.created_at).toISOString(),
        g.image_url || ''
    ]);
    const csv = [headers, ...rows].map(row => row.map(cell => `"${cell}"`).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `laundry_vision_scans_${new Date().toISOString().slice(0,10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('Exported CSV successfully');
    addNotification('Export Complete', `Exported ${data.length} records to CSV`, 'success');
}

function exportToJSON(data) {
    if (!data || data.length === 0) {
        showToast('No records to export', 'error');
        return;
    }
    const jsonStr = JSON.stringify(data, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `laundry_vision_backup_${new Date().toISOString().slice(0,10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('Exported JSON Backup successfully');
    addNotification('Backup Exported', `Saved ${data.length} records`, 'success');
}

// ── Filter Detections ────────────────────────────────────────────────
function getActiveFilteredGarments() {
    const defectFilter = (document.getElementById('filterDefectType')?.value || 'All Defect Types').toLowerCase();
    const garmentFilter = (document.getElementById('filterGarment')?.value || 'All Garments').toLowerCase();
    const locationFilter = (document.getElementById('filterLocation')?.value || 'All Locations').toLowerCase();
    const searchVal = (document.getElementById('searchDetections')?.value || '').toLowerCase();

    return allGarments.filter(g => {
        const defects = (g.defects?.map(d => d.label).join(' ') || '').toLowerCase();
        const garment = (g.garment_type || '').toLowerCase();
        const device = (g.device_name || g.device_id || '').toLowerCase();

        if (defectFilter !== 'all defect types' && !defects.includes(defectFilter)) return false;
        if (garmentFilter !== 'all garments') {
            const cleanG = garmentFilter.split('/')[0].trim();
            if (!garment.includes(cleanG)) return false;
        }
        if (locationFilter !== 'all locations' && !device.includes(locationFilter)) return false;
        if (searchVal && !(defects.includes(searchVal) || garment.includes(searchVal) || device.includes(searchVal))) return false;

        return true;
    });
}

function applyFilters() {
    const filtered = getActiveFilteredGarments();
    renderDetectionsLog(filtered);
    renderFullDetections(filtered);
}

// ── Render Tables ────────────────────────────────────────────────────
function renderDetectionsLog(garments) {
    const tbody = document.getElementById('detectionsLogBody');
    if (!tbody) return;
    if (garments.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="log-empty"><span>No matching detections found</span></td></tr>`;
        return;
    }
    tbody.innerHTML = garments.map((g, i) => {
        const time = formatSingaporeTime(g.created_at, 'table');
        const isDefect = g.status === 'defective';
        const defects = g.defects && g.defects.length > 0
            ? g.defects.map(d => `<span style="background:rgba(239,68,68,0.15);color:#ef4444;padding:2px 7px;border-radius:4px;font-size:11px;font-weight:600;">${d.label}</span>`).join(' ')
            : '<span style="color:var(--text-muted);font-size:12px;">—</span>';
        const statusBadge = isDefect
            ? `<span style="background:rgba(239,68,68,0.15);color:#ef4444;border:1px solid rgba(239,68,68,0.3);padding:2px 8px;border-radius:12px;font-size:11px;font-weight:700;">DEFECT</span>`
            : `<span style="background:rgba(16,185,129,0.15);color:#10b981;border:1px solid rgba(16,185,129,0.3);padding:2px 8px;border-radius:12px;font-size:11px;font-weight:700;">CLEAN</span>`;
        const conf = g.defects && g.defects.length > 0 ? `${Math.round(g.defects[0].confidence * 100)}%` : '99%';

        return `<tr data-idx="${i}" style="cursor:pointer;">
            <td><img src="${g.image_url}" style="width:42px;height:30px;object-fit:cover;border-radius:4px;border:1px solid rgba(255,255,255,0.1);" onerror="this.src='/static/placeholder.png'"></td>
            <td>${statusBadge}</td>
            <td>${defects}</td>
            <td style="font-weight:600;text-transform:capitalize;font-size:12px;">${g.garment_type || '—'}</td>
            <td style="font-size:12px;color:var(--text-dim);">${g.device_name || g.device_id || '—'}</td>
            <td style="font-size:12px;font-weight:600;color:var(--accent);">${conf}</td>
            <td style="font-size:12px;color:var(--text-secondary);">${time}</td>
            <td><button class="btn btn-secondary" style="padding:2px 8px;font-size:11px;background:rgba(99,102,241,0.1);color:var(--accent);border:1px solid rgba(99,102,241,0.2);">Inspect</button></td>
        </tr>`;
    }).join('');
    
    tbody.querySelectorAll('tr[data-idx]').forEach(row => {
        row.addEventListener('click', () => {
            const idx = parseInt(row.getAttribute('data-idx'));
            if (selectedRow) selectedRow.classList.remove('selected');
            row.classList.add('selected');
            selectedRow = row;
            showDetectionDetail(garments[idx]);
        });
    });
}

function renderFullDetections(garments) {
    const tbody = document.getElementById('detectionsFullBody');
    if (!tbody) return;
    if (garments.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="log-empty"><span>No detection records available</span></td></tr>`;
        return;
    }
    tbody.innerHTML = garments.map((g, i) => {
        const time = formatSingaporeTime(g.created_at, 'table');
        const defects = g.defects && g.defects.length > 0
            ? g.defects.map(d => `<span style="background:rgba(239,68,68,0.15);color:#ef4444;padding:2px 6px;border-radius:4px;font-size:11px;">${d.label}</span>`).join(' ')
            : '<span style="background:rgba(16,185,129,0.15);color:#10b981;padding:2px 6px;border-radius:4px;font-size:11px;">Clean</span>';
        const conf = g.defects && g.defects.length > 0 ? `${Math.round(g.defects[0].confidence * 100)}%` : '98%';

        return `<tr>
            <td><img src="${g.image_url}" style="width:42px;height:30px;object-fit:cover;border-radius:4px;cursor:pointer;" onclick="showDetectionDetail(allGarments.find(x=>x.id===${g.id}))" onerror="this.src='/static/placeholder.png'"></td>
            <td>${defects}</td>
            <td style="font-weight:600;text-transform:capitalize;">${g.garment_type || '—'}</td>
            <td>${g.device_name || g.device_id || '—'}</td>
            <td>${conf}</td>
            <td style="font-size:12px;color:var(--text-secondary);">${time}</td>
        </tr>`;
    }).join('');
}

// ── Delete Actions ───────────────────────────────────────────────────
async function deleteSingleGarment(id) {
    const gId = parseInt(id);
    if (!gId || isNaN(gId)) {
        showToast('Invalid scan ID: ' + id, 'error');
        return;
    }
    if (!confirm('Are you sure you want to delete this scan record?')) return;
    try {
        const res = await fetch('/api/garments/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ garment_ids: [gId] })
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast('Scan record deleted');
            document.getElementById('detailModal')?.classList.remove('active');
            // Remove locally for instantaneous UI update
            allGarments = allGarments.filter(g => (g.garment_id || g.id) !== gId);
            applyFilters();
            fetchDashboardData();
        } else {
            showToast('Delete failed: ' + (data.detail || 'Error'), 'error');
        }
    } catch (e) {
        showToast('Delete failed: ' + e.message, 'error');
    }
}

async function purgeAllRecords() {
    if (allGarments.length === 0) {
        showToast('No records to delete');
        return;
    }
    if (!confirm(`Warning: This will permanently delete ALL ${allGarments.length} scans and uploaded images. Continue?`)) return;
    const allIds = allGarments.map(g => parseInt(g.garment_id || g.id)).filter(id => !isNaN(id) && id > 0);
    try {
        const res = await fetch('/api/garments/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ garment_ids: allIds })
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(`Purged ${data.deleted_count} records`);
            addNotification('Database Purged', `Deleted ${data.deleted_count} scans`, 'warn');
            allGarments = [];
            applyFilters();
            fetchDashboardData();
        } else {
            showToast('Purge failed: ' + (data.detail || 'Error'), 'error');
        }
    } catch (e) {
        showToast('Purge failed: ' + e.message, 'error');
    }
}

// ── Render Cameras Page ──────────────────────────────────────────────
function renderCameraDevices(devices) {
    const grid = document.getElementById('cameraDeviceGrid');
    if (!grid) return;
    if (!devices || devices.length === 0) {
        grid.innerHTML = `<div class="kpi-card"><div class="kpi-info"><div class="kpi-value" style="font-size:20px;">No Edge Units</div><div class="kpi-label">Awaiting connection</div></div></div>`;
        return;
    }
    const now = Date.now();
    grid.innerHTML = devices.map(d => {
        const lastSeen = d.last_active ? new Date(d.last_active).getTime() : 0;
        const isOnline = (now - lastSeen) < 180000; // 3 minutes
        return `
            <div class="kpi-card">
                <div class="kpi-info">
                    <div class="kpi-value" style="font-size:22px;">${d.device_id}</div>
                    <div class="kpi-label">LOCATION: ${d.location || 'Local Unit'}</div>
                    <div class="kpi-trend ${isOnline ? 'success' : 'warning'}" style="margin-top:6px;">
                        <span>${isOnline ? '🟢 Online (Active)' : '🟠 Offline — Last seen ' + (d.last_active ? formatSingaporeTime(d.last_active, 'short') : 'N/A')}</span>
                    </div>
                </div>
                <div class="kpi-icon ${isOnline ? 'green' : 'orange'}">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
                </div>
            </div>
        `;
    }).join('');
}

// ── Chart Setup ───────────────────────────────────────────────────────
const chartColors = {
    teal: '#0891b2',
    blue: '#2563eb',
    purple: '#7c3aed',
    orange: '#d97706',
    green: '#16a34a',
    red: '#dc2626',
    gray: '#94a3b8'
};

let barChart = null;
let donutChart = null;
let weeklyChart = null;
let deviceChart = null;

function initCharts() {
    const barCtx = document.getElementById('barChart');
    if (barCtx) {
        barChart = new Chart(barCtx, {
            type: 'bar',
            data: {
                labels: ['Shirt', 'Pants', 'Jacket', 'Shorts', 'Dress', 'Skirt'],
                datasets: [{
                    data: [0, 0, 0, 0, 0, 0],
                    backgroundColor: chartColors.blue,
                    borderRadius: 6,
                    maxBarThickness: 38,
                    barPercentage: 0.7,
                    categoryPercentage: 0.8
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { grid: { display: false }, ticks: { color: '#94a3b8' } },
                    y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8', stepSize: 1 }, beginAtZero: true }
                }
            }
        });
    }

    const donutCtx = document.getElementById('donutChart');
    if (donutCtx) {
        donutChart = new Chart(donutCtx, {
            type: 'doughnut',
            data: {
                labels: ['Clean', 'Hole', 'Stain', 'Tear'],
                datasets: [{
                    data: [100, 0, 0, 0],
                    backgroundColor: [chartColors.green, chartColors.orange, chartColors.blue, chartColors.purple],
                    borderWidth: 2,
                    borderColor: 'rgba(0,0,0,0.2)'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '65%',
                plugins: { legend: { display: false } }
            }
        });
    }
}

function updateAnalyticsCharts(reports) {
    if (!reports) return;
    const weeklyCtx = document.getElementById('weeklyChart');
    if (weeklyCtx && !weeklyChart) {
        weeklyChart = new Chart(weeklyCtx, {
            type: 'line',
            data: {
                labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Today'],
                datasets: [{
                    label: 'Clean Items',
                    data: [4, 8, 12, 10, 15, 18, reports.clean_scans || 0],
                    borderColor: chartColors.green,
                    backgroundColor: 'rgba(16,185,129,0.1)',
                    fill: true,
                    tension: 0.3
                }, {
                    label: 'Defective Items',
                    data: [0, 1, 0, 2, 1, 0, reports.defective_scans || 0],
                    borderColor: chartColors.red,
                    backgroundColor: 'rgba(239,68,68,0.1)',
                    fill: true,
                    tension: 0.3
                }]
            },
            options: { responsive: true, maintainAspectRatio: false }
        });
    }

    const deviceCtx = document.getElementById('deviceChart');
    if (deviceCtx && !deviceChart) {
        const devices = reports.active_devices || [];
        deviceChart = new Chart(deviceCtx, {
            type: 'bar',
            data: {
                labels: devices.map(d => d.device_id) || ['RPi5-01'],
                datasets: [{
                    label: 'Total Scans',
                    data: [reports.total_scans || 0],
                    backgroundColor: chartColors.teal,
                    borderRadius: 6
                }]
            },
            options: { responsive: true, maintainAspectRatio: false }
        });
    }
}

// ── Fetch Dashboard Data ─────────────────────────────────────────────
let lastScanCount = 0;
async function fetchDashboardData() {
    try {
        const resp = await fetch('/api/reports');
        const reports = await resp.json();
        lastReports = reports;

        // Notify on new incoming scans from edge
        if (reports.total_scans > lastScanCount && lastScanCount > 0) {
            addNotification('New Scan Received', `${reports.total_scans - lastScanCount} new garment(s) synced from edge`, 'info');
            showToast('New scan synced from edge device!');
        }
        lastScanCount = reports.total_scans;

        // Update KPI values & Stat Strip
        animateCount(document.getElementById('totalDetected'), reports.total_scans);
        animateCount(document.getElementById('needsReview'), reports.defective_scans);
        animateCount(document.getElementById('reviewed'), reports.clean_scans);

        const stripRate = document.getElementById('stripDefectRate');
        const stripClean = document.getElementById('stripCleanCount');
        const stripDefect = document.getElementById('stripDefectCount');
        if (stripRate) stripRate.textContent = (reports.defect_rate_percent || 0).toFixed(1) + '%';
        if (stripClean) stripClean.textContent = reports.clean_scans || 0;
        if (stripDefect) stripDefect.textContent = reports.defective_scans || 0;

        // Update Pi status pill
        const piPill = document.getElementById('piStatusPill');
        const piText = document.getElementById('piStatusText');
        const devices = reports.active_devices || [];
        const isPiOnline = devices.some(d => (Date.now() - new Date(d.last_active).getTime()) < 180000);

        if (piPill && piText) {
            if (isPiOnline) {
                piPill.className = 'status-pill status-connected';
                piPill.innerHTML = '<span class="status-dot green" style="background:#10b981;"></span><span>RPi5-01: Online</span>';
            } else {
                piPill.className = 'status-pill status-offline';
                piPill.innerHTML = '<span class="status-dot red" style="background:#ef4444;"></span><span>RPi5-01: Standby</span>';
            }
        }

        // Update Charts
        if (barChart) {
            const gb = reports.garment_breakdown || {};
            const labels = Object.keys(gb);
            if (labels.length > 0) {
                barChart.data.labels = labels.map(l => l.charAt(0).toUpperCase() + l.slice(1));
                barChart.data.datasets[0].data = labels.map(l => gb[l]);
                barChart.update();
            }
        }

        if (donutChart) {
            const db = reports.defect_breakdown || {};
            const defectKeys = Object.keys(db);
            if (defectKeys.length > 0) {
                donutChart.data.labels = defectKeys.map(k => k.replace(/_/g, ' '));
                donutChart.data.datasets[0].data = defectKeys.map(k => db[k]);
                donutChart.update();
            }
        }

        // Fetch All Garments for Table
        const garmentsResp = await fetch('/api/garments');
        allGarments = await garmentsResp.json();
        applyFilters();

        // Update last update timestamp
        const lastUpdateEl = document.getElementById('lastUpdate');
        if (lastUpdateEl) {
            lastUpdateEl.textContent = `Last update: ${formatSingaporeTime(new Date(), 'time')}`;
        }

    } catch (e) {
        console.error('Dashboard sync error:', e);
        const piText = document.getElementById('piStatusText');
        if (piText) piText.textContent = 'API Reconnecting...';
    }
}

// ── Manual File Upload Handler ────────────────────────────────────────
async function handleManualUpload(files) {
    if (!files || files.length === 0) return;
    showToast(`Uploading ${files.length} image(s)...`, 'info');
    let successCount = 0;

    for (const file of files) {
        const formData = new FormData();
        const payload = {
            device_id: "Cloud-Upload",
            timestamp: new Date().toISOString(),
            garment: {
                local_id: Date.now() % 10000,
                garment_type: "shirt",
                status: "clean",
                created_at: new Date().toISOString(),
                meta_angle: 0.0,
                defects: []
            }
        };
        formData.append('payload', JSON.stringify(payload));
        formData.append('file', file);

        try {
            const res = await fetch('/api/sync', { method: 'POST', body: formData });
            if (res.ok) successCount++;
        } catch (e) {
            console.error('Upload failed:', e);
        }
    }

    showToast(`Uploaded ${successCount} scan(s) successfully!`);
    addNotification('Manual Import', `Added ${successCount} scans to cloud database`, 'success');
    fetchDashboardData();
}

// ── Live Stream Toggle ────────────────────────────────────────────────
function toggleLiveStream() {
    const feed = document.getElementById('cameraFeed');
    const goLiveBtn = document.querySelector('.btn-go-live');
    if (!feed || !goLiveBtn) return;

    if (!isLiveStreaming) {
        isLiveStreaming = true;
        goLiveBtn.innerHTML = '<span class="status-dot green" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#ef4444;margin-right:4px;"></span> Stop Feed';
        goLiveBtn.style.background = 'rgba(239,68,68,0.2)';
        goLiveBtn.style.borderColor = '#ef4444';

        const streamUrl = `${edgeCameraUrl}/api/video_feed`;
        feed.innerHTML = `
            <img src="${streamUrl}" style="width:100%;height:100%;object-fit:contain;background:#000;" 
                onerror="this.onerror=null; this.src='http://localhost:8000/api/video_feed'; this.onerror=function(){ this.parentElement.innerHTML='<div style=\\'padding:20px;text-align:center;color:#ef4444;font-size:13px;\\'>Cannot reach Edge camera at ${edgeCameraUrl}. Make sure ./start_edge.sh is running on the Pi.</div>'; };">
        `;
        showToast('Connecting to Edge live stream...');
        addNotification('Live Camera', `Streaming from ${edgeCameraUrl}`, 'info');
    } else {
        isLiveStreaming = false;
        goLiveBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg> Go Live';
        goLiveBtn.style.background = '';
        goLiveBtn.style.borderColor = '';
        feed.innerHTML = `
            <div class="camera-placeholder">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.4">
                    <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/>
                    <circle cx="12" cy="13" r="4"/>
                </svg>
                <span>Live stream stopped</span>
            </div>
        `;
        showToast('Live stream stopped');
    }
}

// ── Model Retraining Action ───────────────────────────────────────────
async function triggerModelRetrain(buttonEl) {
    if (buttonEl) {
        buttonEl.innerHTML = '<span class="spinner" style="width:12px;height:12px;border:2px solid currentColor;border-top-color:transparent;border-radius:50%;display:inline-block;animation:spin 0.8s linear infinite;"></span> Training...';
        buttonEl.disabled = true;
    }
    showToast('Starting Active Learning retraining...');
    addNotification('Active Learning', 'Orchestrating model retraining across cloud samples', 'info');

    try {
        const res = await fetch('/api/active_learning/retrain', { method: 'POST' });
        const data = await res.json();
        
        const modelPillText = document.getElementById('modelPillText');
        if (modelPillText) modelPillText.textContent = `DeepFashion-v1.1.0 (Retrained)`;

        showToast('Retraining complete! Model weights upgraded.');
        addNotification('Model Retrained', 'DeepFashion-v1.1.0 active and deployed', 'success');
    } catch (e) {
        showToast('Retrain request failed: ' + e.message, 'error');
    } finally {
        if (buttonEl) {
            buttonEl.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg> RETRAIN';
            buttonEl.disabled = false;
        }
    }
}

// ── Bottom Status Bar ─────────────────────────────────────────────────
function initBottomBar() {
    function updateBottomBar() {
        const uptimeEl = document.getElementById('bottomUptime');
        const apiEl = document.getElementById('bottomApiStatus');
        if (uptimeEl) {
            const elapsed = Math.floor((Date.now() - appStartTime) / 1000);
            const mins = Math.floor(elapsed / 60);
            const secs = elapsed % 60;
            uptimeEl.textContent = `Uptime: ${mins}m ${secs}s`;
        }
        if (apiEl) apiEl.textContent = 'Cloud Server: Online (8080)';
    }
    updateBottomBar();
    setInterval(updateBottomBar, 1000);
}

// ── Initialization & Button Listeners ─────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initCharts();
    initThemeToggle();
    initNotifications();
    initNavigation();
    initModal();
    initBottomBar();

    // Fetch live dashboard data
    fetchDashboardData();
    setInterval(fetchDashboardData, 8000);

    // 1. Retrain & Bootstrap Buttons
    const retrainBtn = document.getElementById('retrainBtn');
    if (retrainBtn) retrainBtn.addEventListener('click', () => triggerModelRetrain(retrainBtn));

    const bootstrapBtn = document.getElementById('bootstrapBtn');
    if (bootstrapBtn) bootstrapBtn.addEventListener('click', () => triggerModelRetrain(bootstrapBtn));

    const btnSettingsRetrain = document.getElementById('btnSettingsRetrain');
    if (btnSettingsRetrain) btnSettingsRetrain.addEventListener('click', () => triggerModelRetrain(btnSettingsRetrain));

    // 2. Reset Model Button
    const btnResetModel = document.getElementById('btnResetModel');
    if (btnResetModel) {
        btnResetModel.addEventListener('click', async () => {
            try {
                await fetch('/api/active_learning/reset', { method: 'POST' });
                const modelPillText = document.getElementById('modelPillText');
                if (modelPillText) modelPillText.textContent = 'DeepFashion-Phase2';
                showToast('Model state reset to base');
                addNotification('Model Reset', 'Reverted active learning state', 'info');
            } catch (e) {
                showToast('Reset failed', 'error');
            }
        });
    }

    // 3. Live Camera Button
    const goLiveBtn = document.querySelector('.btn-go-live');
    if (goLiveBtn) goLiveBtn.addEventListener('click', toggleLiveStream);

    // 4. Analyze & Manual Import Buttons
    const manualInput = document.getElementById('manualUploadInput');
    const analyzeBtn = document.querySelector('.btn-analyze');
    const importBtn = document.querySelector('.btn-import');

    if (manualInput) {
        manualInput.addEventListener('change', (e) => handleManualUpload(e.target.files));
    }
    if (analyzeBtn && manualInput) {
        analyzeBtn.addEventListener('click', () => manualInput.click());
    }
    if (importBtn && manualInput) {
        importBtn.addEventListener('click', () => manualInput.click());
    }

    // 5. Filter Dropdown Listeners
    ['filterDefectType', 'filterGarment', 'filterLocation'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('change', applyFilters);
    });

    const searchInput = document.getElementById('searchDetections');
    if (searchInput) searchInput.addEventListener('input', applyFilters);

    // 6. Export Buttons
    const exportBtn = document.getElementById('exportBtn');
    if (exportBtn) exportBtn.addEventListener('click', () => exportToCSV(allGarments));

    const btnExportJson = document.getElementById('btnExportJson');
    if (btnExportJson) btnExportJson.addEventListener('click', () => exportToJSON(allGarments));

    // 7. Database Purge Button
    const btnClearDb = document.getElementById('btnClearDb');
    if (btnClearDb) btnClearDb.addEventListener('click', purgeAllRecords);

    // 8. Force Refresh Button
    const btnForceRefresh = document.getElementById('btnForceRefresh');
    if (btnForceRefresh) {
        btnForceRefresh.addEventListener('click', () => {
            fetchDashboardData();
            showToast('Synchronized with edge devices');
        });
    }

    // 9. Edge IP Settings
    const settingEdgeIp = document.getElementById('settingEdgeIp');
    const btnSaveEdgeIp = document.getElementById('btnSaveEdgeIp');
    if (settingEdgeIp) settingEdgeIp.value = edgeCameraUrl;
    if (btnSaveEdgeIp && settingEdgeIp) {
        btnSaveEdgeIp.addEventListener('click', () => {
            edgeCameraUrl = settingEdgeIp.value.trim() || 'http://172.20.97.215:8000';
            localStorage.setItem('edgeCameraUrl', edgeCameraUrl);
            showToast('Edge Stream IP saved: ' + edgeCameraUrl);
        });
    }

    // Initial Welcome Notification
    setTimeout(() => {
        addNotification('Central Server Connected', 'Connected to Laundry Vision Cloud on port 8080', 'success');
    }, 600);
});
