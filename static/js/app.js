/**
 * CHRONOS Temporal Video Engine — Frontend Controller v4.0
 */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

/* ── State ── */
let currentJobId = null;
let currentSummary = null;
let pollTimer = null;
let processTimer = null;
let processStartMs = 0;
let currentEstimate = null;
let jobQueue = [];
let batchMode = false;
let activeQueueIdx = -1;
let displayedJobId = null;
let currentPlatform = 'tiktok';
let waBridgeReady = false;
let currentPreset = 'tiktok';

/* ── Elements ── */
const el = {
  dropZone: $('#drop-zone'),
  fileInput: $('#file-input'),
  metaPanel: $('#file-visual'),
  noFileVisual: $('#no-file-visual'),
  processBtn: $('#process-btn'),
  smartBtn: $('#smart-btn'),
  uploadView: $('#upload-view'),
  processView: $('#process-view'),
  completeView: $('#complete-view'),
  terminal: $('#terminal'),
  termToggle: $('#term-toggle'),
  progressRing: $('#progress-ring'),
  progressText: $('#progress-text'),
  statusLabel: $('#status-label'),
  downloadLink: $('#download-link'),
  smartBanner: $('#smart-banner'),
  smartTitle: $('#smart-title'),
  smartReasons: $('#smart-reasons'),
  timeEstBlock: $('#time-estimate-block'),
  timeEstVal: $('#time-est'),
  fasterAlts: $('#faster-alts'),
  timerElapsed: $('#timer-elapsed'),
  timerEst: $('#timer-est'),
  estSizeDisplay: $('#est-size-display'),
  thumbImg: $('#thumb-img'),
  queueArea: $('#queue-area'),
  queueList: $('#queue-list'),
  processQueueBtn: $('#process-queue-btn'),
  ffmpegCmd: $('#ffmpeg-cmd'),
  copyCmdBtn: $('#copy-cmd-btn'),
  pauseBtn: $('#pause-btn'),
  stopBtn: $('#stop-btn'),

  waGroup: $('#wa-group'),
  targetSizeGroup: $('#target-size-group'),
  presetStrip: $('#preset-strip'),
  platformToggle: $('#platform-toggle'),
  togglePill: $('#toggle-pill'),
  segStrip: $('#segment-strip'),
  uploadProgress: $('#upload-progress'),
  uploadFill: $('#upload-fill'),
  uploadMeta: $('#upload-meta'),
  comparisonPanel: $('#comparison-panel'),
  compGrid: $('#comp-grid'),
  holoClock: $('#holo-clock'),
};

const refs = {
  fpsSlider: $('#fps-slider'), fpsInput: $('#fps-input'), fpsValue: $('#fps-value'),
  crfSlider: $('#crf-slider'), crfInput: $('#crf-input'), crfLabel: $('#crf-label'),
  vbrSlider: $('#vbr-slider'), vbrInput: $('#vbr-input'),
  vbrGroup: $('#vbr-group'), crfGroup: $('#crf-group'),
  twoPassWrap: $('#two-pass-wrap'), chkTwoPass: $('#chk-two-pass'),
  audioBitrate: $('#audio-bitrate'), audioInput: $('#audio-input'),
  audioSliderWrap: $('#audio-slider-wrap'), audioMeta: $('#audio-meta'),
  hwGroup: $('#hw-group'),
};

/* ── Clock ── */
function updateClock() {
  const now = new Date();
  const h = now.getHours() % 12;
  const m = now.getMinutes();
  const s = now.getSeconds();
  const hDeg = (h + m/60) * 30;
  const mDeg = (m + s/60) * 6;
  const sDeg = s * 6;

  // Header right digital clock
  const dc = document.getElementById('holo-clock');
  if (dc) dc.textContent = now.toLocaleTimeString('en-US', { hour12: false });

  // Header left logo clock hands
  const logoH = document.getElementById('logo-h-hand');
  const logoM = document.getElementById('logo-m-hand');
  const logoS = document.getElementById('logo-s-hand');
  if (logoH) logoH.style.transform = `rotate(${hDeg}deg)`;
  if (logoM) logoM.style.transform = `rotate(${mDeg}deg)`;
  if (logoS) logoS.style.transform = `rotate(${sDeg}deg)`;

  // Loading screen clock hands
  const lH = document.getElementById('loading-h-hand');
  const lM = document.getElementById('loading-m-hand');
  const lS = document.getElementById('loading-s-hand');
  if (lH) lH.style.transform = `rotate(${hDeg}deg)`;
  if (lM) lM.style.transform = `rotate(${mDeg}deg)`;
  if (lS) lS.style.transform = `rotate(${sDeg}deg)`;
}
setInterval(updateClock, 1000);
updateClock();

/* ── Loading Screen ── */
window.addEventListener('load', () => {
  setTimeout(() => {
    const ls = document.getElementById('loading-screen');
    if (ls) { ls.style.opacity = '0'; setTimeout(() => ls.remove(), 800); }
  }, 2000);
});

/* ── Utils ── */
function fmtBytes(bytes) {
  if (!bytes) return '0 B';
  const k = 1024, sizes = ['B','KB','MB','GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}
function fmtTime(secs) {
  if (!secs || !isFinite(secs)) return '00:00';
  const m = Math.floor(secs / 60).toString().padStart(2,'0');
  const s = Math.floor(secs % 60).toString().padStart(2,'0');
  return `${m}:${s}`;
}
function safeSet(el, prop, val) { if (el) el[prop] = val; else console.warn('CHRONOS: missing element, tried to set ' + prop); }
function safeHtml(el, val) { if (el) el.innerHTML = val; else console.warn('CHRONOS: missing element, tried to set innerHTML'); }
function safeShow(el, show=true) { if (el) el.style.display = show ? '' : 'none'; }

function log(msg, type='') {
  if (!el.terminal) return;
  const line = document.createElement('span');
  line.className = 't-line ' + (type || '');
  line.textContent = '> ' + msg;
  el.terminal.appendChild(line);
  el.terminal.scrollTop = el.terminal.scrollHeight;
}
function setRing(pct) {
  const c = 2 * Math.PI * 90;
  if (el.progressRing) el.progressRing.style.strokeDashoffset = c - (pct / 100) * c;
  if (el.progressText) el.progressText.innerHTML = pct + '<span class="pct-sym">%</span>';
}
function getRadioVal(name) {
  const el = document.querySelector('input[name="' + name + '"]:checked');
  return (el && !el.disabled) ? el.value : null;
}
function setRadioVal(name, val) {
  const el = document.querySelector('input[name="' + name + '"][value="' + val + '"]');
  if (el && !el.disabled) { el.checked = true; el.dispatchEvent(new Event('change')); return true; }
  return false;
}
function debounce(fn, ms) {
  let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn.apply(this, args), ms); };
}
function clampInt(v, min, max) {
  const n = parseInt(v, 10); return isNaN(n) ? min : Math.max(min, Math.min(max, n));
}
function syncSliderInput(slider, input, min, max, onChange) {
  if (!slider || !input) return;
  slider.addEventListener('input', () => { input.value = slider.value; if (onChange) onChange(); });
  input.addEventListener('input', () => {
    if (input.value === '') return;
    const n = parseInt(input.value, 10); if (isNaN(n)) return;
    if (n >= min && n <= max) { slider.value = n; if (onChange) onChange(); }
  });
  input.addEventListener('blur', () => {
    const v = clampInt(input.value, min, max); input.value = v; slider.value = v; if (onChange) onChange();
  });
}

