// dashboard.js — v2
// Cloud Admin Dashboard: data fetching, animated stats, live-view links, activity ticker

// ── Edge Unit URL Registry ─────────────────────────────────────────────────────
// Maps device_id -> edge server base URL for live-view deep-links.
// Adjust these to match your actual edge device hostnames/IPs.
const EDGE_URL_MAP = {
    'Van-01': 'http://localhost:8000',
    'Van-02': 'http://192.168.1.101:8000',
    'Van-03': 'http://192.168.1.102:8000',
};

// ── Multi-Select Deletion State ───────────────────────────────────────────────
const selectedGarmentIds = new Set();
let allLoadedGarmentIds = [];

function updateDeleteButtonState() {
    const btnSelectAll = document.getElementById('btnSelectAll');
    const btnDeselectAll = document.getElementById('btnDeselectAll');
    const btnDelete = document.getElementById('btnDeleteSelected');
    
    if (selectedGarmentIds.size > 0) {
        btnDelete.style.display = 'inline-block';
        btnDelete.textContent = `🗑 Delete Selected (${selectedGarmentIds.size})`;
        btnDeselectAll.style.display = 'inline-block';
    } else {
        btnDelete.style.display = 'none';
        btnDeselectAll.style.display = 'none';
    }
}

function toggleGarmentSelection(garmentId, cardEl) {
    if (selectedGarmentIds.has(garmentId)) {
        selectedGarmentIds.delete(garmentId);
        cardEl.classList.remove('selected');
    } else {
        selectedGarmentIds.add(garmentId);
        cardEl.classList.add('selected');
    }
    updateDeleteButtonState();
}

function selectAllGarments() {
    allLoadedGarmentIds.forEach(id => selectedGarmentIds.add(id));
    document.querySelectorAll('.gallery-card').forEach(card => {
        card.classList.add('selected');
    });
    updateDeleteButtonState();
}

function deselectAllGarments() {
    selectedGarmentIds.clear();
    document.querySelectorAll('.gallery-card').forEach(card => {
        card.classList.remove('selected');
    });
    updateDeleteButtonState();
}

async function deleteSelectedGarments() {
    const count = selectedGarmentIds.size;
    if (count === 0) return;
    
    if (!confirm(`Are you sure you want to delete the ${count} selected garment record(s) and their images from the central cloud server?`)) {
        return;
    }
    
    const idsToDelete = Array.from(selectedGarmentIds);
    try {
        const resp = await fetch('/api/garments/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ garment_ids: idsToDelete })
        });
        const result = await resp.json();
        if (result.status === 'success') {
            pushActivity(`Successfully deleted ${result.deleted_count} garment(s) and ${result.deleted_files} image file(s).`, 'var(--color-defect)');
            selectedGarmentIds.clear();
            updateDeleteButtonState();
            fetchCloudData();
        } else {
            alert(`Error deleting garments: ${result.detail || 'unknown error'}`);
        }
    } catch (err) {
        console.error('Delete failed:', err);
        alert('Failed to connect to central server to delete garments.');
    }
}

function getEdgeUrl(deviceId) {
    return EDGE_URL_MAP[deviceId] || null;
}

// ── Animated Counter ──────────────────────────────────────────────────────────
function animateCount(el, target, prefix = '', suffix = '') {
    const start   = parseInt(el.textContent.replace(/[^\d]/g, '')) || 0;
    const end     = typeof target === 'number' ? target : parseFloat(target) || 0;
    const dur     = 600;
    const steps   = 25;
    const step    = (end - start) / steps;
    let   current = start;
    let   count   = 0;

    const timer = setInterval(() => {
        count++;
        current += step;
        if (count >= steps) {
            clearInterval(timer);
            el.textContent = prefix + (typeof target === 'string' ? target : Math.round(end)) + suffix;
        } else {
            el.textContent = prefix + Math.round(current) + suffix;
        }
    }, dur / steps);
}

// ── Activity Ticker ───────────────────────────────────────────────────────────
const activityLog = [];

function pushActivity(message, color = 'var(--accent)') {
    activityLog.unshift({ message, color, time: new Date() });
    if (activityLog.length > 20) activityLog.pop();
    renderActivityTicker();
}

