(function(){
  // Initialize Socket.IO (socket.io script is loaded from CDN in the template)
  const socket = io();

  // State
  let alertCount = 0;
  let alertHistory = new Array(60).fill(0);
  let frameCache = {};
  let latestFrameByCam = {};
  let frameHeartbeat = {};
  let cameraUiRenderTs = {};
  let cameraRenderQueued = {};
  let snapshots = [];
  let streamPaused = (localStorage.getItem('streamPaused') === '1');
  let soundEnabled = (localStorage.getItem('soundEnabled') !== '0');
  let fpsByCam = {};
  let lastFrameTs = {};
  let activeModalCam = null;
  let modalRenderTs = 0;
  const CAMERA_RENDER_MIN_INTERVAL_MS = 85;
  const MODAL_RENDER_MIN_INTERVAL_MS = 60;
  let pageVisible = !document.hidden;

  // Safe getters for DOM elements that may not exist immediately
  function $(sel){ return document.querySelector(sel); }
  function $id(id){ return document.getElementById(id); }

  // --- Socket handlers ---
  socket.on('connect', () => console.log('[WS] connected'));
  socket.on('disconnect', () => console.log('[WS] disconnected'));

  socket.on('new_alert', (a)=>{ appendAlert(a); showToast(a); alertHistory[alertHistory.length-1]++; updateChart(); });
  socket.on('threat_update', (d)=>{ setThreatLevel(d.level, d.total); });
  socket.on('mqtt_status', (d)=>{ const el = $id('mqtt-status'); if (el) { el.textContent = d.connected ? 'ONLINE' : 'OFFLINE'; el.className = d.connected ? 'ts-value mqtt-online' : 'ts-value mqtt-offline'; } });

  socket.on('frame_update', (d)=>{
    try {
      frameCache[d.camera_id] = d.frame;
      latestFrameByCam[d.camera_id] = d.frame;
      frameHeartbeat[d.camera_id] = Date.now();

      if (streamPaused || (document.hidden)) return;
      scheduleCameraRender(d.camera_id);

      // compute smoothed fps and latency
      const now = Date.now();
      const last = lastFrameTs[d.camera_id] || 0;
      const delta = last ? (now - last) : 0;
      const instFps = delta ? (1000 / delta) : 0;
      const prev = fpsByCam[d.camera_id] || instFps;
      const sm = prev * 0.65 + instFps * 0.35;
      fpsByCam[d.camera_id] = sm; lastFrameTs[d.camera_id] = now;
      const fpsEl = $id('fps-' + d.camera_id); if (fpsEl) fpsEl.textContent = `${Math.max(0, Math.round(sm))} fps`;
      const latEl = $id('lat-' + d.camera_id); if (latEl) latEl.textContent = `${Date.now() - frameHeartbeat[d.camera_id]} ms`;

      // If the modal is open for this cam, update modal image throttled
      if (activeModalCam === d.camera_id) {
        const pnow = performance.now();
        if ((pnow - modalRenderTs) < MODAL_RENDER_MIN_INTERVAL_MS) return;
        modalRenderTs = pnow;
        const modalImg = $id('cam-modal-img');
        if (modalImg) {
          modalImg.classList.remove('loaded');
          modalImg.onload = ()=> modalImg.classList.add('loaded');
          modalImg.src = 'data:image/jpeg;base64,' + d.frame;
        }
      }
    } catch(e) { console.error(e); }
  });

  // --- Render camera frames into <img> tags ---
  function scheduleCameraRender(cameraId){
    if (cameraRenderQueued[cameraId]) return;
    cameraRenderQueued[cameraId] = true;
    requestAnimationFrame(()=>{
      cameraRenderQueued[cameraId] = false;
      const img = $id(`feed-${cameraId}`);
      if (!img) return;
      const now = performance.now();
      const last = cameraUiRenderTs[cameraId] || 0;
      if ((now - last) < CAMERA_RENDER_MIN_INTERVAL_MS) return;
      const frame = latestFrameByCam[cameraId]; if (!frame) return;
      const ph = $id(`ph-${cameraId}`);
      img.classList.remove('loaded');
      img.onload = ()=> img.classList.add('loaded');
      img.src = 'data:image/jpeg;base64,' + frame;
      img.style.display = 'block';
      if (ph) ph.style.display = 'none';
      cameraUiRenderTs[cameraId] = now;
    });
  }

  // --- Alerts feed ---
  function appendAlert(a){
    const feed = $id('alert-feed');
    if (!feed) return;
    // remove placeholder if present
    const ph = feed.querySelector('div[style]'); if (ph) ph.remove();
    const badge = `badge-${a.threat_level}`;
    const item = document.createElement('div'); item.className = 'alert-item';
    item.innerHTML = `<div class="alert-header"><span class="alert-badge ${badge}">${a.threat_level}</span><span class="alert-time">${a.timestamp}</span></div><div class="alert-event">${a.event_type}</div><div style="display:flex;justify-content:space-between;margin-top:2px"><span class="alert-cam">${a.camera_id}</span><span class="alert-conf">CONF: ${a.confidence}%</span></div>`;
    feed.insertBefore(item, feed.firstChild);
    while (feed.children.length > 80) feed.removeChild(feed.lastChild);
    alertCount++; $id('stat-total') && ($id('stat-total').textContent = alertCount);
  }

  // --- Threat UI ---
  function setThreatLevel(level){
    const badge = $id('threat-badge'); const stat = $id('stat-threat');
    if (badge) { badge.className = `threat-${level}`; badge.textContent = `● ${level}`; }
    if (stat)  { stat.textContent = level; }
  }

  // --- Toasts ---
  let toastTimer = null;
  function showToast(a){
    const t = $id('toast'); if (!t) return;
    t.innerHTML = `⚠ ${a.event_type.toUpperCase()} detected at ${a.camera_id}<br><span style="color:var(--text-dim)">Confidence: ${a.confidence}% · ${a.timestamp}</span>`;
    const prog = document.createElement('div'); prog.className = 'toast-progress'; prog.style.width = '100%'; t.appendChild(prog);
    t.classList.add('show'); clearTimeout(toastTimer);
    requestAnimationFrame(()=>{ prog.style.transition = 'width 3.5s linear'; prog.style.width = '0%'; });
    toastTimer = setTimeout(()=>{ t.classList.remove('show'); try{ prog.remove(); }catch(e){} }, 3500);
  }

  // --- Clock ---
  function updateClock(){ $id('clock') && ($id('clock').textContent = new Date().toTimeString().slice(0,8)); }
  setInterval(updateClock, 1000); updateClock();

  // --- Chart (lightweight) ---
  let alertChart = null;
  try {
    const chartCtx = $id('alertChart') && $id('alertChart').getContext('2d');
    if (chartCtx) {
      alertChart = new Chart(chartCtx, { type:'bar', data:{ labels: alertHistory.map(()=>''), datasets:[{ data: alertHistory, backgroundColor:'rgba(0,245,200,0.25)', borderColor:'#00f5c8', borderWidth:1 }] }, options: { responsive:true, plugins:{ legend:{display:false} }, scales:{ x:{display:false}, y:{ display:true, grid:{color:'#0a2218'}, ticks:{color:'#4a7a70', maxTicksLimit:3, font:{size:8}}, beginAtZero:true } }, animation:false } });
    }
  } catch(e){ console.warn('Chart init failed', e); }
  function updateChart(){ if (!alertChart) return; alertChart.data.datasets[0].data = [...alertHistory]; alertChart.update('none'); }
  setInterval(()=>{ if (document.hidden) return; alertHistory.shift(); alertHistory.push(0); updateChart(); }, 2000);

  // --- Radar (reuse canvas code from template) ---
  (function(){
    const rc = $id('radar-canvas'); if (!rc) return; const rctx = rc.getContext('2d'); let radarAngle = 0; let radarBlips = []; let radarTimer = null; function drawRadarFrame(){ const W = rc.width, H = rc.height, cx = W/2, cy = H/2, R = 54; rctx.clearRect(0,0,W,H); rctx.beginPath(); rctx.arc(cx,cy,R,0,Math.PI*2); rctx.fillStyle = '#030a08'; rctx.fill(); rctx.strokeStyle = '#0a2218'; rctx.lineWidth = 1; rctx.stroke(); [0.25,0.5,0.75,1].forEach(f=>{ rctx.beginPath(); rctx.arc(cx,cy,R*f,0,Math.PI*2); rctx.strokeStyle = '#0d2820'; rctx.stroke(); }); rctx.strokeStyle = '#0d2820'; rctx.beginPath(); rctx.moveTo(cx-R,cy); rctx.lineTo(cx+R,cy); rctx.stroke(); rctx.beginPath(); rctx.moveTo(cx,cy-R); rctx.lineTo(cx,cy+R); rctx.stroke(); rctx.save(); rctx.translate(cx, cy); rctx.rotate(radarAngle); const g = rctx.createLinearGradient(0, -R, 0, 0); g.addColorStop(0, 'rgba(0,245,200,0)'); g.addColorStop(1, 'rgba(0,245,200,0.35)'); rctx.beginPath(); rctx.moveTo(0,0); rctx.arc(0,0,R, -Math.PI/2, -Math.PI/2 + 1.2); rctx.closePath(); rctx.fillStyle = g; rctx.fill(); rctx.beginPath(); rctx.moveTo(0,0); rctx.lineTo(0,-R); rctx.strokeStyle = '#00f5c8'; rctx.lineWidth = 1.5; rctx.stroke(); rctx.restore(); radarBlips = radarBlips.filter(b=>b.age<60); radarBlips.forEach(b=>{ b.age++; const alpha = 1 - b.age/60; rctx.beginPath(); rctx.arc(cx+b.x, cy+b.y, 3, 0, Math.PI*2); rctx.fillStyle = `rgba(0,245,200,${alpha})`; rctx.fill(); }); if (Math.random() < 0.04) { const dist = (0.3 + Math.random()*0.65)*R; const ang  = radarAngle - Math.PI/2 + (Math.random()-0.5)*0.3; radarBlips.push({ x: dist*Math.cos(ang), y: dist*Math.sin(ang), age:0 }); } radarAngle += 0.04; }
    function start(){ if (radarTimer) return; drawRadarFrame(); radarTimer = setInterval(drawRadarFrame, 120); }
    function stop(){ if (!radarTimer) return; clearInterval(radarTimer); radarTimer = null; }
    $id('radar-wrap') && ($id('radar-wrap').style.display = 'flex'); $id('radar-btn') && ($id('radar-btn').textContent = 'RADAR OFF'); start();
  })();

  // --- Network map drawing (on demand) ---
  function drawNetmap(){ const canvas = $id('netmap-canvas'); if (!canvas) return; const ctx = canvas.getContext('2d'); const W = canvas.width, H = canvas.height; ctx.clearRect(0,0,W,H); ctx.fillStyle = 'rgba(8,14,18,0.95)'; ctx.fillRect(0,0,W,H); ctx.font = '9px Courier New'; ctx.textAlign = 'center'; const nodes = [ { x:90, y:20,  label:'INTERNET', icon:'🌐', color:'#ffd600' }, { x:90, y:65,  label:'ROUTER',   icon:'🔀', color:'#00f5c8' }, { x:90, y:110, label:'SWITCH',   icon:'⚡', color:'#00f5c8' }, { x:20, y:150, label:'CAM-01',   icon:'📷', color:'#00ff88' }, { x:60, y:150, label:'CAM-02',   icon:'📷', color:'#00ff88' }, { x:120,y:150, label:'SERVER',   icon:'🖥',  color:'#00f5c8' }, { x:160,y:150, label:'CAM-03',   icon:'📷', color:'#00ff88' }, ]; const edges = [[0,1],[1,2],[2,3],[2,4],[2,5],[2,6]]; ctx.setLineDash([3,3]); ctx.lineDashOffset = -(Date.now()/80) % 6; edges.forEach(([a,b])=>{ ctx.beginPath(); ctx.moveTo(nodes[a].x, nodes[a].y); ctx.lineTo(nodes[b].x, nodes[b].y); ctx.strokeStyle = '#0d2820'; ctx.lineWidth = 1; ctx.stroke(); }); ctx.setLineDash([]); nodes.forEach(n=>{ ctx.fillStyle = n.color + '22'; ctx.beginPath(); ctx.arc(n.x, n.y, 10, 0, Math.PI*2); ctx.fill(); ctx.strokeStyle = n.color; ctx.lineWidth = 1; ctx.stroke(); ctx.fillStyle = n.color; ctx.font = '8px Courier New'; ctx.fillText(n.label, n.x, n.y+22); ctx.font = '11px serif'; ctx.fillText(n.icon, n.x, n.y+4); }); }

  // --- Camera modal ---
  function openCameraModal(id){ activeModalCam = id; $id('cam-modal') && $id('cam-modal').classList.add('show'); $id('cam-modal-title') && ($id('cam-modal-title').textContent = `${id} LIVE VIEW`); const modalImg = $id('cam-modal-img'); if (modalImg && frameCache[id]) { modalImg.classList.remove('loaded'); modalImg.onload = ()=> modalImg.classList.add('loaded'); modalImg.src = 'data:image/jpeg;base64,' + frameCache[id]; } }
  function closeCameraModal(evt){ if (evt && evt.target && evt.target.id !== 'cam-modal') return; $id('cam-modal') && $id('cam-modal').classList.remove('show'); document.querySelectorAll('.cam-tile').forEach(t=> t.classList.remove('active-cam')); activeModalCam = null; }
  window.openCameraModal = openCameraModal; window.closeCameraModal = closeCameraModal;

  function captureSnapshot(fromModal=false){ const cam = fromModal && activeModalCam ? activeModalCam : (document.querySelector('.cam-tile.active-cam') && document.querySelector('.cam-tile.active-cam').id.replace('tile-','')) || 'CAM-01'; const frame = frameCache[cam]; if (!frame) return; const item = { id: Date.now(), camera: cam, ts: new Date().toLocaleTimeString(), src: 'data:image/jpeg;base64,'+frame }; snapshots.unshift(item); snapshots = snapshots.slice(0,24); renderSnapshots(); }
  window.captureSnapshot = captureSnapshot;

  function renderSnapshots(){ const list = $id('snapshot-list'); if (!list) return; if (!snapshots.length){ list.innerHTML = '<div class="snapshot-meta">No snapshots yet.</div>'; return; } list.innerHTML = snapshots.map((s, i)=>`<div class="snapshot-item" data-idx="${i}"><img src="${s.src}" alt="snapshot"><div class="snapshot-meta">${s.camera} • ${s.ts}</div></div>`).join(''); // attach click handlers
    list.querySelectorAll('.snapshot-item').forEach(el=> el.addEventListener('click', (e)=>{ const idx = Number(el.getAttribute('data-idx')); openLightbox(idx); })); updateLightboxThumbs(); }
  function clearSnapshots(){ snapshots = []; renderSnapshots(); }
  window.clearSnapshots = clearSnapshots;

  // --- Lightbox / Carousel ---
  let lbIndex = 0;
  function openLightbox(index){ if (!snapshots.length) return; lbIndex = Math.max(0, Math.min(index, snapshots.length-1)); const lb = $id('lightbox'); const img = $id('lightbox-img'); if (!lb || !img) return; img.src = snapshots[lbIndex].src; lb.classList.add('show'); lb.setAttribute('aria-hidden','false'); updateLightboxThumbs(); }
  function closeLightbox(){ const lb = $id('lightbox'); if (!lb) return; lb.classList.remove('show'); lb.setAttribute('aria-hidden','true'); }
  function lightboxNext(){ if (snapshots.length===0) return; lbIndex = (lbIndex+1) % snapshots.length; $id('lightbox-img').src = snapshots[lbIndex].src; updateLightboxThumbs(); }
  function lightboxPrev(){ if (snapshots.length===0) return; lbIndex = (lbIndex-1 + snapshots.length) % snapshots.length; $id('lightbox-img').src = snapshots[lbIndex].src; updateLightboxThumbs(); }
  function updateLightboxThumbs(){ const thumbs = $id('lightbox-thumbs'); if (!thumbs) return; thumbs.innerHTML = snapshots.map((s,i)=>`<img src="${s.src}" data-idx="${i}" class="${i===lbIndex? 'active':''}">`).join(''); thumbs.querySelectorAll('img').forEach(im=> im.addEventListener('click', ()=>{ const ix = Number(im.getAttribute('data-idx')); openLightbox(ix); })); }
  window.openLightbox = openLightbox; window.closeLightbox = closeLightbox; window.lightboxNext = lightboxNext; window.lightboxPrev = lightboxPrev;

  // keyboard navigation for lightbox and shortcuts
  document.addEventListener('keydown', (e)=>{
    const tag = (document.activeElement && document.activeElement.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
    if (e.key === 'ArrowLeft') { if ($id('lightbox') && $id('lightbox').classList.contains('show')) { e.preventDefault(); lightboxPrev(); } }
    if (e.key === 'ArrowRight') { if ($id('lightbox') && $id('lightbox').classList.contains('show')) { e.preventDefault(); lightboxNext(); } }
    if (e.key === 'Escape') { if ($id('lightbox') && $id('lightbox').classList.contains('show')) { closeLightbox(); } else { closeCameraModal(); } }
    if (e.key === 'm' || e.key === 'M') { toggleMode(); }
    if (e.key === ' ') { e.preventDefault(); toggleStreamPause(); }
    if (e.key === 's' || e.key === 'S') { captureSnapshot(); }
    if (e.key === 'e' || e.key === 'E') { exportAlertsCsv(); }
  });

  // --- Export CSV placeholder (calls server) ---
  async function exportAlertsCsv(){ try{ const r = await fetch('/api/alerts?limit=500'); const d = await r.json(); const rows = d.alerts || []; const header = ['id','timestamp','camera_id','event_type','confidence','threat_level','details']; const csv = [header.join(',')].concat(rows.map(a => [a.id, `"${String(a.timestamp).replaceAll('"','""') }"`, a.camera_id, a.event_type, a.confidence, a.threat_level, `"${String(a.details||'').replaceAll('"','""') }"`].join(','))).join('\n'); const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `sentinel_alerts_${Date.now()}.csv`; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url); } catch(e){ console.error('CSV export failed', e); } }
  window.exportAlertsCsv = exportAlertsCsv;

  // --- Misc UI helpers ---
  function toggleStreamPause(){ streamPaused = !streamPaused; localStorage.setItem('streamPaused', streamPaused ? '1':'0'); const btn = $id('stream-btn'); if (btn) { btn.textContent = streamPaused ? 'RESUME STREAM' : 'PAUSE STREAM'; btn.classList.toggle('active', streamPaused); } }
  window.toggleStreamPause = toggleStreamPause;
  function toggleSound(){ soundEnabled = !soundEnabled; localStorage.setItem('soundEnabled', soundEnabled ? '1':'0'); const btn = $id('sound-btn'); if (btn) { btn.textContent = soundEnabled ? 'SOUND ON' : 'SOUND OFF'; btn.classList.toggle('active', !soundEnabled); } }
  window.toggleSound = toggleSound;

  function toggleMode(){ (async ()=>{ try{ const next = ($id('mode-status') && $id('mode-status').textContent==='ALERT') ? 'SIMPLE' : 'ALERT'; const res = await fetch('/api/mode', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({mode:next}) }); const data = await res.json(); const mode = data.mode || next; $id('mode-status') && ($id('mode-status').textContent = mode); $id('mode-btn') && ($id('mode-btn').textContent = `MODE: ${mode}`); const t = $id('toast'); if (t) { if (mode==='ALERT') t.innerHTML = '<strong>🔴 ALERT MODE ENABLED</strong><br><span style="color:var(--text-dim)">Notifications will be sent on detection (Telegram/WhatsApp)</span>'; else t.innerHTML = '<strong>✓ SIMPLE MODE ENABLED</strong><br><span style="color:var(--text-dim)">Detection visible only, no external notifications</span>'; t.classList.add('show'); setTimeout(()=> t.classList.remove('show'), 4200); } }catch(e){ console.error(e); } })(); }
  window.toggleMode = toggleMode;



  // restore UI from storage
  try{ const savedStream = localStorage.getItem('streamPaused'); if (savedStream) { streamPaused = savedStream === '1'; $id('stream-btn') && ($id('stream-btn').textContent = streamPaused ? 'RESUME STREAM' : 'PAUSE STREAM'); $id('stream-btn') && $id('stream-btn').classList.toggle('active', streamPaused); } }catch(e){}
  try{ const savedSound = localStorage.getItem('soundEnabled'); if (savedSound !== null) { soundEnabled = savedSound !== '0'; $id('sound-btn') && ($id('sound-btn').textContent = soundEnabled ? 'SOUND ON' : 'SOUND OFF'); } }catch(e){}

  // initial render snapshots
  renderSnapshots();

  // expose a few functions for inline onclicks that remain in template
  window.focusCamera = function(id){ document.querySelectorAll('.cam-tile').forEach(t=> t.classList.remove('active-cam')); const tile = $id('tile-'+id); if (tile) tile.classList.add('active-cam'); openCameraModal(id); };
  window.toggleRadar = function(){ const wrap = $id('radar-wrap'); if (!wrap) return; const btn = $id('radar-btn'); const on = wrap.style.display !== 'none'; wrap.style.display = on ? 'none' : 'flex'; if (btn) btn.textContent = on ? 'RADAR ON' : 'RADAR OFF'; };
  window.toggleNetmap = function(){ const nm = $id('netmap'); if (!nm) return; nm.classList.toggle('show'); if (nm.classList.contains('show')) drawNetmap(); };
  window.resetThreat = function(){ fetch('/api/reset_threat'); setThreatLevel('SAFE'); };
  window.setCameraFilter = function(cam){ try{ localStorage.setItem('cameraFilter', cam); }catch(e){} document.querySelectorAll('.cam-tile').forEach(tile=>{ if (cam === 'ALL') tile.style.display = ''; else tile.style.display = tile.id === `tile-${cam}` ? '' : 'none'; }); };
  window.setAlertFilter = function(level){ try{ localStorage.setItem('alertFilter', level); }catch(e){} document.getElementById('f-all') && document.getElementById('f-all').classList.remove('active'); document.getElementById('f-medium') && document.getElementById('f-medium').classList.remove('active'); document.getElementById('f-high') && document.getElementById('f-high').classList.remove('active'); if (level==='ALL') document.getElementById('f-all') && document.getElementById('f-all').classList.add('active'); if (level==='MEDIUM') document.getElementById('f-medium') && document.getElementById('f-medium').classList.add('active'); if (level==='HIGH') document.getElementById('f-high') && document.getElementById('f-high').classList.add('active'); };

  // --- Help Guide ---
  function openHelpGuide(){ const guide = $id('help-guide'); if (guide) guide.classList.add('show'); }
  function closeHelpGuide(evt){ if (evt && evt.target && evt.target.id !== 'help-guide') return; const guide = $id('help-guide'); if (guide) guide.classList.remove('show'); }
  window.openHelpGuide = openHelpGuide; window.closeHelpGuide = closeHelpGuide;

  // --- System Status Polling ---
  function updateSystemStatus(){
    (async ()=>{
      try{
        const res = await fetch('/api/state');
        const data = await res.json();
        const mqttEl = $id('mqtt-status');
        if (mqttEl) {
          mqttEl.textContent = data.mqtt_connected ? 'ONLINE' : 'OFFLINE';
          mqttEl.className = data.mqtt_connected ? 'ts-value mqtt-online' : 'ts-value mqtt-offline';
        }
        const modeEl = $id('mode-status');
        if (modeEl) {
          modeEl.textContent = data.mode;
          modeEl.className = `ts-value mode-${data.mode}`;
        }
      }catch(e){ console.error('Status update failed', e); }
    })();
  }
  setInterval(updateSystemStatus, 3000);
  updateSystemStatus();

})();