/* ── Hover Tooltip ── */
const hoverTip = $('#hover-tip');
let hoverTimer = null;

function showHoverTip(el, text) {
  if (!hoverTip || !text) return;
  hoverTip.textContent = text;
  const rect = el.getBoundingClientRect();
  const tipW = hoverTip.offsetWidth || 280;
  let left = rect.left + (rect.width / 2) - (tipW / 2);
  let top = rect.bottom + 10;
  if (left < 12) left = 12;
  if (left + tipW > window.innerWidth - 12) left = window.innerWidth - tipW - 12;
  if (top + 80 > window.innerHeight - 12) top = rect.top - 80;
  hoverTip.style.left = left + 'px';
  hoverTip.style.top = top + 'px';
  hoverTip.classList.add('active');
  clearTimeout(hoverTimer);
  hoverTimer = setTimeout(() => { if (hoverTip) hoverTip.classList.remove('active'); }, 3500);
}
function hideHoverTip() {
  clearTimeout(hoverTimer);
  if (hoverTip) hoverTip.classList.remove('active');
}

function attachHoverTip(el) {
  if (!el || !el.dataset.desc) return;
  el.addEventListener('mouseenter', () => showHoverTip(el, el.dataset.desc));
  el.addEventListener('mouseleave', hideHoverTip);
}

// Labels in segmented groups, toggles, inputs, sliders, buttons, etc.
$$('.segmented label[data-desc], .holo-toggle[data-desc], .holo-input[data-desc], .holo-slider-wrap[data-desc], .holo-btn[data-desc], .est-block[data-desc]').forEach(attachHoverTip);

/* ── Platform Toggle ── */
function initPlatformToggle() {
  $$('.platform-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.platform;
      if (target === currentPlatform) return;
      currentPlatform = target;
      $$('.platform-btn').forEach(b => b.classList.toggle('active', b === btn));
      el.platformToggle.dataset.active = target;
      applyPlatformUI();
      if (currentJobId) { updateSizeEstimate(); debouncedFetchEstimate(); }
    });
  });
}

function applyPlatformUI() {
  const isWA = currentPlatform === 'whatsapp';
  if (el.waGroup) el.waGroup.style.display = isWA ? 'block' : 'none';
  if (el.targetSizeGroup) el.targetSizeGroup.style.display = isWA ? 'none' : 'block';

  const adv = $('#config-advanced');
  const simple = $('#config-whatsapp-simple');
  if (adv) adv.style.display = isWA ? 'none' : '';
  if (simple) simple.style.display = isWA ? 'block' : 'none';
  if (el.presetStrip) el.presetStrip.style.display = isWA ? 'none' : '';

  const coreLabel = $('#core-label');
  if (coreLabel) coreLabel.textContent = isWA ? 'WhatsApp HD Optimizer' : 'Processing Core';
  if (el.processBtn) el.processBtn.textContent = isWA ? 'Compress' : 'Initiate';

  if (isWA) {
    const mode = getRadioVal('wa_mode') || 'status';
    if (mode === 'status') applyPreset('wa_status_hd');
    else applyPreset('wa_chat');
    updateWaSimpleSpec();
  } else {
    $$('.holo-preset').forEach(b => {
      const isWaPreset = b.dataset.preset.startsWith('wa_');
      b.style.display = isWaPreset ? 'none' : '';
    });
    const visible = $$('.holo-preset').filter(b => b.style.display !== 'none');
    if (visible.length) {
      $$('.holo-preset').forEach(b => b.classList.remove('active'));
      visible[0].classList.add('active');
      applyPreset(visible[0].dataset.preset);
    }
  }
  log(`PLATFORM: ${currentPlatform.toUpperCase()}`, 'info');
}

function updateWaSimpleSpec() {
  const mode = getRadioVal('wa_mode') || 'status';
  const spec = $('#wa-simple-spec');
  if (!spec) return;
  if (mode === 'status') {
    spec.textContent = '1080p • H.264 • 30fps • Original • VBR 2.5 Mbps • Auto-split >30s';
  } else {
    spec.textContent = '1080p • H.264 • 30fps • Original • CRF 18 • Single file';
  }
}

/* ── Hardware Detection ── */
function initHwStatus() {
  fetch('/hwstatus')
    .then(r => r.json())
    .then(d => {
      const map = { nvenc: 'dot-nvenc', qsv: 'dot-qsv', amf: 'dot-amf' };
      const inp = { nvenc: 'hw-nvenc', qsv: 'hw-qsv', amf: 'hw-amf' };
      Object.keys(d).forEach(k => {
        const st = d[k]; const dot = $(`#${map[k]}`); const input = $(`#${inp[k]}`);
        const label = input ? document.querySelector(`label[for="${inp[k]}"]`) : null;
        if (!dot || !input) return;
        if (st.state === 'working') {
          dot.className = 'dot green'; dot.title = 'Working'; input.disabled = false;
          if (label) label.style.opacity = '1';
        } else if (st.state === 'detected_not_working') {
          dot.className = 'dot orange'; dot.title = 'Driver issue — click for diagnostic'; input.disabled = true;
          if (label) label.style.opacity = '0.5';
          dot.style.cursor = 'pointer';
        } else {
          dot.className = 'dot red'; dot.title = 'Not available'; input.disabled = true;
          if (label) label.style.opacity = '0.5';
        }
      });
      if (refs.hwGroup) refs.hwGroup.style.display = 'block';
      Object.keys(map).forEach(k => {
        const dot = $(`#${map[k]}`); if (!dot) return;
        dot.addEventListener('click', () => {
          log(`DIAGNOSTIC: ${k.toUpperCase()}...`, 'info');
          fetch('/hwdiag').then(r => r.json()).then(diag => {
            if (diag.error) { log('DIAG ERR: ' + diag.error, 'error'); return; }
            const item = diag[k]; if (!item) return;
            log(`--- ${k.toUpperCase()} ---`, 'info');
            log(item.command, 'info');
            if (item.working) log('WORKING', 'info');
            else { log('FAILED', 'error'); (item.stderr || 'No output').split('\n').filter(l => l.trim()).forEach(l => log('  ' + l, 'error')); }
            log('--- END ---', 'info');
          }).catch(e => log('DIAG FAIL: ' + e.message, 'error'));
        });
      });
    }).catch(() => { if (refs.hwGroup) refs.hwGroup.style.display = 'block'; });
}

/* ── Audio UI ── */
function updateAudioUI() {
  const mode = getRadioVal('audio_mode');
  if (mode === 'lossless') { if (refs.audioSliderWrap) refs.audioSliderWrap.style.display = 'none'; if (refs.audioMeta) refs.audioMeta.style.display = 'none'; }
  else { if (refs.audioSliderWrap) refs.audioSliderWrap.style.display = 'block'; if (refs.audioMeta) refs.audioMeta.style.display = 'flex'; }
}

/* ── Two-pass visibility ── */
function updateTwoPass() {
  const strategy = getRadioVal('strategy');
  const hw = getRadioVal('hw_accel') || 'none';
  const codec = getRadioVal('codec');
  const show = strategy === 'vbr' && hw === 'none' && (codec === 'h264' || codec === 'hevc');
  if (refs.twoPassWrap) refs.twoPassWrap.style.display = show ? 'block' : 'none';
}

/* ── Slider updates ── */
function updateSliderTrack(slider) {
  if (!slider || !slider.parentElement) return;
  const track = slider.parentElement.querySelector('.slider-track');
  if (!track) return;
  const p = ((slider.value - slider.min) / (slider.max - slider.min)) * 100;
  track.style.width = p + '%';
}

