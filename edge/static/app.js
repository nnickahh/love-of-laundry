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
const liveBadge   = document.getElementById('liveBadge');

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
    liveBadge.classList.remove('active');
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
    if (el) el.textContent = '';
}

function _renderWsFrame(jpeg_b64, boxes) {
    _offscreenImg.onload = () => {
        ctx.drawImage(_offscreenImg, 0, 0, canvas.width, canvas.height);

        const garmentClasses = new Set(['shirt','jacket','jeans','underwear','dress','shorts','skirt']);
        boxes.forEach(b => {
            const x1 = b.box[0] * canvas.width;
            const y1 = b.box[1] * canvas.height;
            const x2 = b.box[2] * canvas.width;
            const y2 = b.box[3] * canvas.height;
            const w  = x2 - x1;
            const h  = y2 - y1;

            const isDefect    = !garmentClasses.has(b.label);
            const strokeColor = isDefect ? '#f04a6e' : '#10b981';
            const glowColor   = isDefect ? 'rgba(240,74,110,0.5)' : 'rgba(16,185,129,0.5)';

            ctx.shadowColor = glowColor;
            ctx.shadowBlur  = 12;
            ctx.strokeStyle = strokeColor;
            ctx.lineWidth   = 2.5;
            ctx.strokeRect(x1, y1, w, h);
            ctx.shadowBlur  = 0;

            const txt      = `${b.label.toUpperCase()} ${Math.round(b.confidence * 100)}%`;
            ctx.font        = 'bold 11px Outfit, sans-serif';
            const txtWidth  = ctx.measureText(txt).width;
            const pillH     = 20;
            const pillY     = y1 > pillH + 4 ? y1 - pillH - 2 : y1 + 4;

            ctx.fillStyle = strokeColor;
            ctx.beginPath();
            ctx.roundRect(x1 - 1, pillY, txtWidth + 12, pillH, 4);
            ctx.fill();

            ctx.fillStyle = '#ffffff';
            ctx.fillText(txt, x1 + 5, pillY + 13);
        });
        _fpsFrameCount++;
    };
    _offscreenImg.src = 'data:image/jpeg;base64,' + jpeg_b64;
}

function startLiveFeed() {
    if (ws) { ws.close(); ws = null; }

    isLiveActive  = true;
    hasScanResult = false;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    placeholder.style.display = 'none';
    // Show canvas directly (no <img> tag needed)
    canvas.style.display      = 'block';
    liveBadge.classList.add('active');
    document.getElementById('viewportStatus').textContent = 'Live';

    const btn = document.getElementById('liveBtn');
    btn.innerHTML = '⏹ Stop Live Feed';
    btn.classList.add('active');

    const infer = liveInferCheck && liveInferCheck.checked;
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
    liveBadge.classList.remove('active');
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

        document.getElementById('cameraMode').innerText = data.camera_mock ? '🟡 Mock Mode' : '🟢 Webcam Active';

    } catch (e) {
        console.error('Status fetch failed', e);
        const syncDot = document.getElementById('syncDot');
        syncDot.className = 'status-dot offline';
        document.getElementById('syncText').innerText = 'Server Offline';
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
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

        const garmentClasses = ['shirt', 'jacket', 'jeans', 'underwear', 'dress'];

        boxes.forEach(b => {
            const x1 = b.box[0] * canvas.width;
            const y1 = b.box[1] * canvas.height;
            const x2 = b.box[2] * canvas.width;
            const y2 = b.box[3] * canvas.height;
            const w  = x2 - x1;
            const h  = y2 - y1;

            const isDefect    = !garmentClasses.includes(b.label);
            const strokeColor = isDefect ? '#f04a6e' : '#10b981';
            const glowColor   = isDefect ? 'rgba(240,74,110,0.5)' : 'rgba(16,185,129,0.5)';

            // Glow shadow
            ctx.shadowColor = glowColor;
            ctx.shadowBlur  = 12;
            ctx.strokeStyle = strokeColor;
            ctx.lineWidth   = 2.5;
            ctx.strokeRect(x1, y1, w, h);
            ctx.shadowBlur  = 0;

            // Label background pill
            const txt      = `${b.label.toUpperCase()} ${Math.round(b.confidence * 100)}%`;
            ctx.font        = 'bold 11px Outfit, sans-serif';
            const txtWidth  = ctx.measureText(txt).width;
            const pillH     = 20;
            const pillY     = y1 > pillH + 4 ? y1 - pillH - 2 : y1 + 4;

            ctx.fillStyle = strokeColor;
            ctx.beginPath();
            ctx.roundRect(x1 - 1, pillY, txtWidth + 12, pillH, 4);
            ctx.fill();

            ctx.fillStyle = '#ffffff';
            ctx.fillText(txt, x1 + 5, pillY + 13);
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
        const data = await resp.json();

        currentScan   = data;
        hasScanResult = true;

        // Show scan snapshot in overlay
        placeholder.style.display = 'none';
        renderBoxes(data.image_url, data.boxes);
        document.getElementById('viewportStatus').textContent = 'Scan Result — ' + (wasLive ? 'Resume Feed below' : '');

        applyResultToUI(data, /*isFromBatch=*/false);

        document.getElementById('confirmBtn').disabled = false;
        document.getElementById('resetBtn').disabled   = false;

    } catch (e) {
        console.error('Scan failed:', e);
        alert('Inference Server Error. Check that best.pt model is present.');
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
            batchItems = data.map(item => ({ ...item, confirmed: false }));
            document.getElementById('batchScansContainer').style.display = 'block';
            document.getElementById('batchCount').innerText = batchItems.length;
            renderBatchList();
            if (batchItems.length > 0) loadBatchItem(0);
        }
    } catch (err) {
        console.error('Batch upload failed:', err);
        alert('Batch upload failed.');
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
        defectsList.innerHTML = `<div style="text-align:center; color:var(--text-secondary); padding:1.5rem 0; font-size:0.88rem;">✓ No defects detected.</div>`;
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
    document.getElementById('defectsList').innerHTML   = `<div style="text-align:center; color:var(--text-secondary); padding:2rem 0; font-size:0.88rem;">No defects detected yet.</div>`;

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

