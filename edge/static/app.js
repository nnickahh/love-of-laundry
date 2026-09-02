// app.js — v3
// Operator dashboard: Live MJPEG feed + YOLO overlay canvas + scan/confirm logic

// Polyfill: ctx.roundRect for older Chrome/Safari versions
if (!CanvasRenderingContext2D.prototype.roundRect) {
    CanvasRenderingContext2D.prototype.roundRect = function(x, y, w, h, r) {
        const radius = Math.min(r, w / 2, h / 2);
        this.beginPath();
        this.moveTo(x + radius, y);
        this.lineTo(x + w - radius, y);
        this.quadraticCurveTo(x + w, y, x + w, y + radius);
        this.lineTo(x + w, y + h - radius);
        this.quadraticCurveTo(x + w, y + h, x + w - radius, y + h);
        this.lineTo(x + radius, y + h);
        this.quadraticCurveTo(x, y + h, x, y + h - radius);
        this.lineTo(x, y + radius);
        this.quadraticCurveTo(x, y, x + radius, y);
        this.closePath();
    };
}

// ── Canvas / Overlay Setup ────────────────────────────────────────────────────
const videoFeed   = document.getElementById('videoFeed');
const canvas      = document.getElementById('overlayCanvas');
const ctx         = canvas.getContext('2d');
const placeholder = document.getElementById('viewportPlaceholder');
const fpsBadge    = document.getElementById('fpsBadge') || document.getElementById('liveBadge');
const fpsCounter  = document.getElementById('fpsCounter');

// Match canvas resolution to source stream
canvas.width  = 640;
canvas.height = 480;

// ── State ─────────────────────────────────────────────────────────────────────
let currentScan   = null;
let currentPan    = 0.0;
let currentTilt   = 0.0;
let batchItems    = [];
let isLiveActive  = false;     // true when MJPEG stream is running
let hasScanResult = false;     // true when a scan result is shown on the overlay

// ── Helpers ───────────────────────────────────────────────────────────────────
function showPlaceholder() {
    placeholder.style.display  = 'flex';
    canvas.style.display       = 'none';
    if (fpsBadge) fpsBadge.classList.remove('active');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    document.getElementById('viewportStatus').textContent = 'Awaiting Feed';
}

// ── WebSocket Live Feed ───────────────────────────────────────────────────────
let ws               = null;
let _fpsFrameCount   = 0;
let _fpsLastTime     = performance.now();
let _fpsInterval     = null;
const _offscreenImg  = new Image();   // reused image element for canvas drawing

function _startFpsCounter() {
    _fpsFrameCount = 0;
    _fpsLastTime   = performance.now();
    const el = document.getElementById('fpsCounter');
    if (el) el.textContent = '30.0 FPS';
    _fpsInterval   = setInterval(() => {
        const now     = performance.now();
        const elapsed = (now - _fpsLastTime) / 1000;
        const fps     = (_fpsFrameCount / elapsed).toFixed(1);
        _fpsFrameCount = 0;
        _fpsLastTime   = now;
        const el = document.getElementById('fpsCounter');
        if (el) el.textContent = `${fps} FPS`;
    }, 1000);
}

function _stopFpsCounter() {
    clearInterval(_fpsInterval);
    _fpsInterval = null;
    const el = document.getElementById('fpsCounter');
    if (el) el.textContent = '-- FPS';
}

let _pendingWsFrame = null;
let _isWsRendering = false;

function getBoxColor(label) {
    const l = (label || '').toLowerCase();
    if (['hole', 'tear', 'stain', 'broken_button', 'color_defect', 'defect', 'foreign_yarn'].includes(l)) {
        return { stroke: '#ef4444', glow: 'rgba(239,68,68,0.7)', fill: '#ef4444', text: '#ffffff' }; // Red Defect
    }
    // High-visibility green bounding box for all garments as requested
    return { stroke: '#10b981', glow: 'rgba(16,185,129,0.7)', fill: '#10b981', text: '#ffffff' }; // Emerald Green Garment
}