const crfLabels = { 14:'Archive', 15:'Archive', 16:'Near Lossless', 17:'Near Lossless', 18:'Visually Lossless', 19:'High Fidelity', 20:'High Fidelity', 21:'Broadcast', 22:'Broadcast', 23:'Standard', 24:'Standard', 25:'Web', 26:'Web', 27:'Compressed', 28:'Compressed' };

syncSliderInput(refs.fpsSlider, refs.fpsInput, 1, 120, () => {
  if (refs.fpsValue) refs.fpsValue.textContent = refs.fpsSlider.value + ' FPS'; updateSliderTrack(refs.fpsSlider); updateSizeEstimate(); debouncedFetchEstimate();
});
if (refs.fpsSlider) refs.fpsSlider.addEventListener('input', () => updateSliderTrack(refs.fpsSlider));

syncSliderInput(refs.crfSlider, refs.crfInput, 14, 28, () => {
  if (refs.crfLabel) refs.crfLabel.textContent = crfLabels[refs.crfSlider.value] || 'Custom'; updateSliderTrack(refs.crfSlider); updateSizeEstimate(); debouncedFetchEstimate();
});
if (refs.crfSlider) refs.crfSlider.addEventListener('input', () => updateSliderTrack(refs.crfSlider));

syncSliderInput(refs.vbrSlider, refs.vbrInput, 500, 25000, () => {
  updateSliderTrack(refs.vbrSlider); updateSizeEstimate(); debouncedFetchEstimate();
});
if (refs.vbrSlider) refs.vbrSlider.addEventListener('input', () => updateSliderTrack(refs.vbrSlider));

syncSliderInput(refs.audioBitrate, refs.audioInput, 64, 1411, () => {
  updateSliderTrack(refs.audioBitrate); updateSizeEstimate(); debouncedFetchEstimate();
});
if (refs.audioBitrate) refs.audioBitrate.addEventListener('input', () => updateSliderTrack(refs.audioBitrate));

$$('input[name="strategy"]').forEach(r => r.addEventListener('change', () => {
  if (getRadioVal('strategy') === 'vbr') { if (refs.crfGroup) refs.crfGroup.style.display = 'none'; if (refs.vbrGroup) refs.vbrGroup.style.display = 'block'; }
  else { if (refs.crfGroup) refs.crfGroup.style.display = 'block'; if (refs.vbrGroup) refs.vbrGroup.style.display = 'none'; }
  updateTwoPass(); updateSizeEstimate(); debouncedFetchEstimate();
}));
$$('input[name="audio_mode"]').forEach(r => r.addEventListener('change', () => { updateAudioUI(); updateSizeEstimate(); debouncedFetchEstimate(); }));
$$('input[name="wa_mode"]').forEach(r => r.addEventListener('change', () => {
  if (currentPlatform === 'whatsapp') {
    const mode = getRadioVal('wa_mode') || 'status';
    if (mode === 'status') applyPreset('wa_status_hd');
    else applyPreset('wa_chat');
    updateWaSimpleSpec();
    updateSizeEstimate();
    debouncedFetchEstimate();
  }
}));
$$('input[name="codec"], input[name="hw_accel"]').forEach(r => r.addEventListener('change', () => { updateTwoPass(); updateSizeEstimate(); debouncedFetchEstimate(); }));

/* ── Presets ── */
const PRESETS = {
  tiktok: { res:'1080p', fps:60, aspect:'original', codec:'h264', container:'mp4', strategy:'crf', crf:18, vbr:12000, scale:'bicubic', preset:'slow', hevc_int:false, color:false, audio_mode:'lossy', audio_bitrate:192, hw_accel:'none', two_pass:false },
  optimal: { res:'1080p', fps:30, aspect:'original', codec:'h264', container:'mp4', strategy:'crf', crf:18, vbr:12000, scale:'bicubic', preset:'medium', hevc_int:false, color:false, audio_mode:'lossy', audio_bitrate:192, hw_accel:'none', two_pass:false },
  reddit: { res:'1080p', fps:30, aspect:'original', codec:'h264', container:'mp4', strategy:'crf', crf:18, vbr:12000, scale:'lanczos', preset:'slow', hevc_int:false, color:true, audio_mode:'lossy', audio_bitrate:192, hw_accel:'none', two_pass:false },
  compat: { res:'1080p', fps:30, aspect:'original', codec:'h264', container:'mp4', strategy:'crf', crf:20, vbr:12000, scale:'bicubic', preset:'medium', hevc_int:false, color:true, audio_mode:'lossy', audio_bitrate:192, hw_accel:'none', two_pass:false },
  wa_status: { res:'720p', fps:30, aspect:'original', codec:'h264', container:'mp4', strategy:'vbr', crf:23, vbr:1500, scale:'bicubic', preset:'medium', hevc_int:false, color:true, audio_mode:'lossy', audio_bitrate:128, hw_accel:'none', two_pass:false },
  wa_status_hd: { res:'1080p', fps:30, aspect:'original', codec:'h264', container:'mp4', strategy:'vbr', crf:21, vbr:2500, scale:'bicubic', preset:'medium', hevc_int:false, color:true, audio_mode:'lossy', audio_bitrate:128, hw_accel:'none', two_pass:false },
  wa_chat: { res:'1080p', fps:30, aspect:'original', codec:'h264', container:'mp4', strategy:'crf', crf:18, vbr:12000, scale:'bicubic', preset:'slow', hevc_int:false, color:true, audio_mode:'lossy', audio_bitrate:192, hw_accel:'none', two_pass:false },
  ksaevelo: { res:'1080p', fps:60, aspect:'original', codec:'h264', container:'mp4', strategy:'crf', crf:18, vbr:12000, scale:'bicubic', preset:'slow', hevc_int:false, color:false, audio_mode:'lossy', audio_bitrate:192, hw_accel:'none', two_pass:false },
};

function applyPreset(name) {
  const p = PRESETS[name]; if (!p) return;
  currentPreset = name;
  setRadioVal('res', p.res); setRadioVal('aspect', p.aspect); setRadioVal('codec', p.codec); setRadioVal('container', p.container);
  setRadioVal('strategy', p.strategy); setRadioVal('scale_filter', p.scale); setRadioVal('enc_preset', p.preset); setRadioVal('audio_mode', p.audio_mode);
  if (p.hw_accel && !setRadioVal('hw_accel', p.hw_accel)) setRadioVal('hw_accel', 'none');
  if (p.strategy === 'vbr') { if (refs.crfGroup) refs.crfGroup.style.display = 'none'; if (refs.vbrGroup) refs.vbrGroup.style.display = 'block'; }
  else { if (refs.crfGroup) refs.crfGroup.style.display = 'block'; if (refs.vbrGroup) refs.vbrGroup.style.display = 'none'; }
  if (refs.fpsSlider) { refs.fpsSlider.value = p.fps; refs.fpsInput.value = p.fps; if (refs.fpsValue) refs.fpsValue.textContent = p.fps + ' FPS'; updateSliderTrack(refs.fpsSlider); }
  if (refs.crfSlider) { refs.crfSlider.value = p.crf; refs.crfInput.value = p.crf; if (refs.crfLabel) refs.crfLabel.textContent = crfLabels[p.crf] || 'Custom'; updateSliderTrack(refs.crfSlider); }
  if (refs.vbrSlider) { refs.vbrSlider.value = p.vbr; refs.vbrInput.value = p.vbr; updateSliderTrack(refs.vbrSlider); }
  if (refs.audioBitrate) { refs.audioBitrate.value = p.audio_bitrate; refs.audioInput.value = p.audio_bitrate; updateSliderTrack(refs.audioBitrate); }
  const chkHevc = $('#chk-hevc-int'); if (chkHevc) chkHevc.checked = p.hevc_int;
  const chkColor = $('#chk-color'); if (chkColor) chkColor.checked = p.color;
  if (refs.chkTwoPass) refs.chkTwoPass.checked = p.two_pass || false;
  updateAudioUI(); updateTwoPass(); updateSizeEstimate();
  log('PRESET: ' + name.toUpperCase(), 'info');
  if (currentJobId) fetchEstimate();
}