function renderActivityTicker() {
    const ticker = document.getElementById('activityTicker');
    if (!ticker) return;
    ticker.innerHTML = '';
    if (activityLog.length === 0) {
        ticker.innerHTML = `<div style="text-align:center; color:var(--text-secondary); font-size:0.85rem; padding:1rem 0;">No recent activity.</div>`;
        return;
    }
    activityLog.forEach(entry => {
        const item = document.createElement('div');
        item.className = 'ticker-item';
        const timeStr = entry.time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        item.innerHTML = `
            <span class="ticker-dot" style="background: ${entry.color};"></span>
            <span style="flex:1;">${entry.message}</span>
            <span style="font-size:0.7rem; opacity:0.5; flex-shrink:0;">${timeStr}</span>
        `;
        ticker.appendChild(item);
    });
}

// ── Main Data Fetch ──────────────────────────────────────────────────────────
let _prevTotalScans = 0;

async function fetchCloudData() {
    try {
        // ── 1. Metrics ──────────────────────────────────────────────────────
        const reportsResp = await fetch('/api/reports');
        const reports     = await reportsResp.json();

        animateCount(document.getElementById('lblTotalScans'),    reports.total_scans);
        animateCount(document.getElementById('lblDefectPercent'), reports.defect_rate_percent, '', '%');
        animateCount(document.getElementById('lblCleanCount'),    reports.clean_scans);
        animateCount(document.getElementById('lblDefectCount'),   reports.defective_scans);

        // Activity ping if new scans arrived
        if (reports.total_scans > _prevTotalScans && _prevTotalScans > 0) {
            const diff = reports.total_scans - _prevTotalScans;
            pushActivity(`${diff} new garment${diff > 1 ? 's' : ''} synced from edge units`, 'var(--color-clean)');
        }
        _prevTotalScans = reports.total_scans;

        // Update last refresh time
        document.getElementById('lastRefreshTime').textContent = new Date().toLocaleTimeString();

        // ── 2. Edge Device List ─────────────────────────────────────────────
        const deviceList = document.getElementById('deviceList');
        const badge      = document.getElementById('deviceCountBadge');
        deviceList.innerHTML = '';

        if (reports.active_devices.length === 0) {
            deviceList.innerHTML = `<div style="text-align:center; color:var(--text-secondary); padding:1.5rem 0; font-size:0.88rem;">No active Edge units registered.</div>`;
            badge.textContent = '0 active';
        } else {
            badge.textContent = `${reports.active_devices.length} active`;
            reports.active_devices.forEach(dev => {
                const lastSeen  = new Date(dev.last_active);
                const ageMins   = Math.round((Date.now() - lastSeen) / 60000);
                const isRecent  = ageMins < 5;
                const dotColor  = isRecent ? 'var(--color-clean)' : 'var(--color-warn)';
                const timeLabel = isRecent ? `${ageMins}m ago` : lastSeen.toLocaleTimeString();
                const edgeUrl   = getEdgeUrl(dev.name || dev.device_id);

                const row = document.createElement('div');
                row.className = 'device-row';
                row.innerHTML = `
                    <div style="display:flex; align-items:center; gap:0.7rem; flex:1; min-width:0;">
                        <span style="width:9px; height:9px; border-radius:50%; background:${dotColor}; box-shadow:0 0 6px ${dotColor}; flex-shrink:0;"></span>
                        <div style="min-width:0;">
                            <div style="font-weight:700; font-size:0.88rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                                💻 ${dev.name || dev.device_id}
                            </div>
                            <div style="font-size:0.72rem; color:var(--text-secondary);">${dev.location || 'No location'} · ${timeLabel}</div>
                        </div>
                    </div>
                    <div style="display:flex; align-items:center; gap:0.5rem; flex-shrink:0;">
                        ${edgeUrl
                            ? `<a class="live-view-btn" href="${edgeUrl}" target="_blank" rel="noopener">📹 Live View</a>`
                            : `<span style="font-size:0.72rem; color:var(--text-secondary);">No URL</span>`
                        }
                    </div>
                `;
                deviceList.appendChild(row);
            });
        }

        // ── 3. Defect Breakdown ─────────────────────────────────────────────
        const defectStatsList = document.getElementById('defectStatsList');
        defectStatsList.innerHTML = '';
        const breakdownKeys = Object.keys(reports.defect_breakdown || {});
        const maxVal = Math.max(1, ...Object.values(reports.defect_breakdown || {}));

        if (breakdownKeys.length === 0) {
            defectStatsList.innerHTML = `<div style="text-align:center; color:var(--text-secondary); padding:1.5rem 0; font-size:0.88rem;">No defects logged yet.</div>`;
        } else {
            breakdownKeys.sort((a, b) => reports.defect_breakdown[b] - reports.defect_breakdown[a]);
            breakdownKeys.forEach(k => {
                const val  = reports.defect_breakdown[k];
                const pct  = Math.round((val / maxVal) * 100);
                const row  = document.createElement('div');
                row.className = 'defect-stat-row';
                row.innerHTML = `
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="font-weight:700; color:#f87171; font-size:0.85rem;">⚠ ${k.replace(/_/g, ' ').toUpperCase()}</span>
                        <span style="font-size:0.8rem; color:var(--color-defect); font-weight:700;">${val}</span>
                    </div>
                    <div class="defect-stat-bar">
                        <div class="defect-stat-bar-fill" style="width: 0%;" data-width="${pct}"></div>
                    </div>
                `;
                defectStatsList.appendChild(row);

                // Animate bar fill on next tick
                requestAnimationFrame(() => {
                    const fill = row.querySelector('.defect-stat-bar-fill');
                    if (fill) fill.style.width = pct + '%';
                });
            });
        }

        // ── 4. Garment Gallery ──────────────────────────────────────────────
        const garmentsResp = await fetch('/api/garments');
        const garments     = await garmentsResp.json();
        const gallery      = document.getElementById('garmentGallery');
        gallery.innerHTML  = '';

        if (garments.length === 0) {
            allLoadedGarmentIds = [];
            selectedGarmentIds.clear();
            updateDeleteButtonState();
            gallery.innerHTML = `
                <div style="grid-column:1/-1; text-align:center; color:var(--text-secondary); padding:5rem 0; font-size:0.9rem;">
                    <div style="font-size:2.5rem; margin-bottom:1rem; opacity:0.3;">📦</div>
                    No inspected garments found. Sync data from Edge units first.
                </div>`;
        } else {
            allLoadedGarmentIds = garments.map(g => g.garment_id);
            // Clean up selections that no longer exist
            for (const id of selectedGarmentIds) {
                if (!allLoadedGarmentIds.includes(id)) {
                    selectedGarmentIds.delete(id);
                }
            }
            updateDeleteButtonState();

            garments.forEach((g, i) => {
                const isDefect    = g.status === 'defective';
                const badgeColor  = isDefect ? 'rgba(240,74,110,0.9)' : 'rgba(16,185,129,0.9)';
                const shadowColor = isDefect ? 'rgba(240,74,110,0.4)' : 'rgba(16,185,129,0.4)';
                const timeStr     = new Date(g.created_at).toLocaleString([], {
                    month: 'short', day: 'numeric',
                    hour: '2-digit', minute: '2-digit'
                });

                let defectPills = '';
                if (isDefect && g.defects && g.defects.length > 0) {
                    defectPills = '<div style="display:flex; flex-wrap:wrap; gap:3px; margin-top:6px;">';
                    g.defects.forEach(d => {
                        defectPills += `<span style="background:rgba(240,74,110,0.12); border:1px solid rgba(240,74,110,0.3); color:#f87171; padding:2px 6px; border-radius:4px; font-size:0.68rem; font-weight:600;">${d.label}</span>`;
                    });
                    defectPills += '</div>';
                }

                const card = document.createElement('div');
                card.className = 'gallery-card';
                if (selectedGarmentIds.has(g.garment_id)) {
                    card.classList.add('selected');
                }
                card.style.animationDelay = `${i * 0.05}s`;
                card.innerHTML = `
                    <div class="gallery-img-container">
                        <div class="gallery-checkbox-container"></div>
                        <img src="${g.image_url}" class="gallery-img" alt="${g.garment_type}" loading="lazy">
                        <span class="gallery-badge" style="background:${badgeColor}; box-shadow:0 2px 12px ${shadowColor};">
                            ${isDefect ? '⚠ DEFECT' : '✓ CLEAN'}
                        </span>
                    </div>
                    <div class="gallery-info">
                        <div style="font-weight:800; font-size:0.9rem; display:flex; justify-content:space-between; align-items:flex-start; gap:4px;">
                            <span>${g.garment_type.toUpperCase()}</span>
                            <span style="color:var(--text-secondary); font-size:0.68rem; font-weight:500; flex-shrink:0;">#${g.garment_id}</span>
                        </div>
                        <div style="font-size:0.72rem; color:var(--text-secondary); margin-top:4px;">
                            📡 ${g.device_name || g.device_id}
                        </div>
                        <div style="font-size:0.7rem; color:var(--text-secondary);">🕐 ${timeStr}</div>
                        ${defectPills}
                    </div>
                `;
                card.addEventListener('click', () => toggleGarmentSelection(g.garment_id, card));
                gallery.appendChild(card);
            });
        }

        // ── 5. Update Labeling Queue ─────────────────────────────────────────
        updateLabelingQueue(garments);

    } catch (e) {
        console.error('Cloud dashboard fetch failed:', e);
        pushActivity('⚠ Cloud data fetch failed — check server connection', 'var(--color-defect)');
    }
}