function formatGarmentBadgeText(label, confidence) {
    const l = (label || '').toLowerCase();
    const confPct = Math.round(confidence * 100);
    if (['shirt', 't_shirt', 'tshirt', 'polo', 'uniform', 'top', 'blouse'].includes(l)) {
        return `TSHIRT ${confPct}%`;
    }
    if (['pants', 'jeans', 'trousers', 'slacks', 'long_pants', 'long'].includes(l)) {
        return `LONG PANTS ${confPct}%`;
    }
    if (['shorts', 'short_pants'].includes(l)) {
        return `SHORTS ${confPct}%`;
    }
    if (['jacket', 'coat', 'winter_jacket', 'hoodie'].includes(l)) {
        return `JACKET ${confPct}%`;
    }
    if (['dress', 'gown'].includes(l)) {
        return `DRESS ${confPct}%`;
    }
    if (['skirt'].includes(l)) {
        return `SKIRT ${confPct}%`;
    }
    return `${label.toUpperCase()} ${confPct}%`;
}

let _currentBoxes = [];
let _pendingBitmap = null;
let _isAnimScheduled = false;

function _drawBoxes(boxes) {
    if (!boxes || boxes.length === 0) return;
    boxes.forEach(b => {
        const x1 = b.box[0] * canvas.width;
        const y1 = b.box[1] * canvas.height;
        const x2 = b.box[2] * canvas.width;
        const y2 = b.box[3] * canvas.height;
        const w  = x2 - x1;
        const h  = y2 - y1;

        const style = getBoxColor(b.label);

        // High-visibility bounding box with glow
        ctx.shadowColor = style.glow;
        ctx.shadowBlur  = 12;
        ctx.strokeStyle = style.stroke;
        ctx.lineWidth   = 3.0;
        ctx.strokeRect(x1, y1, w, h);
        ctx.shadowBlur  = 0;

        // High-contrast pill badge
        const txt      = formatGarmentBadgeText(b.label, b.confidence);
        ctx.font        = 'bold 12px Outfit, sans-serif';
        const txtWidth  = ctx.measureText(txt).width;
        const pillH     = 22;
        const pillY     = y1 > pillH + 4 ? y1 - pillH - 2 : y1 + 4;

        ctx.fillStyle = style.fill;
        ctx.beginPath();
        ctx.roundRect(x1 - 1, pillY, txtWidth + 14, pillH, 4);
        ctx.fill();

        ctx.fillStyle = style.text;
        ctx.fillText(txt, x1 + 6, pillY + 15);
    });
}

function _scheduleCanvasPaint() {
    if (_isAnimScheduled) return;
    _isAnimScheduled = true;
    requestAnimationFrame(() => {
        _isAnimScheduled = false;
        if (!_pendingBitmap) return;
        const bmp = _pendingBitmap;
        _pendingBitmap = null;
        ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height);
        _drawBoxes(_currentBoxes);
        bmp.close();
        _fpsFrameCount++;
    });
}

function _renderWsFrame(jpeg_b64, boxes) {
    _currentBoxes = boxes || [];

    if (typeof createImageBitmap === 'function') {
        const binStr = atob(jpeg_b64);
        const len = binStr.length;
        const bytes = new Uint8Array(len);
        for (let i = 0; i < len; i++) {
            bytes[i] = binStr.charCodeAt(i);
        }
        const blob = new Blob([bytes], { type: 'image/jpeg' });
        createImageBitmap(blob).then(bmp => {
            if (_pendingBitmap) _pendingBitmap.close();
            _pendingBitmap = bmp;
            _scheduleCanvasPaint();
        }).catch(() => {});
    } else {
        const img = new Image();
        img.onload = () => {
            ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
            _drawBoxes(_currentBoxes);
            _fpsFrameCount++;
        };
        img.src = 'data:image/jpeg;base64,' + jpeg_b64;
    }
}