$$('.holo-preset').forEach(btn => {
  btn.addEventListener('click', () => {
    $$('.holo-preset').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    applyPreset(btn.dataset.preset);
  });
});

/* ── Smart Recommend ── */
if (el.smartBtn) {
el.smartBtn.addEventListener('click', () => {
  if (!currentJobId) return;
  log('Analyzing source for optimal settings...', 'info');
  fetch(`/recommend/${currentJobId}?platform=${currentPlatform}`)
    .then(r => r.json())
    .then(rec => {
      if (rec.error) throw new Error(rec.error);
      setRadioVal('res', rec.resolution); setRadioVal('aspect', rec.aspect_mode); setRadioVal('codec', rec.codec);
      setRadioVal('container', rec.container); setRadioVal('strategy', rec.strategy); setRadioVal('scale_filter', rec.scale_filter);
      setRadioVal('enc_preset', rec.preset); setRadioVal('audio_mode', rec.audio_mode);
      if (rec.hw_accel && !setRadioVal('hw_accel', rec.hw_accel)) setRadioVal('hw_accel', 'none');
      if (rec.strategy === 'vbr') { if (refs.crfGroup) refs.crfGroup.style.display = 'none'; if (refs.vbrGroup) refs.vbrGroup.style.display = 'block'; }
      else { if (refs.crfGroup) refs.crfGroup.style.display = 'block'; if (refs.vbrGroup) refs.vbrGroup.style.display = 'none'; }
      if (refs.fpsSlider) { refs.fpsSlider.value = rec.fps; refs.fpsInput.value = rec.fps; if (refs.fpsValue) refs.fpsValue.textContent = rec.fps + ' FPS'; updateSliderTrack(refs.fpsSlider); }
      if (refs.crfSlider) { refs.crfSlider.value = rec.crf; refs.crfInput.value = rec.crf; if (refs.crfLabel) refs.crfLabel.textContent = crfLabels[rec.crf] || 'Custom'; updateSliderTrack(refs.crfSlider); }
      if (refs.vbrSlider) { refs.vbrSlider.value = rec.vbr_kbps; refs.vbrInput.value = rec.vbr_kbps; updateSliderTrack(refs.vbrSlider); }
      if (refs.audioBitrate) { refs.audioBitrate.value = rec.audio_bitrate; refs.audioInput.value = rec.audio_bitrate; updateSliderTrack(refs.audioBitrate); }
      const chkHevc = $('#chk-hevc-int'); if (chkHevc) chkHevc.checked = rec.hevc_int;
      const chkColor = $('#chk-color'); if (chkColor) chkColor.checked = rec.color_tags;
      if (refs.chkTwoPass) refs.chkTwoPass.checked = rec.two_pass || false;
      if (rec.wa_mode) setRadioVal('wa_mode', rec.wa_mode);
      updateAudioUI(); updateTwoPass(); updateSizeEstimate();
      safeShow(el.smartBanner, true);
      safeSet(el.smartTitle, 'textContent', rec.preset_name || 'CHRONOS AUTO');
      safeHtml(el.smartReasons, (rec.reasons || []).map(r => `<div>• ${r}</div>`).join(''));
      log('Smart config applied.', 'info');
      fetchEstimate();
    })
    .catch(err => log('Recommend error: ' + err.message, 'error'));
});
}

/* ── Target Size ── */
const QUALITY_FLOOR = { '480p': 1000, '720p': 2000, '1080p': 4000 };

const targetSizeBtn = $('#target-size-btn');
if (targetSizeBtn) {
targetSizeBtn.addEventListener('click', () => {
  const mb = parseFloat($('#target-size').value);
  if (!mb || !currentSummary || !currentSummary.duration) { log('Enter valid target size', 'error'); return; }
  const dur = currentSummary.duration;
  const audioKbps = getRadioVal('audio_mode') === 'lossy' ? parseInt(refs.audioBitrate ? refs.audioBitrate.value : 192) : 1411;
  const totalKbps = (mb * 8192) / dur;
  let videoKbps = Math.floor(totalKbps - audioKbps);
  const res = getRadioVal('res') || '1080p';
  const floor = QUALITY_FLOOR[res] || 1000;
  const warnEl = $('#target-size-warning');

  if (videoKbps < floor) {
    const minMB = ((floor + audioKbps) * dur) / 8192;
    const msg = `Target ${mb}MB requires ${videoKbps} kbps — too low for ${res}. Clamped to ${floor} kbps (~${minMB.toFixed(1)} MB min) to preserve quality.`;
    if (warnEl) warnEl.textContent = msg;
    log('QUALITY GUARDRAIL: ' + msg, 'error');
    videoKbps = floor;
  } else {
    if (warnEl) warnEl.textContent = '';
  }

  setRadioVal('strategy', 'vbr'); if (refs.crfGroup) refs.crfGroup.style.display = 'none'; if (refs.vbrGroup) refs.vbrGroup.style.display = 'block';
  if (refs.vbrSlider) { refs.vbrSlider.value = Math.min(25000, Math.max(floor, videoKbps)); if (refs.vbrInput) refs.vbrInput.value = refs.vbrSlider.value; updateSliderTrack(refs.vbrSlider); }
  updateTwoPass(); updateSizeEstimate(); debouncedFetchEstimate();
});
}