// ── Tab Switching ────────────────────────────────────────────────────────────
function switchTab(tabName) {
    const dashView = document.getElementById('dashboardView');
    const alView   = document.getElementById('activeLearningView');
    const btnDash  = document.getElementById('btnTabDashboard');
    const btnAl    = document.getElementById('btnTabActiveLearning');

    if (tabName === 'dashboard') {
        dashView.style.display = 'grid';
        alView.style.display   = 'none';
        btnDash.classList.add('active');
        btnAl.classList.remove('active');
    } else {
        dashView.style.display = 'none';
        alView.style.display   = 'grid';
        btnDash.classList.remove('active');
        btnAl.classList.add('active');
        // Redraw canvas if active
        if (currentLabelingItem) {
            drawLabelingCanvas();
        }
    }
}

// ── Active Learning Studio Logic ─────────────────────────────────────────────
let labelingGarments     = [];
let currentLabelingItem  = null;
let labelingBoxes        = [];
let selectedBoxIndex     = -1;
let correctionsCount     = 0;
let isDrawing            = false;
let startX, startY;

const lCanvas     = document.getElementById('labelingCanvas');
const lCtx        = lCanvas.getContext('2d');
const lImage      = new Image();
const lPlaceholder= document.getElementById('labelingPlaceholder');