function startLiveFeed() {
    if (ws) { ws.close(); ws = null; }

    isLiveActive  = true;
    hasScanResult = false;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    placeholder.style.display = 'none';
    // Show canvas directly (no <img> tag needed)
    canvas.style.display      = 'block';
    if (fpsBadge) fpsBadge.classList.add('active');
    document.getElementById('viewportStatus').textContent = 'Live';

    const btn = document.getElementById('liveBtn');
    btn.innerHTML = '⏹ Stop Live Feed';
    btn.classList.add('active');

    const infer = liveInferCheck ? liveInferCheck.checked : true;
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/video_feed`);
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => {
        ws.send(JSON.stringify({ infer }));
        _startFpsCounter();
    };

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        _renderWsFrame(msg.frame, msg.boxes || []);
    };

    ws.onerror = (e) => console.error('WebSocket error:', e);
    ws.onclose = () => {
        _stopFpsCounter();
        if (isLiveActive) {
            // Unexpected close — try to reconnect after 1s
            setTimeout(() => { if (isLiveActive) startLiveFeed(); }, 1000);
        }
    };
}

if (liveInferCheck) {
    liveInferCheck.addEventListener('change', () => {
        if (isLiveActive && ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ infer: liveInferCheck.checked }));
        }
    });
}

function stopLiveFeed() {
    isLiveActive = false;
    if (ws) { ws.close(); ws = null; }
    canvas.style.display = 'none';
    if (fpsBadge) fpsBadge.classList.remove('active');
    _stopFpsCounter();

    const btn = document.getElementById('liveBtn');
    btn.innerHTML = '📹 Start Live Feed';
    btn.classList.remove('active');

    if (!hasScanResult) {
        showPlaceholder();
        document.getElementById('viewportStatus').textContent = 'Feed Stopped';
    } else {
        document.getElementById('viewportStatus').textContent = 'Scan Result';
    }
}

// ── Live Feed Toggle ──────────────────────────────────────────────────────────
document.getElementById('liveBtn').addEventListener('click', () => {
    if (isLiveActive) {
        stopLiveFeed();
    } else {
        startLiveFeed();
    }
});


// ── Status Polling ────────────────────────────────────────────────────────────
async function updateStats() {
    try {
        const resp = await fetch('/api/status');
        const data = await resp.json();

        document.getElementById('deviceId').innerText      = data.device_id;
        document.getElementById('currentAngles').innerText = `Pan: ${data.angles.pan}°, Tilt: ${data.angles.tilt}°`;
        currentPan  = data.angles.pan;
        currentTilt = data.angles.tilt;

        document.getElementById('statsTotal').innerText   = data.stats.total;
        document.getElementById('statsPending').innerText = data.stats.pending;
        document.getElementById('statsDefects').innerText = data.stats.defective;

        const syncDot  = document.getElementById('syncDot');
        const syncText = document.getElementById('syncText');
        if (data.stats.pending > 0) {
            syncDot.style.background  = '#f59e0b';
            syncDot.style.boxShadow   = '0 0 8px #f59e0b';
            syncText.innerText        = `${data.stats.pending} pending sync`;
        } else {
            syncDot.style.background  = '#10b981';
            syncDot.style.boxShadow   = '0 0 8px #10b981';
            syncText.innerText        = 'Synced ✓';
        }

        const camModeEl = document.getElementById('cameraMode');
        if (camModeEl) {
            if (data.camera_mock) {
                camModeEl.innerText = '🟡 Mock Mode';
                camModeEl.style.color = 'var(--color-warn)';
            } else {
                const label = data.camera_name || (data.camera_source === '0' ? 'Laptop Camera' : `Camera ${data.camera_source}`);
                camModeEl.innerText = `🟢 ${label}`;
                camModeEl.style.color = 'var(--color-clean)';
            }
        }

    } catch (e) {
        console.error('Status fetch failed', e);
        const syncDot = document.getElementById('syncDot');
        if (syncDot) syncDot.className = 'status-dot offline';
        const syncText = document.getElementById('syncText');
        if (syncText) syncText.innerText = 'Server Offline';
    }
}

updateStats();
setInterval(updateStats, 5000);

// ── Pan-Tilt ──────────────────────────────────────────────────────────────────
async function setPreset(name) {
    const presets = {
        center:       [0.0,   0.0],
        top_left:     [-30.0, 30.0],
        top_right:    [30.0,  30.0],
        bottom_left:  [-30.0, -30.0],
        bottom_right: [30.0,  -30.0],
    };
    const [pan, tilt] = presets[name];
    await movePTDirect(pan, tilt);
}

async function movePT(panDelta, tiltDelta) {
    await movePTDirect(currentPan + panDelta, currentTilt + tiltDelta);
}

async function movePTDirect(pan, tilt) {
    try {
        const resp = await fetch('/api/camera/move', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pan, tilt }),
        });
        const data = await resp.json();
        document.getElementById('currentAngles').innerText = `Pan: ${data.angles.pan}°, Tilt: ${data.angles.tilt}°`;
        currentPan  = data.angles.pan;
        currentTilt = data.angles.tilt;
    } catch (e) {
        console.error('Camera move failed:', e);
    }
}

// ── Bounding Box Renderer ─────────────────────────────────────────────────────
function renderBoxes(imageSrc, boxes) {
    const img = new Image();
    img.onload = () => {
        canvas.style.display = 'block';
        if (placeholder) placeholder.style.display = 'none';

        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

        boxes.forEach(b => {
            const x1 = b.box[0] * canvas.width;
            const y1 = b.box[1] * canvas.height;
            const x2 = b.box[2] * canvas.width;
            const y2 = b.box[3] * canvas.height;
            const w  = x2 - x1;
            const h  = y2 - y1;

            const style = getBoxColor(b.label);

            // Glow shadow & thick border
            ctx.shadowColor = style.glow;
            ctx.shadowBlur  = 14;
            ctx.strokeStyle = style.stroke;
            ctx.lineWidth   = 3.0;
            ctx.strokeRect(x1, y1, w, h);
            ctx.shadowBlur  = 0;

            // Label background pill
            const txt      = formatGarmentBadgeText(b.label, b.confidence);
            ctx.font        = 'bold 12px Outfit, sans-serif';
            const txtWidth  = ctx.measureText(txt).width;
            const pillH     = 22;
            const pillY     = y1 > pillH + 4 ? y1 - pillH - 2 : y1 + 4;

            ctx.fillStyle = style.fill;
            ctx.beginPath();
            ctx.roundRect(x1 - 1, pillY, txtWidth + 14, pillH, 4);
            ctx.fill();

            ctx.fillStyle = style.text;
            ctx.fillText(txt, x1 + 6, pillY + 15);
        });
    };
    img.src = imageSrc;
}

// ── Scan Trigger ──────────────────────────────────────────────────────────────
document.getElementById('scanBtn').addEventListener('click', async () => {
    const btn = document.getElementById('scanBtn');
    btn.disabled  = true;
    btn.innerHTML = `<span class="spinner"></span> Running Inference...`;

    // Pause live feed while scanning
    const wasLive = isLiveActive;
    if (wasLive) stopLiveFeed();

    try {
        const resp = await fetch('/api/scan', { method: 'POST' });
        if (!resp.ok) {
            const errJson = await resp.json().catch(() => ({}));
            throw new Error(errJson.detail || `Server returned ${resp.status}`);
        }
        const data = await resp.json();

        currentScan   = data;
        hasScanResult = true;

        // Show scan snapshot in overlay
        if (placeholder) placeholder.style.display = 'none';
        canvas.style.display = 'block';
        renderBoxes(data.image_url, data.boxes);
        document.getElementById('viewportStatus').textContent = 'Scan Result — ' + (wasLive ? 'Resume Feed below' : '');

        applyResultToUI(data, /*isFromBatch=*/false);

        document.getElementById('confirmBtn').disabled = false;
        document.getElementById('resetBtn').disabled   = false;

    } catch (e) {
        console.error('Scan failed:', e);
        alert(`Scan failed: ${e.message || 'Server error'}`);
        if (wasLive) startLiveFeed(); // resume if scan fails
    } finally {
        btn.disabled  = false;
        btn.innerHTML = `📷 Trigger Scan`;
    }
});

// ── Batch Upload ──────────────────────────────────────────────────────────────
document.getElementById('uploadBatchBtn').addEventListener('click', () => {
    document.getElementById('batchUploadInput').click();
});

document.getElementById('batchUploadInput').addEventListener('change', async (e) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    const formData = new FormData();
    for (let i = 0; i < files.length; i++) formData.append('files', files[i]);

    const btn = document.getElementById('uploadBatchBtn');
    btn.disabled  = true;
    btn.innerHTML = `<span class="spinner"></span> Uploading...`;

    // Pause live feed for batch
    if (isLiveActive) stopLiveFeed();

    try {
        const resp = await fetch('/api/upload_batch', { method: 'POST', body: formData });
        if (resp.ok) {
            const data = await resp.json();
            if (data.length === 0) {
                alert('No valid images could be processed.');
                return;
            }
            batchItems = data.map(item => ({ ...item, confirmed: false }));
            document.getElementById('batchScansContainer').style.display = 'block';
            document.getElementById('batchCount').innerText = batchItems.length;
            renderBatchList();
            if (batchItems.length > 0) loadBatchItem(0);
        } else {
            const errJson = await resp.json().catch(() => ({}));
            alert(`Batch upload failed: ${errJson.detail || resp.statusText}`);
        }
    } catch (err) {
        console.error('Batch upload failed:', err);
        alert(`Batch upload failed: ${err.message || 'Network error'}`);
    } finally {
        btn.disabled  = false;
        btn.innerHTML = `📁 Batch`;
        e.target.value = '';
    }
});

// ── Batch List Renderer ───────────────────────────────────────────────────────
function renderBatchList() {
    const list = document.getElementById('batchScansList');
    list.innerHTML = '';
    batchItems.forEach((item, idx) => {
        const isDefect     = item.status === 'defective';
        const isActive     = currentScan && currentScan.local_id === item.local_id;
        const color        = isDefect ? 'var(--color-defect)' : 'var(--color-clean)';
        const symbol       = isDefect ? '⚠️' : '✓';
        const statusText   = item.confirmed
            ? `<span style="color:var(--color-clean);font-weight:700;">✓ Synced</span>`
            : `<span style="color:var(--color-warn);font-weight:700;">● Pending</span>`;
        const filename = item.image_url.split('/').pop().replace(/^scan_\d+_/, '');

        const row = document.createElement('div');
        row.className = 'device-row';
        row.style.cursor      = 'pointer';
        row.style.background  = isActive ? 'rgba(124,60,248,0.12)' : 'rgba(255,255,255,0.02)';
        row.style.borderColor = isActive ? 'rgba(124,60,248,0.4)'  : 'var(--panel-border)';
        row.innerHTML = `
            <div style="flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                <span style="color:${color}; font-weight:700; margin-right:4px;">${symbol}</span>
                <span style="font-weight:700; font-size:0.83rem;">${item.garment_type.toUpperCase()}</span>
                <span style="font-size:0.72rem; color:var(--text-secondary); margin-left:5px;">${filename}</span>
            </div>
            <div style="font-size:0.78rem; margin-left:8px; flex-shrink:0;">${statusText}</div>
        `;
        row.addEventListener('click', () => loadBatchItem(idx));
        list.appendChild(row);
    });
}

function loadBatchItem(idx) {
    const data = batchItems[idx];
    currentScan   = data;
    hasScanResult = true;

    renderBatchList();
    placeholder.style.display = 'none';
    renderBoxes(data.image_url, data.boxes);
    applyResultToUI(data, /*isFromBatch=*/true);

    document.getElementById('confirmBtn').disabled = data.confirmed;
    document.getElementById('resetBtn').disabled   = false;
    document.getElementById('viewportStatus').textContent = 'Batch Item ' + (idx + 1) + '/' + batchItems.length;
}

// ── Shared UI Update ──────────────────────────────────────────────────────────
function applyResultToUI(data, isFromBatch) {
    document.getElementById('garmentTypeSelect').value = data.garment_type;
    document.getElementById('statusSelect').value      = data.status;

    const summary = document.getElementById('defectSummary');
    const badge   = document.getElementById('scanStatusBadge');

    if (data.status === 'clean') {
        summary.innerHTML  = `<span>✓ Garment Clear: Clean <strong>${data.garment_type}</strong></span>`;
        summary.className  = 'defect-summary-box summary-clean';
        badge.textContent  = isFromBatch ? (data.confirmed ? 'CONFIRMED ✓' : 'PASSED') : 'PASSED';
        badge.style.color  = 'var(--color-clean)';
    } else {
        summary.innerHTML  = `<span>⚠ Defect Detected: <strong>${data.garment_type}</strong> has anomalies</span>`;
        summary.className  = 'defect-summary-box summary-defect';
        badge.textContent  = isFromBatch ? (data.confirmed ? 'CONFIRMED ✓' : 'DEFECT FOUND') : 'DEFECT FOUND';
        badge.style.color  = 'var(--color-defect)';
    }

    const defectsList = document.getElementById('defectsList');
    defectsList.innerHTML = '';
    if (data.defects.length === 0) {
        defectsList.innerHTML = `<div class="empty-state"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg><div>No defects detected</div></div>`;
    } else {
        data.defects.forEach(d => {
            const item = document.createElement('div');
            item.className = 'defect-item';
            item.innerHTML = `
                <span class="defect-tag">⚠ ${d.label.replace(/_/g, ' ')}</span>
                <span class="defect-conf">${Math.round(d.confidence * 100)}% conf.</span>
            `;
            defectsList.appendChild(item);
        });
    }
}

// ── Confirm ───────────────────────────────────────────────────────────────────
document.getElementById('confirmBtn').addEventListener('click', async () => {
    if (!currentScan) return;
    const localId = currentScan.local_id;
    const type    = document.getElementById('garmentTypeSelect').value;
    const status  = document.getElementById('statusSelect').value;

    try {
        const resp = await fetch('/api/confirm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ local_id: localId, garment_type: type, status }),
        });
        if (resp.ok) {
            const idx = batchItems.findIndex(item => item.local_id === localId);
            if (idx !== -1) {
                batchItems[idx].garment_type = type;
                batchItems[idx].status       = status;
                batchItems[idx].confirmed    = true;
                const nextIdx = batchItems.findIndex((item, i) => !item.confirmed && i !== idx);
                loadBatchItem(nextIdx !== -1 ? nextIdx : idx);
            } else {
                resetUI();
            }
            updateStats();
        }
    } catch (e) {
        console.error('Confirm failed:', e);
    }
});

// ── Reset ─────────────────────────────────────────────────────────────────────
document.getElementById('resetBtn').addEventListener('click', () => {
    batchItems = [];
    document.getElementById('batchScansContainer').style.display = 'none';
    if (isLiveActive) stopLiveFeed();
    resetUI();
});

function resetUI() {
    currentScan   = null;
    hasScanResult = false;
    document.getElementById('garmentTypeSelect').value = 'unknown';
    document.getElementById('statusSelect').value      = 'clean';
    document.getElementById('defectsList').innerHTML   = `<div class="empty-state"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg><div>No defects detected yet</div></div>`;

    const summary = document.getElementById('defectSummary');
    summary.innerHTML  = 'No active scan. Run scan to inspect.';
    summary.className  = 'defect-summary-box summary-unknown';

    const badge = document.getElementById('scanStatusBadge');
    badge.textContent = 'Awaiting Scan';
    badge.style.color = 'var(--text-secondary)';

    document.getElementById('confirmBtn').disabled = true;
    document.getElementById('resetBtn').disabled   = true;

    showPlaceholder();
}

// ── Model Config Tuning UI Handlers ──────────────────────────────────────────
const confSlider  = document.getElementById('confSlider');
const confVal     = document.getElementById('confVal');
const iouSlider   = document.getElementById('iouSlider');
const iouVal      = document.getElementById('iouVal');
const imgszSelect = document.getElementById('imgszSelect');

async function fetchModelConfig() {
    try {
        const resp = await fetch('/api/config');
        if (resp.ok) {
            const config = await resp.json();
            
            // Set slider values
            confSlider.value = config.conf;
            confVal.textContent = parseFloat(config.conf).toFixed(2);
            
            iouSlider.value = config.iou;
            iouVal.textContent = parseFloat(config.iou).toFixed(2);
            
            imgszSelect.value = config.imgsz;
        }
    } catch (err) {
        console.error('Failed to fetch model config:', err);
    }
}

async function updateModelConfig() {
    const conf = parseFloat(confSlider.value);
    const iou = parseFloat(iouSlider.value);
    const imgsz = parseInt(imgszSelect.value);
    
    // Update local label display
    confVal.textContent = conf.toFixed(2);
    iouVal.textContent = iou.toFixed(2);
    
    try {
        const resp = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ conf, iou, imgsz })
        });
        if (!resp.ok) {
            console.error('Failed to update config on edge server');
        }
    } catch (err) {
        console.error('Failed to update model config:', err);
    }
}

// Bind event listeners
if (confSlider) {
    confSlider.addEventListener('input', () => {
        confVal.textContent = parseFloat(confSlider.value).toFixed(2);
    });
    confSlider.addEventListener('change', updateModelConfig);
}

if (iouSlider) {
    iouSlider.addEventListener('input', () => {
        iouVal.textContent = parseFloat(iouSlider.value).toFixed(2);
    });
    iouSlider.addEventListener('change', updateModelConfig);
}

if (imgszSelect) {
    imgszSelect.addEventListener('change', updateModelConfig);
}

// Fetch on startup
fetchModelConfig();

// ── Scan History ──────────────────────────────────────────────────────
let scanHistory = [];

function addToScanHistory(scan) {
    scanHistory.unshift(scan);
    if (scanHistory.length > 5) scanHistory.pop();
    renderScanHistory();
}

function renderScanHistory() {
    const container = document.getElementById('scanHistory');
    if (!container) return;
    
    if (scanHistory.length === 0) {
        container.innerHTML = `<div class="empty-state"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><div>No scans yet. Trigger your first scan!</div></div>`;
        return;
    }
    
    container.innerHTML = scanHistory.map(scan => `
        <div class="scan-history-item" onclick="showScanModal(${JSON.stringify(scan).replace(/"/g, '&quot;')})">
            <div class="scan-thumb">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
                    <circle cx="8.5" cy="8.5" r="1.5"/>
                    <polyline points="21 15 16 10 5 21"/>
                </svg>
            </div>
            <div class="scan-info">
                <div class="scan-type">${scan.garmentType || 'Unknown'}</div>
                <div class="scan-time">${scan.time}</div>
            </div>
            <span class="scan-status ${scan.status}">${scan.status}</span>
        </div>
    `).join('');
}

// ── Scan Result Modal ─────────────────────────────────────────────────
function showScanModal(scan) {
    let modal = document.getElementById('scanModal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'scanModal';
        modal.className = 'scan-modal-overlay';
        modal.innerHTML = `
            <div class="scan-modal">
                <div class="scan-modal-header">
                    <span class="scan-modal-title">Scan Details</span>
                    <button class="scan-modal-close" onclick="closeScanModal()">×</button>
                </div>
                <div id="scanModalContent"></div>
            </div>
        `;
        document.body.appendChild(modal);
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeScanModal();
        });
    }
    
    const content = document.getElementById('scanModalContent');
    content.innerHTML = `
        <div class="scan-modal-details">
            <div class="scan-detail-item">
                <div class="scan-detail-label">Garment Type</div>
                <div class="scan-detail-value">${scan.garmentType || 'Unknown'}</div>
            </div>
            <div class="scan-detail-item">
                <div class="scan-detail-label">Status</div>
                <div class="scan-detail-value" style="color: ${scan.status === 'clean' ? 'var(--color-clean)' : 'var(--color-defect)'}">${scan.status.toUpperCase()}</div>
            </div>
            <div class="scan-detail-item">
                <div class="scan-detail-label">Defects</div>
                <div class="scan-detail-value">${scan.defects?.length || 0} found</div>
            </div>
            <div class="scan-detail-item">
                <div class="scan-detail-label">Time</div>
                <div class="scan-detail-value">${scan.time}</div>
            </div>
        </div>
    `;
    
    modal.classList.add('active');
}

function closeScanModal() {
    const modal = document.getElementById('scanModal');
    if (modal) modal.classList.remove('active');
}

// ── Keyboard Shortcuts ────────────────────────────────────────────────
document.addEventListener('keydown', (e) => {
    // Ignore if typing in input
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') {
        return;
    }
    
    switch(e.key) {
        case ' ':
            e.preventDefault();
            document.getElementById('scanBtn')?.click();
            break;
        case 'l':
        case 'L':
            document.getElementById('liveBtn')?.click();
            break;
        case 'Enter':
            if (e.ctrlKey || e.metaKey) {
                document.getElementById('confirmBtn')?.click();
            }
            break;
        case 'Escape':
            document.getElementById('resetBtn')?.click();
            closeScanHistoryModal();
            closeScanModal();
            break;
    }
});

// ── Batch Upload Progress ─────────────────────────────────────────────
function showBatchProgress(current, total) {
    let progressEl = document.getElementById('batchProgress');
    if (!progressEl) {
        progressEl = document.createElement('div');
        progressEl.id = 'batchProgress';
        progressEl.className = 'batch-progress';
        const container = document.getElementById('batchScansContainer');
        if (container) {
            container.insertBefore(progressEl, container.firstChild);
        }
    }
    
    const pct = Math.round((current / total) * 100);
    progressEl.innerHTML = `
        <div class="batch-progress-bar">
            <div class="batch-progress-fill" style="width: ${pct}%"></div>
        </div>
        <div class="batch-progress-text">Processing ${current} of ${total} images (${pct}%)</div>
    `;
    
    if (current >= total) {
        setTimeout(() => progressEl.remove(), 2000);
    }
}

// ── Camera Device Management & Switching ──────────────────────────────
const cameraSelect   = document.getElementById('cameraSelect');
const refreshCamsBtn = document.getElementById('refreshCamsBtn');

async function fetchCameraSources() {
    if (!cameraSelect) return;
    try {
        if (refreshCamsBtn) refreshCamsBtn.style.transform = 'rotate(360deg)';
        const resp = await fetch('/api/camera/sources');
        if (resp.ok) {
            const data = await resp.json();
            const activeSrc = data.active_source;
            const isMock = data.is_mock;

            cameraSelect.innerHTML = '';
            data.sources.forEach(src => {
                const opt = document.createElement('option');
                opt.value = src.id;
                opt.textContent = src.name + (src.available ? '' : ' (Offline)');
                if (src.active || (src.id === activeSrc && !isMock) || (src.id === 'mock' && isMock)) {
                    opt.selected = true;
                }
                cameraSelect.appendChild(opt);
            });

            // Ensure custom stream option is present
            const hasCustom = Array.from(cameraSelect.options).some(o => o.value === 'custom_url');
            if (!hasCustom) {
                const opt = document.createElement('option');
                opt.value = 'custom_url';
                opt.textContent = '🌐 Custom Network / VLC Stream...';
                cameraSelect.appendChild(opt);
            }
        }
    } catch (err) {
        console.error('Failed to fetch camera sources:', err);
    } finally {
        if (refreshCamsBtn) {
            setTimeout(() => { refreshCamsBtn.style.transform = 'none'; }, 350);
        }
    }
}

if (cameraSelect) {
    cameraSelect.addEventListener('change', async (e) => {
        const val = e.target.value;
        if (val === 'custom_url' || val === 'network_stream') {
            showStreamInputModal();
            return;
        }

        try {
            const resp = await fetch('/api/camera/source', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ source: val })
            });
            if (resp.ok) {
                const data = await resp.json();
                updateStats();
                // If live feed was active, restart WebSocket to immediately receive new stream
                if (isLiveActive) {
                    startLiveFeed();
                }
            }
        } catch (err) {
            console.error('Failed to switch camera source:', err);
        }
    });
}

if (refreshCamsBtn) {
    refreshCamsBtn.addEventListener('click', (e) => {
        e.preventDefault();
        fetchCameraSources();
    });
}

// Initial fetch on page load
fetchCameraSources();

// Auto-start live feed on load so user immediately sees their camera feed
setTimeout(() => {
    startLiveFeed();
}, 300);

// ── VLC Stream Modal Helpers ──────────────────────────────────────────
const vlcBtn = document.getElementById('vlcBtn');
const vlcModal = document.getElementById('vlcModal');

function openVlcModal() {
    if (!vlcModal) return;
    const host = window.location.host; // includes port
    const proto = window.location.protocol;
    const rawUrl = `${proto}//${host}/video_feed`;
    const inferUrl = `${proto}//${host}/video_feed?infer=1`;

    const rawInput = document.getElementById('vlcStreamUrlRaw');
    const inferInput = document.getElementById('vlcStreamUrlInfer');
    if (rawInput) rawInput.value = rawUrl;
    if (inferInput) inferInput.value = inferUrl;

    vlcModal.style.display = 'flex';
}