/* ── Upload / Queue ── */
function handleFiles(files) {
  const arr = Array.from(files).filter(f => f.type.startsWith('video/'));
  if (!arr.length) { log('Rejected: invalid format', 'error'); return; }
  arr.forEach(uploadFile);
}
function uploadFile(file) {
  log('Ingesting: ' + file.name);
  const form = new FormData(); form.append('video', file);

  if (el.uploadProgress) el.uploadProgress.style.display = 'block';
  if (el.uploadFill) el.uploadFill.style.width = '0%';
  if (el.uploadMeta) el.uploadMeta.textContent = 'Uploading to CHRONOS...';

  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/upload', true);

  xhr.upload.addEventListener('progress', (e) => {
    if (e.lengthComputable) {
      const pct = Math.round((e.loaded / e.total) * 100);
      if (el.uploadFill) el.uploadFill.style.width = pct + '%';
      if (el.uploadMeta) el.uploadMeta.textContent = `Uploading stream... ${pct}%`;
    }
  });

  xhr.addEventListener('load', () => {
    if (el.uploadProgress) el.uploadProgress.style.display = 'none';
    if (xhr.status === 200) {
      try {
        const data = JSON.parse(xhr.responseText);
        if (data.error) throw new Error(data.error);
        jobQueue.push({ jobId: data.job_id, summary: data.summary, filename: data.summary.filename, hasThumb: data.has_thumb, status: 'queued', outputSize: null, outputSummary: null, ffmpegCmd: null, outputFiles: [] });
        renderQueue(); log('Upload complete', 'info');
        if (!displayedJobId || !jobQueue.find(j => j.jobId === displayedJobId)) { refreshInputAnalysis(); fetchEstimate(); updateSizeEstimate(); }
      } catch (err) {
        log('Upload fail: ' + err.message, 'error');
      }
    } else {
      log('Upload failed: HTTP ' + xhr.status, 'error');
    }
  });

  xhr.addEventListener('error', () => {
    if (el.uploadProgress) el.uploadProgress.style.display = 'none';
    log('Upload network error', 'error');
  });

  xhr.send(form);
}
function renderQueue() {
  if (!el.queueList || !el.queueArea) return;
  if (!jobQueue.length) { el.queueArea.style.display = 'none'; return; }
  el.queueArea.style.display = 'block';
  el.queueList.innerHTML = jobQueue.map((j, i) => {
    const color = j.status === 'completed' ? 'done' : j.status === 'error' ? 'fail' : j.status === 'processing' ? 'proc' : '';
    const remove = (j.status === 'queued' || j.status === 'uploaded') ? `<span class="q-remove" data-idx="${i}" style="color:var(--danger);cursor:pointer;margin-left:4px;">×</span>` : '';
    return `<div class="queue-item"><span class="q-name">${j.filename}</span><span class="q-status ${color}">${j.status.toUpperCase()}</span>${remove}</div>`;
  }).join('');
  el.queueList.querySelectorAll('.q-remove').forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = parseInt(btn.dataset.idx);
      const job = jobQueue[idx]; if (!job || (job.status !== 'queued' && job.status !== 'uploaded')) return;
      fetch(`/delete/${job.jobId}`, { method: 'POST' }).finally(() => {
        const was = displayedJobId === job.jobId; jobQueue.splice(idx, 1); if (was) refreshInputAnalysis(); renderQueue();
      });
    });
  });
  const queued = jobQueue.filter(j => j.status === 'queued' || j.status === 'uploaded').length;
  if (el.processQueueBtn) el.processQueueBtn.textContent = queued ? `Process Queue (${queued})` : 'Process Queue';
  if (el.processQueueBtn) el.processQueueBtn.disabled = queued === 0;
}
function populateMeta(s) {
  if (!el.noFileVisual || !el.metaPanel) return;
  el.noFileVisual.style.display = 'none'; el.metaPanel.style.display = 'flex';
  const mName = $('#m-name'); if (mName) { mName.textContent = s.filename || 'UNKNOWN'; mName.title = s.filename || ''; }
  const mSize = $('#m-size'); if (mSize) mSize.textContent = fmtBytes(s.size_bytes);
  const mRes = $('#m-res'); if (mRes) mRes.textContent = (s.width && s.height) ? `${s.width}×${s.height}` : '—';
  const mDur = $('#m-dur'); if (mDur) mDur.textContent = fmtTime(s.duration);
  const mFps = $('#m-fps'); if (mFps) mFps.textContent = s.fps ? s.fps.toFixed(2) : '—';
  const mCodec = $('#m-codec'); if (mCodec) mCodec.textContent = (s.video_codec || '—').toUpperCase();
  const mBitrate = $('#m-bitrate'); if (mBitrate) mBitrate.textContent = s.bit_rate ? (parseInt(s.bit_rate)/1000).toFixed(0) + ' Kbps' : '—';
  const mFormat = $('#m-format'); if (mFormat) mFormat.textContent = s.format_name ? s.format_name.split(',')[0].toUpperCase() : '—';
  const mFrames = $('#m-frames'); if (mFrames) mFrames.textContent = s.nb_frames ? parseInt(s.nb_frames).toLocaleString() : '—';
  const mPix = $('#m-pix'); if (mPix) mPix.textContent = s.pix_fmt ? s.pix_fmt.toUpperCase() : '—';
  const mAudio = $('#m-audio'); if (mAudio) mAudio.textContent = s.has_audio ? 'Yes' : 'No';
}
function switchDisplayedJob(id) {
  if (!id) { displayedJobId = null; currentJobId = null; currentSummary = null; if (el.metaPanel) el.metaPanel.style.display = 'none'; if (el.noFileVisual) el.noFileVisual.style.display = 'flex'; if (el.thumbImg) { el.thumbImg.src = ''; } if (el.processBtn) el.processBtn.disabled = true; if (el.smartBtn) el.smartBtn.disabled = true; return; }
  const job = jobQueue.find(j => j.jobId === id); if (!job) return;
  displayedJobId = id; currentJobId = id; currentSummary = job.summary; populateMeta(job.summary);
  if (job.hasThumb && el.thumbImg) { el.thumbImg.src = `/thumbnail/${id}`; el.thumbImg.style.display = 'block'; }
  else if (el.thumbImg) { el.thumbImg.style.display = 'none'; el.thumbImg.src = ''; }
  if (el.processBtn) el.processBtn.disabled = false;
  if (el.smartBtn) el.smartBtn.disabled = false;
}
function refreshInputAnalysis() {
  const j = jobQueue.find(j => j.status === 'queued' || j.status === 'uploaded');
  if (j) switchDisplayedJob(j.jobId); else switchDisplayedJob(null);
}

if (el.dropZone) {
  el.dropZone.addEventListener('click', () => { if (el.fileInput) el.fileInput.click(); });
  el.dropZone.addEventListener('dragover', e => { e.preventDefault(); el.dropZone.classList.add('dragover'); });
  el.dropZone.addEventListener('dragleave', () => el.dropZone.classList.remove('dragover'));
  el.dropZone.addEventListener('drop', e => { e.preventDefault(); el.dropZone.classList.remove('dragover'); if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files); });
}
if (el.fileInput) el.fileInput.addEventListener('change', e => { if (e.target.files.length) handleFiles(e.target.files); });

/* ── Estimate ── */
function buildPayload() {
  return {
    job_id: currentJobId, resolution: getRadioVal('res'), fps: parseInt(refs.fpsSlider ? refs.fpsSlider.value : 60), aspect_mode: getRadioVal('aspect'),
    codec: getRadioVal('codec'), container: getRadioVal('container'), strategy: getRadioVal('strategy'), crf: parseInt(refs.crfSlider ? refs.crfSlider.value : 18),
    vbr_kbps: parseInt(refs.vbrSlider ? refs.vbrSlider.value : 12000), scale_filter: getRadioVal('scale_filter'), preset: getRadioVal('enc_preset'),
    hevc_intermediate: ($('#chk-hevc-int') && $('#chk-hevc-int').checked) || false, color_tags: ($('#chk-color') && $('#chk-color').checked) || false, audio_mode: getRadioVal('audio_mode'),
    audio_bitrate: parseInt(refs.audioBitrate ? refs.audioBitrate.value : 192), two_pass: (refs.chkTwoPass && refs.chkTwoPass.checked) || false, hw_accel: getRadioVal('hw_accel') || 'none',
    platform: currentPlatform, wa_mode: getRadioVal('wa_mode') || 'status',
    selected_preset: currentPreset,
  };
}
function fetchEstimate() {
  if (!currentJobId) return;
  const payload = buildPayload();
  fetch('/estimate', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) })
    .then(r => r.json()).then(d => {
      if (d.error) return; currentEstimate = d; safeShow(el.timeEstBlock, true);
      safeSet(el.timeEstVal, 'textContent', d.estimate ? ('~' + d.estimate.label) : '—');
      if (d.alternatives && d.alternatives.length) {
        safeHtml(el.fasterAlts, d.alternatives.map((a, i) => `
          <div class="alt-row" data-alt="${i}">
            <span class="alt-reason">${a.reason}</span><span class="alt-time">~${a.time_label}</span>
          </div>`).join(''));
        if (el.fasterAlts) el.fasterAlts.querySelectorAll('.alt-row').forEach(row => {
          row.addEventListener('click', () => {
            const alt = d.alternatives[parseInt(row.dataset.alt)]; if (!alt) return;
            if (alt.preset) setRadioVal('enc_preset', alt.preset); if (alt.resolution) setRadioVal('res', alt.resolution);
            if (alt.hevc_intermediate === false) { const chk = $('#chk-hevc-int'); if (chk) chk.checked = false; }
            if (alt.codec) setRadioVal('codec', alt.codec); if (alt.hw_accel) setRadioVal('hw_accel', alt.hw_accel);
            log('Applied: ' + alt.reason + ' (~' + alt.time_label + ')', 'info'); updateSizeEstimate(); fetchEstimate();
          });
        });
      } else safeHtml(el.fasterAlts, '');
    }).catch(() => {});
}
const debouncedFetchEstimate = debounce(fetchEstimate, 350);