// Initialize canvas listeners
lCanvas.addEventListener('mousedown', onMouseDown);
lCanvas.addEventListener('mousemove', onMouseMove);
lCanvas.addEventListener('mouseup', onMouseUp);

// Populate Queue in sidebar
function updateLabelingQueue(garments) {
    labelingGarments = garments;
    const queueList = document.getElementById('labelingQueueList');
    const badge     = document.getElementById('labelingQueueBadge');
    
    // Filter to garments with defects or not verified yet
    const pendingItems = garments.filter(g => g.status === 'defective');
    badge.textContent = `${pendingItems.length} items`;
    
    queueList.innerHTML = '';
    if (pendingItems.length === 0) {
        queueList.innerHTML = `<div style="text-align: center; color: var(--text-secondary); padding: 1.5rem 0; font-size: 0.82rem;">✓ All defect items verified!</div>`;
        return;
    }
    
    pendingItems.forEach(item => {
        const row = document.createElement('div');
        row.className = 'device-row';
        row.style.cursor = 'pointer';
        row.style.background = currentLabelingItem && currentLabelingItem.garment_id === item.garment_id ? 'rgba(59,130,246,0.12)' : 'rgba(255,255,255,0.02)';
        row.style.borderColor = currentLabelingItem && currentLabelingItem.garment_id === item.garment_id ? 'rgba(59,130,246,0.4)' : 'var(--panel-border)';
        
        const filename = item.image_url.split('/').pop().replace(/^Van-\d+_+scan_\d+_/, '');
        
        row.innerHTML = `
            <div style="flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                <span style="color: var(--color-defect); font-weight:700; margin-right: 4px;">⚠️</span>
                <span style="font-weight: 700; font-size: 0.8rem;">${item.garment_type.toUpperCase()}</span>
                <span style="font-size: 0.72rem; color: var(--text-secondary); margin-left: 5px;">#${item.garment_id} (${filename})</span>
            </div>
            <div style="font-size: 0.72rem; color: var(--color-warn); font-weight: 600; flex-shrink:0;">Verify</div>
        `;
        row.addEventListener('click', () => loadLabelingItem(item));
        queueList.appendChild(row);
    });
}