function closeVlcModal() {
    if (vlcModal) vlcModal.style.display = 'none';
}

function copyStreamUrl(withInfer) {
    const inputId = withInfer ? 'vlcStreamUrlInfer' : 'vlcStreamUrlRaw';
    const input = document.getElementById(inputId);
    if (!input) return;

    input.select();
    input.setSelectionRange(0, 99999);
    navigator.clipboard.writeText(input.value).then(() => {
        const btn = event?.target;
        if (btn && btn.tagName === 'BUTTON') {
            const orig = btn.innerText;
            btn.innerText = '✓ Copied!';
            btn.style.borderColor = 'var(--color-clean)';
            btn.style.color = 'var(--color-clean)';
            setTimeout(() => {
                btn.innerText = orig;
                btn.style.borderColor = '';
                btn.style.color = '';
            }, 1800);
        }
    }).catch(err => {
        console.error('Clipboard copy failed:', err);
    });
}

if (vlcBtn) {
    vlcBtn.addEventListener('click', openVlcModal);
}

if (vlcModal) {
    vlcModal.addEventListener('click', (e) => {
        if (e.target === vlcModal) closeVlcModal();
    });
}

// ── Custom Stream Input Modal Helpers ─────────────────────────────────
const streamInputModal = document.getElementById('streamInputModal');

function showStreamInputModal() {
    if (streamInputModal) {
        streamInputModal.style.display = 'flex';
        const input = document.getElementById('customStreamUrlInput');
        if (input) {
            input.focus();
        }
    }
}

function closeStreamInputModal() {
    if (streamInputModal) streamInputModal.style.display = 'none';
}

async function submitCustomStreamUrl() {
    const input = document.getElementById('customStreamUrlInput');
    if (!input || !input.value.trim()) {
        alert('Please enter a valid RTSP or HTTP stream URL.');
        return;
    }

    const streamUrl = input.value.trim();
    try {
        const resp = await fetch('/api/camera/source', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source: streamUrl })
        });
        if (resp.ok) {
            closeStreamInputModal();
            await fetchCameraSources();
            updateStats();
            if (isLiveActive) startLiveFeed();
        }
    } catch (err) {
        console.error('Failed to set custom stream URL:', err);
        alert('Could not connect to the specified stream URL.');
    }
}

if (streamInputModal) {
    streamInputModal.addEventListener('click', (e) => {
        if (e.target === streamInputModal) closeStreamInputModal();
    });
}