function updateSizeEstimate() {
  if (!el.estSizeDisplay || !currentSummary || !currentSummary.duration) { if (el.estSizeDisplay) el.estSizeDisplay.textContent = ''; return; }
  const dur = currentSummary.duration, audioKbps = getRadioVal('audio_mode') === 'lossy' ? parseInt(refs.audioBitrate ? refs.audioBitrate.value : 192) : 1411;
  let videoKbps = 0;
  if (getRadioVal('strategy') === 'vbr') { videoKbps = parseInt(refs.vbrSlider ? refs.vbrSlider.value : 12000); }
  else {
    const orig = currentSummary.bit_rate ? (currentSummary.bit_rate / 1000) : 0;
    const rf = { '480p': 1.5, '720p': 3.5, '1080p': 7.0 }, pf = { 'medium': 1.0, 'slow': 0.85, 'veryslow': 0.75 };
    const crf = parseInt(refs.crfSlider ? refs.crfSlider.value : 18), cf = { 'h264': 1.0, 'hevc': 0.6, 'vp9': 0.55, 'av1': 0.45 };
    videoKbps = (rf[getRadioVal('res')] || 5) * (parseInt(refs.fpsSlider ? refs.fpsSlider.value : 60) / 30) * (pf[getRadioVal('enc_preset')] || 1) * Math.max(0.3, (28 - crf) / 10) * (cf[getRadioVal('codec')] || 1) * 1000;
    if (orig > 500 && videoKbps > orig * 1.2) videoKbps = orig * 1.1;
  }
  const totalMB = ((videoKbps + audioKbps) * dur) / 8192;
  const inMB = currentSummary.size_bytes / (1024 * 1024);
  let txt = getRadioVal('strategy') === 'vbr' ? `Est. ~${totalMB.toFixed(1)} MB (VBR)` : `Est. ~${totalMB.toFixed(1)} MB (CRF)`;
  if (inMB > 0 && getRadioVal('strategy') === 'vbr') {
    const pct = ((1 - totalMB / inMB) * 100);
    if (pct > 5) txt += ` | ${pct.toFixed(0)}% smaller`; else if (pct < -5) txt += ` | ${Math.abs(pct).toFixed(0)}% larger`;
  }
  if (currentPlatform === 'whatsapp' && getRadioVal('wa_mode') === 'status') {
    const segs = Math.ceil(dur / 30); txt += ` | ${segs} segment${segs > 1 ? 's' : ''}`;
  }
  safeSet(el.estSizeDisplay, 'textContent', txt);
}

/* ── Process / Timer ── */
function startClientTimer() {
  processStartMs = Date.now();
  processTimer = setInterval(() => { if (el.timerElapsed) el.timerElapsed.textContent = fmtTime(Math.floor((Date.now() - processStartMs) / 1000)); }, 1000);
}
function stopClientTimer() { clearInterval(processTimer); processTimer = null; }

function processQueue() {
  const queued = jobQueue.filter(j => j.status === 'queued' || j.status === 'uploaded');
  if (!queued.length) return;
  if (queued.length === 1) { batchMode = false; currentJobId = queued[0].jobId; currentSummary = queued[0].summary; startSingleJob(currentJobId); }
  else { batchMode = true; activeQueueIdx = 0; startBatchJob(0); }
}
function startSingleJob(id) {
  const payload = buildPayload();
  if (currentPlatform === 'whatsapp') {
    log(`Compress: WhatsApp ${payload.wa_mode.toUpperCase()} | HD Optimized`, 'info');
  } else {
    log(`Encode: ${payload.resolution} @ ${payload.fps}FPS | ${payload.codec.toUpperCase()} | ${payload.platform.toUpperCase()}`, 'info');
  }
  if (el.uploadView) el.uploadView.classList.remove('active');
  if (el.processView) el.processView.classList.add('active');
  if (el.completeView) el.completeView.classList.remove('active');
  if (el.processBtn) el.processBtn.disabled = true;
  if (el.smartBtn) el.smartBtn.disabled = true;
  if (el.timeEstBlock) el.timeEstBlock.style.display = 'none';
  setRing(0);
  if (el.pauseBtn) { el.pauseBtn.textContent = 'Pause'; el.pauseBtn.style.display = 'inline-flex'; }
  if (el.statusLabel) el.statusLabel.textContent = currentPlatform === 'whatsapp' ? 'Compressing' : 'Encoding';
  if (el.timerElapsed) el.timerElapsed.textContent = '00:00';
  if (el.timerEst) el.timerEst.textContent = currentEstimate && currentEstimate.estimate ? '~' + currentEstimate.estimate.label : '—';
  startClientTimer();
  fetch('/process', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) })
    .then(r => r.json()).then(data => {
      if (data.error) throw new Error(data.error);
      log('Mode: ' + (data.mode || 'direct'), 'info'); if (data.segments) log('Segments: ' + data.segments, 'info');
      startPolling(id);
    }).catch(err => { log('Process error: ' + err.message, 'error'); handleComplete(id, null, null, null, true); });
}
function startBatchJob(idx) {
  if (idx >= jobQueue.length) { finishBatch(); return; }
  const job = jobQueue[idx];
  if (job.status === 'completed' || job.status === 'error' || job.status === 'cancelled') { activeQueueIdx = idx + 1; startBatchJob(activeQueueIdx); return; }
  job.status = 'processing'; switchDisplayedJob(job.jobId); renderQueue();
  if (el.uploadView) el.uploadView.classList.remove('active');
  if (el.processView) el.processView.classList.add('active');
  if (el.completeView) el.completeView.classList.remove('active');
  if (el.processBtn) el.processBtn.disabled = true;
  if (el.smartBtn) el.smartBtn.disabled = true;
  if (el.timeEstBlock) el.timeEstBlock.style.display = 'none';
  setRing(0);
  if (el.pauseBtn) { el.pauseBtn.textContent = 'Pause'; el.pauseBtn.style.display = 'inline-flex'; }
  if (el.statusLabel) el.statusLabel.textContent = `Batch [${idx+1}/${jobQueue.length}]`;
  if (el.timerElapsed) el.timerElapsed.textContent = '00:00';
  if (el.timerEst) el.timerEst.textContent = currentEstimate && currentEstimate.estimate ? '~' + currentEstimate.estimate.label : '—';
  startClientTimer(); log(`Batch ${idx+1}/${jobQueue.length}: ${job.filename}`, 'info');
  fetch('/process', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(buildPayload()) })
    .then(r => r.json()).then(data => { if (data.error) throw new Error(data.error); startPolling(job.jobId); })
    .catch(err => { log('Batch error: ' + err.message, 'error'); handleComplete(job.jobId, null, null, null, true); });
}