function loadLabelingItem(item) {
    currentLabelingItem = item;
    selectedBoxIndex = -1;
    document.getElementById('labelingItemName').innerHTML = `Scanning item: <strong>${item.garment_type.toUpperCase()}</strong> (Cloud ID: #${item.garment_id})`;
    document.getElementById('btnSubmitCorrection').disabled = false;
    
    // Copy boxes
    labelingBoxes = item.defects ? item.defects.map(d => ({
        label: d.label,
        confidence: d.confidence,
        box: [...d.box] // [x1, y1, x2, y2]
    })) : [];
    
    // Load image
    lPlaceholder.style.display = 'none';
    lCanvas.style.display = 'block';
    
    lImage.onload = () => {
        lCanvas.width = 640;
        lCanvas.height = 480;
        drawLabelingCanvas();
    };
    lImage.src = item.image_url;
    
    // Refresh queue UI selection
    updateLabelingQueue(labelingGarments);
}

function drawLabelingCanvas() {
    lCtx.clearRect(0, 0, lCanvas.width, lCanvas.height);
    lCtx.drawImage(lImage, 0, 0, lCanvas.width, lCanvas.height);
    
    // Draw all boxes
    labelingBoxes.forEach((b, idx) => {
        const x1 = b.box[0] * lCanvas.width;
        const y1 = b.box[1] * lCanvas.height;
        const x2 = b.box[2] * lCanvas.width;
        const y2 = b.box[3] * lCanvas.height;
        const w = x2 - x1;
        const h = y2 - y1;
        
        const isSelected = idx === selectedBoxIndex;
        lCtx.strokeStyle = isSelected ? '#3b82f6' : '#f04a6e';
        lCtx.lineWidth = isSelected ? 4 : 2;
        lCtx.strokeRect(x1, y1, w, h);
        
        // Label badge
        lCtx.fillStyle = isSelected ? '#3b82f6' : '#f04a6e';
        lCtx.font = 'bold 10px Outfit, sans-serif';
        const txt = b.label.toUpperCase();
        const txtW = lCtx.measureText(txt).width;
        lCtx.fillRect(x1 - 1, y1 - 18, txtW + 8, 18);
        
        lCtx.fillStyle = '#ffffff';
        lCtx.fillText(txt, x1 + 3, y1 - 5);
    });
}

// Canvas Mouse Handlers for click selection & box drawing
function onMouseDown(e) {
    const rect = lCanvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    
    // Check if clicked inside an existing box (reverse loop for top-most)
    let clickedBoxIdx = -1;
    for (let i = labelingBoxes.length - 1; i >= 0; i--) {
        const b = labelingBoxes[i];
        const x1 = b.box[0] * lCanvas.width;
        const y1 = b.box[1] * lCanvas.height;
        const x2 = b.box[2] * lCanvas.width;
        const y2 = b.box[3] * lCanvas.height;
        
        if (x >= x1 && x <= x2 && y >= y1 && y <= y2) {
            clickedBoxIdx = i;
            break;
        }
    }
    
    if (clickedBoxIdx !== -1) {
        selectedBoxIndex = clickedBoxIdx;
        document.getElementById('labelSelect').value = labelingBoxes[clickedBoxIdx].label;
        drawLabelingCanvas();
    } else {
        // Start drawing a new box
        isDrawing = true;
        startX = x / lCanvas.width;
        startY = y / lCanvas.height;
        selectedBoxIndex = -1;
    }
}