if (el.processBtn) el.processBtn.addEventListener('click', processQueue);
if (el.processQueueBtn) el.processQueueBtn.addEventListener('click', processQueue);

/* ── Controls ── */
if (el.pauseBtn) {
el.pauseBtn.addEventListener('click', () => {
  if (!currentJobId) return; const job = jobQueue.find(j => j.jobId === currentJobId); if (!job) return;
  const action = job.status === 'processing' ? 'pause' : 'resume';
  fetch(`/control/${currentJobId}`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({action}) })
    .then(r => r.json()).then(d => {
      if (d.status === 'paused') { job.status = 'paused'; el.pauseBtn.textContent = 'Resume'; if (el.statusLabel) el.statusLabel.textContent = 'Paused'; log('Paused', 'info'); }
      else if (d.status === 'resumed') { job.status = 'processing'; el.pauseBtn.textContent = 'Pause'; if (el.statusLabel) el.statusLabel.textContent = batchMode ? `Batch [${activeQueueIdx+1}/${jobQueue.length}]` : 'Encoding'; log('Resumed', 'info'); }
    }).catch(() => {});
});
}
if (el.stopBtn) {
el.stopBtn.addEventListener('click', () => {
  if (!currentJobId) return; const job = jobQueue.find(j => j.jobId === currentJobId); if (!job) return;
  log('Aborting...', 'error');
  fetch(`/control/${currentJobId}`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({action:'stop'}) })
    .then(() => { if (el.statusLabel) el.statusLabel.textContent = 'Stopping'; })
    .catch(() => {});
});
}

/* ── Polling ── */
function startPolling(id) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => {
    fetch(`/status/${id}`).then(r => r.json()).then(d => {
      if (d.status === 'paused') { if (el.pauseBtn) el.pauseBtn.textContent = 'Resume'; if (el.statusLabel) el.statusLabel.textContent = 'Paused'; return; }
      if (d.status === 'processing') { if (el.pauseBtn) el.pauseBtn.textContent = 'Pause'; if (el.statusLabel) el.statusLabel.textContent = batchMode ? `Batch [${activeQueueIdx+1}/${jobQueue.length}]` : (currentPlatform === 'whatsapp' ? 'Compressing' : 'Encoding'); }
      if (d.progress != null) setRing(d.progress);
      if (d.log && d.log.length) {
        d.log.slice(-5).forEach(l => { if (!l) return; const last = el.terminal.lastElementChild; if (last && last.textContent === '> ' + l) return; log(l, l.toLowerCase().includes('error') ? 'error' : 'info'); });
      }
      if (d.elapsed_seconds != null && el.timerElapsed) el.timerElapsed.textContent = fmtTime(d.elapsed_seconds);
      if (d.status === 'completed') { clearInterval(pollTimer); stopClientTimer(); handleComplete(id, d.output_size, d.output_summary, d.ffmpeg_cmd, false, d.output_files || []); }
      else if (d.status === 'stopped') { clearInterval(pollTimer); stopClientTimer(); handleComplete(id, null, d.output_summary, d.ffmpeg_cmd, true, d.output_files || []); }
      else if (d.status === 'error' || d.status === 'cancelled') { clearInterval(pollTimer); stopClientTimer(); handleComplete(id, null, null, null, true, []); }
    });
  }, 800);
}

function handleComplete(id, outSize, outSummary, ffmpegCmd, isStopped, outputFiles) {
  const job = jobQueue.find(j => j.jobId === id);
  if (job) { job.status = isStopped ? 'stopped' : (outSize ? 'completed' : 'error'); job.outputSize = outSize; job.outputSummary = outSummary; job.ffmpegCmd = ffmpegCmd; job.outputFiles = outputFiles; }
  renderQueue(); if (el.pauseBtn) el.pauseBtn.style.display = 'none';
  if (batchMode) {
    if (isStopped || !outSize) log(`Batch ${isStopped ? 'stopped' : 'failed'}: ${job ? job.filename : id}`, isStopped ? 'info' : 'error');
    if (isStopped) { finishBatch(); return; }
    if (activeQueueIdx < jobQueue.length - 1) { activeQueueIdx++; setTimeout(() => startBatchJob(activeQueueIdx), 500); return; }
    finishBatch();
  } else {
    finalize(id, outSize, outSummary, ffmpegCmd, isStopped, outputFiles);
  }
}

function finalize(id, outSize, outSummary, ffmpegCmd, isStopped, outputFiles) {
  if (el.processView) el.processView.classList.remove('active');
  if (el.completeView) el.completeView.classList.add('active');
  setRing(isStopped ? 0 : 100);
  if (isStopped) {
    log('Stopped', 'info');
    const retryBtn = $('#retry-btn'); if (retryBtn) retryBtn.style.display = 'inline-flex';
    const deleteBtn = $('#delete-btn'); if (deleteBtn) deleteBtn.style.display = 'inline-flex';
    const resetBtn = $('#reset-btn'); if (resetBtn) resetBtn.style.display = 'inline-flex';
    if (el.downloadLink) el.downloadLink.style.display = 'none';
    if (el.segStrip) el.segStrip.style.display = 'none';
    if (el.comparisonPanel) el.comparisonPanel.style.display = 'none';
    if (el.ffmpegCmd) el.ffmpegCmd.textContent = ffmpegCmd || '';
    return;
  }
  log('Complete', 'info');
  const retryBtn = $('#retry-btn'); if (retryBtn) retryBtn.style.display = 'inline-flex';
  const deleteBtn = $('#delete-btn'); if (deleteBtn) deleteBtn.style.display = 'inline-flex';
  const resetBtn = $('#reset-btn'); if (resetBtn) resetBtn.style.display = 'inline-flex';
  const inS = currentSummary || {}, outS = outSummary || {};
  const inSize = inS.size_bytes || 0;
  if (inSize && outSize) { const pct = ((1 - outSize / inSize) * 100).toFixed(1); const saved = pct > 0 ? `${pct}% reduction` : `${Math.abs(pct)}% increase`; if ($('#reduction-val')) $('#reduction-val').textContent = saved; }
  else { if ($('#reduction-val')) $('#reduction-val').textContent = 'COMPLETE'; }

  /* Comparison Table */
  if (el.comparisonPanel && el.compGrid) {
    el.comparisonPanel.style.display = 'block';
    const inBitrate = inS.bit_rate ? (parseInt(inS.bit_rate)/1000).toFixed(0) + ' Kbps' : '—';
    const outBitrate = outS.bit_rate ? (parseInt(outS.bit_rate)/1000).toFixed(0) + ' Kbps' : '—';
    const inRes = (inS.width && inS.height) ? `${inS.width}×${inS.height}` : '—';
    const outRes = (outS.width && outS.height) ? `${outS.width}×${outS.height}` : inRes;
    const inDur = fmtTime(inS.duration || 0);
    const outDur = fmtTime(outS.duration || inS.duration || 0);
    const inCodec = (inS.video_codec || '—').toUpperCase();
    const outCodec = (outS.video_codec || getRadioVal('codec') || 'H.264').toUpperCase();
    const sizeClass = outSize && outSize < inSize ? 'improve' : (outSize > inSize ? 'degrade' : '');
    el.compGrid.innerHTML = `
      <div class="comp-row head"><span class="comp-metric">Metric</span><span class="comp-col">Original</span><span class="comp-col">Compressed</span></div>
      <div class="comp-row"><span class="comp-metric">File Size</span><span class="comp-col">${fmtBytes(inSize)}</span><span class="comp-col ${sizeClass}">${outSize ? fmtBytes(outSize) : '—'}</span></div>
      <div class="comp-row"><span class="comp-metric">Resolution</span><span class="comp-col">${inRes}</span><span class="comp-col">${outRes}</span></div>
      <div class="comp-row"><span class="comp-metric">Duration</span><span class="comp-col">${inDur}</span><span class="comp-col">${outDur}</span></div>
      <div class="comp-row"><span class="comp-metric">Video Bitrate</span><span class="comp-col">${inBitrate}</span><span class="comp-col">${outBitrate}</span></div>
      <div class="comp-row"><span class="comp-metric">Codec</span><span class="comp-col">${inCodec}</span><span class="comp-col">${outCodec}</span></div>
    `;
  }

  const extMap = {mp4:'.mp4', mov:'.mov', webm:'.webm', avi:'.avi'};
  const ext = extMap[getRadioVal('container')] || '.mp4';
  const stem = inS.filename ? inS.filename.replace(/\.[^/.]+$/, '').replace(/\s+/g, '_') : 'video';
  if (el.downloadLink) {
    el.downloadLink.textContent = 'Download';
    el.downloadLink.href = `/download/${id}`;
    el.downloadLink.setAttribute('download', stem + '_CHRONOS_' + getRadioVal('res') + ext);
    el.downloadLink.style.display = 'inline-flex';
  }
  if (outputFiles && outputFiles.length > 1) {
    if (el.segStrip) {
      el.segStrip.style.display = 'flex';
      el.segStrip.innerHTML = outputFiles.map((f, i) => {
        const name = f.replace(/\\/g, '/').split('/').pop();
        return `<div class="segment-row"><span class="seg-badge">SEG ${i+1}</span><span class="seg-name">${name}</span><a class="seg-dl" href="/download/${id}?idx=${i}">[DOWNLOAD]</a></div>`;
      }).join('');
    }
    if (el.downloadLink) el.downloadLink.style.display = 'none';
  } else { if (el.segStrip) el.segStrip.style.display = 'none'; }
  if (el.ffmpegCmd) el.ffmpegCmd.textContent = ffmpegCmd || '';
}

function finishBatch() {
  if (el.processView) el.processView.classList.remove('active');
  if (el.completeView) el.completeView.classList.add('active');
  setRing(100);
  const rows = jobQueue.map(j => {
    const inS = j.summary.size_bytes || 0, outS = j.outputSize || 0;
    let delta = '—'; if (inS && outS) { const p = ((1 - outS / inS) * 100).toFixed(1); delta = p > 0 ? `${p}% reduction` : `${Math.abs(p)}% increase`; }
    const col = j.status === 'completed' ? 'done' : 'fail';
    return `<div class="queue-item"><span class="q-name">${j.filename}</span><span class="q-status ${col}">${j.status.toUpperCase()}</span><span>${delta}</span><span>${j.status === 'completed' ? `<a href="/download/${j.jobId}" style="color:var(--accent)">[DL]</a>` : '—'}</span></div>`;
  }).join('');
  if (el.segStrip) el.segStrip.style.display = 'none';
  if (el.comparisonPanel) el.comparisonPanel.style.display = 'none';
  if (el.downloadLink) el.downloadLink.style.display = 'none';
  if (el.ffmpegCmd) el.ffmpegCmd.textContent = '';
  log('Batch complete', 'info');
}

/* ── Retry / Delete / Reset ── */
const retryBtn = $('#retry-btn');
if (retryBtn) {
retryBtn.addEventListener('click', () => {
  if (!currentJobId) return;
  if (el.completeView) el.completeView.classList.remove('active');
  if (el.processView) el.processView.classList.add('active');
  setRing(0);
  if (el.statusLabel) el.statusLabel.textContent = 'Encoding';
  if (el.pauseBtn) { el.pauseBtn.textContent = 'Pause'; el.pauseBtn.style.display = 'inline-flex'; }
  if (el.timerElapsed) el.timerElapsed.textContent = '00:00';
  log('Restarting...', 'info'); startClientTimer();
  fetch('/process', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(buildPayload()) })
    .then(r => r.json()).then(data => { if (data.error) throw new Error(data.error); startPolling(currentJobId); })
    .catch(err => { log('Restart error: ' + err.message, 'error'); handleComplete(currentJobId, null, null, null, true, []); });
});
}
const deleteBtn = $('#delete-btn');
if (deleteBtn) {
deleteBtn.addEventListener('click', () => {
  if (!currentJobId) return; const job = jobQueue.find(j => j.jobId === currentJobId); if (!job) return;
  log('Deleting...', 'info');
  fetch(`/delete/${currentJobId}`, { method: 'POST' }).then(() => {
    const idx = jobQueue.findIndex(j => j.jobId === currentJobId); if (idx !== -1) jobQueue.splice(idx, 1);
    refreshInputAnalysis(); renderQueue(); if (!jobQueue.length) resetAll();
    log('Deleted', 'info');
  }).catch(() => {});
});
}
const resetBtn = $('#reset-btn');
if (resetBtn) resetBtn.addEventListener('click', resetAll);
function resetAll() {
  currentJobId = null; currentSummary = null; currentEstimate = null; displayedJobId = null;
  jobQueue = []; batchMode = false; activeQueueIdx = -1;
  if (pollTimer) clearInterval(pollTimer); stopClientTimer();
  if (el.fileInput) el.fileInput.value = '';
  if (el.uploadView) el.uploadView.classList.add('active');
  if (el.processView) el.processView.classList.remove('active');
  if (el.completeView) el.completeView.classList.remove('active');
  if (el.metaPanel) el.metaPanel.style.display = 'none';
  if (el.noFileVisual) el.noFileVisual.style.display = 'flex';
  if (el.thumbImg) el.thumbImg.src = '';
  safeShow(el.smartBanner, false); safeShow(el.timeEstBlock, false); safeSet(el.estSizeDisplay, 'textContent', '');
  if (el.ffmpegCmd) el.ffmpegCmd.textContent = '';
  if (el.segStrip) el.segStrip.style.display = 'none';
  if (el.comparisonPanel) el.comparisonPanel.style.display = 'none';
  if (el.pauseBtn) { el.pauseBtn.textContent = 'Pause'; el.pauseBtn.style.display = 'inline-flex'; }
  if (el.processBtn) el.processBtn.disabled = true;
  if (el.smartBtn) el.smartBtn.disabled = true;
  $$('.holo-preset').forEach(b => b.classList.remove('active'));
  log('Ready', 'info');
}

if (el.copyCmdBtn) {
el.copyCmdBtn.addEventListener('click', () => {
  if (!el.ffmpegCmd || !el.ffmpegCmd.textContent) return;
  navigator.clipboard.writeText(el.ffmpegCmd.textContent).then(() => { if (el.copyCmdBtn) { el.copyCmdBtn.textContent = 'Copied'; setTimeout(() => el.copyCmdBtn.textContent = 'Copy', 1200); } });
});
}

/* ── Terminal Toggle ── */
if (el.termToggle) {
el.termToggle.addEventListener('click', () => {
  el.termToggle.classList.toggle('collapsed'); if (el.terminal) el.terminal.classList.toggle('collapsed');
});
}

/* ── Boot ── */
initPlatformToggle();
applyPlatformUI();
initHwStatus();
updateAudioUI(); updateTwoPass();
log('CHRONOS online. Awaiting stream.', 'info');