function onMouseMove(e) {
    if (!isDrawing) return;
    const rect = lCanvas.getBoundingClientRect();
    const curX = (e.clientX - rect.left) / lCanvas.width;
    const curY = (e.clientY - rect.top) / lCanvas.height;
    
    // Draw current boxes + active box outline
    drawLabelingCanvas();
    
    const x1 = Math.min(startX, curX) * lCanvas.width;
    const y1 = Math.min(startY, curY) * lCanvas.height;
    const w = Math.abs(curX - startX) * lCanvas.width;
    const h = Math.abs(curY - startY) * lCanvas.height;
    
    lCtx.strokeStyle = '#3b82f6';
    lCtx.lineWidth = 2.5;
    lCtx.setLineDash([4, 4]);
    lCtx.strokeRect(x1, y1, w, h);
    lCtx.setLineDash([]);
}

function onMouseUp(e) {
    if (!isDrawing) return;
    isDrawing = false;
    const rect = lCanvas.getBoundingClientRect();
    const endX = (e.clientX - rect.left) / lCanvas.width;
    const endY = (e.clientY - rect.top) / lCanvas.height;
    
    const x1 = Math.min(startX, endX);
    const y1 = Math.min(startY, endY);
    const x2 = Math.max(startX, endX);
    const y2 = Math.max(startY, endY);
    
    // Require a minimum drag size
    if (Math.abs(x2 - x1) > 0.02 && Math.abs(y2 - y1) > 0.02) {
        const newLabel = document.getElementById('labelSelect').value;
        labelingBoxes.push({
            label: newLabel,
            confidence: 1.0,
            box: [x1, y1, x2, y2]
        });
        selectedBoxIndex = labelingBoxes.length - 1;
    }
    drawLabelingCanvas();
}

// Bbox select change handler
document.getElementById('labelSelect').addEventListener('change', (e) => {
    if (selectedBoxIndex !== -1) {
        labelingBoxes[selectedBoxIndex].label = e.target.value;
        drawLabelingCanvas();
    }
});

function clearSelectedBox() {
    if (selectedBoxIndex !== -1) {
        labelingBoxes.splice(selectedBoxIndex, 1);
        selectedBoxIndex = -1;
        drawLabelingCanvas();
    }
}

// Submit Correction
function submitLabelCorrection() {
    if (!currentLabelingItem) return;
    
    correctionsCount++;
    document.getElementById('txtPoolSize').textContent = `${correctionsCount} annotation${correctionsCount > 1 ? 's' : ''}`;
    
    const filename = currentLabelingItem.image_url.split('/').pop().replace(/^Van-\d+_+scan_\d+_/, '');
    pushActivity(`Verified scan #${currentLabelingItem.garment_id} (${filename}) added to retraining pool`, 'var(--color-warn)');
    
    // Clear workspace
    currentLabelingItem = null;
    labelingBoxes = [];
    selectedBoxIndex = -1;
    lCanvas.style.display = 'none';
    lPlaceholder.style.display = 'flex';
    document.getElementById('labelingItemName').innerText = 'Select an item from the queue to start';
    document.getElementById('btnSubmitCorrection').disabled = true;
    
    // Remove completed item from local list
    const index = labelingGarments.findIndex(g => g.garment_id === currentLabelingItem?.garment_id);
    if (index !== -1) {
        labelingGarments.splice(index, 1);
    }
    updateLabelingQueue(labelingGarments);
}

// Simulated active learning retraining loop
function runMockRetraining() {
    const btn = document.getElementById('btnRunRetrain');
    const container = document.getElementById('retrainProgressContainer');
    const progressBar = document.getElementById('barRetrainProgress');
    const progressText = document.getElementById('txtRetrainProgress');
    const percentText = document.getElementById('txtRetrainPercent');
    const logs = document.getElementById('retrainLogs');
    
    btn.disabled = true;
    container.style.display = 'block';
    progressBar.style.width = '0%';
    percentText.textContent = '0%';
    logs.innerHTML = '';
    
    const logsData = [
        "Initializing Active Learning Fine-Tuning...",
        "Checking GPU acceleration status... CUDA active (NVIDIA RTX 3080 detected).",
        "Loading base model weights: YOLO26s v1.0.0",
        `Assembling retraining dataset pool... Found ${correctionsCount} user-submitted annotation corrections.`,
        "Splitting dataset... 80% train / 20% validation split.",
        "Starting Fine-Tuning Epochs...",
        "Epoch 1/5: Loss = 0.542, mAP50 = 0.681, Stain precision = 71.2%",
        "Epoch 2/5: Loss = 0.385, mAP50 = 0.752, Stain precision = 79.5%",
        "Epoch 3/5: Loss = 0.224, mAP50 = 0.884, Stain precision = 88.0%",
        "Epoch 4/5: Loss = 0.151, mAP50 = 0.912, Stain precision = 91.5%",
        "Epoch 5/5: Loss = 0.082, mAP50 = 0.948, Stain precision = 94.8%",
        "Retraining run completed successfully!",
        "Validating updated weights... Confusion matrix stain vs hole cross-class errors reduced to 0.",
        "Optimizing weights for edge device deployment... ONNX export complete.",
        "Deploying updated weights to Edge units (http://localhost:8000)...",
        "Edge units successfully loaded updated weights: YOLO26s v1.1.0"
    ];
    
    let step = 0;
    const interval = setInterval(async () => {
        if (step >= logsData.length) {
            clearInterval(interval);
            progressText.textContent = 'Retraining Completed!';
            percentText.textContent = '100%';
            progressBar.style.width = '100%';
            
            // Save retraining state in central Cloud server
            try {
                const resp = await fetch('/api/active_learning/retrain', { method: 'POST' });
                const data = await resp.json();
                if (data.status === 'success') {
                    // Update stats
                    document.getElementById('txtModelVersion').textContent = 'YOLO26s v1.1.0 (Active)';
                    document.getElementById('txtModelVersion').style.color = 'var(--color-clean)';
                    document.getElementById('txtStainAccuracy').textContent = '94.8% (Highly Accurate)';
                    document.getElementById('txtStainAccuracy').style.color = 'var(--color-clean)';
                    document.getElementById('btnResetModel').style.display = 'block';
                    
                    pushActivity('Active learning retraining complete. Model upgraded to v1.1.0.', 'var(--color-clean)');
                }
            } catch (err) {
                console.error("Failed to commit retrain state:", err);
            }
            
            btn.disabled = false;
            return;
        }
        
        // Append log line
        logs.innerHTML += logsData[step] + '\n';
        logs.scrollTop = logs.scrollHeight;
        
        // Progress percent
        const pct = Math.round(((step + 1) / logsData.length) * 100);
        percentText.textContent = `${pct}%`;
        progressBar.style.width = `${pct}%`;
        progressText.textContent = step < 5 ? "Preparing..." : (step < 11 ? "Training epochs..." : "Deploying ONNX...");
        
        step++;
    }, 400);
}

// Reset Model Version
async function resetModelVersion() {
    try {
        const resp = await fetch('/api/active_learning/reset', { method: 'POST' });
        const data = await resp.json();
        if (data.status === 'success') {
            document.getElementById('txtModelVersion').textContent = 'YOLO26s v1.0.0';
            document.getElementById('txtModelVersion').style.color = 'var(--cyan)';
            document.getElementById('txtStainAccuracy').textContent = '65.2% (Unreliable)';
            document.getElementById('txtStainAccuracy').style.color = 'var(--color-defect)';
            document.getElementById('btnResetModel').style.display = 'none';
            document.getElementById('retrainProgressContainer').style.display = 'none';
            correctionsCount = 0;
            document.getElementById('txtPoolSize').textContent = '0 annotations';
            pushActivity('Active learning model reset to factory v1.0.0.', 'var(--text-secondary)');
        }
    } catch (e) {
        console.error(e);
    }
}

// ── Autorefresh ───────────────────────────────────────────────────────────────
fetchCloudData();
setInterval(fetchCloudData, 10000);

