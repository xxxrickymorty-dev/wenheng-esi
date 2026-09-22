/* ==================================================================
   声音层（取书 / 翻页 / 开卷 / 合上 + 背景乐）
   ------------------------------------------------------------------
   来源：G-复刻WorkingVolumes 的 SFX 模块（本项目自己的实现）+ rick 提供的三段真录音。
   三段原始素材都**不能直接用**，处理记录见
   《G-复刻WorkingVolumes/README.md》第九节与《音效合成配方》：
     · 背景音乐.mp3  其实是 MP4 容器（h264+aac）——剥掉视频流、+15dB 提响度
     · 翻书声.m4a    31.8 秒连续录音——检出 7 次翻页、取 4 段完整的
     · 书架取书.wav  一次完整事件——峰值对齐 + 首尾淡入淡出
   三条响度统一到峰值 −3.5dB，否则随机播放会忽大忽小。

   合规四条（缺一条就是「开关开着但一点声音都没有」）：
     默认关闭 · 需一次用户手势 · 页面隐藏即挂起 · 偏好可记住但**不自动开**。

   兜底三层：真实素材 → 解码失败回落合成 → BGM 缺失回落合成环境乐。
   三层听感都是「有声音」，所以必须暴露 info() 说明到底走的哪条。
   ================================================================== */
window.WH_AUDIO = (function () {
'use strict';

var BGM_SRC = 'audio/bgm.mp3';
var SFX_DATA = window.WH_SFX_DATA || {};
var PREF = 'wh_sound_on';

var ctx = null, master = null, sfxBus = null, musBus = null, noiseBuf = null;
var on = false, noteTimer = null, drones = [];
var samples = { page: [], pull: null };
var bgmEl = null, bgmFade = null, bgmFailed = false;

/* 五声音阶（羽调式）：不确立大小调，中立、不抢戏 */
var SCALE = [220.00, 261.63, 293.66, 349.23, 392.00, 440.00, 523.25];
var noteIdx = 0;

/* ---------- 小工具 ---------- */
function b64ToBuf(b64) {
  var bin = atob(b64), arr = new Uint8Array(bin.length);
  for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return arr.buffer;
}

function decodeAll() {
  var names = Object.keys(SFX_DATA);
  if (!names.length) return;
  names.forEach(function (k) {
    try {
      ctx.decodeAudioData(b64ToBuf(SFX_DATA[k]), function (dec) {
        if (k === 'pull') samples.pull = dec; else samples.page.push(dec);
      }, function () { console.warn('[声] 解码失败：', k); });
    } catch (e) { console.warn('[声] 解码异常：', k, e); }
  });
}

function playBuf(b, vol) {
  var src = ctx.createBufferSource();
  src.buffer = b;
  var g = ctx.createGain();
  g.gain.value = vol;
  src.connect(g); g.connect(sfxBus);
  src.start(0);
}

function ensure() {
  if (ctx) return true;
  try {
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return false;
    ctx = new AC();
    master = ctx.createGain(); master.gain.value = .85; master.connect(ctx.destination);
    sfxBus = ctx.createGain(); sfxBus.gain.value = .9; sfxBus.connect(master);
    musBus = ctx.createGain(); musBus.gain.value = 0; musBus.connect(master);
    decodeAll();
    return true;
  } catch (e) {
    console.warn('[声] Web Audio 不可用，本次静音运行', e);
    ctx = null; return false;
  }
}

function noise() {
  if (!noiseBuf) {
    var n = Math.floor(ctx.sampleRate * 2);
    noiseBuf = ctx.createBuffer(1, n, ctx.sampleRate);
    var d = noiseBuf.getChannelData(0);
    for (var i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
  }
  return noiseBuf;
}

/* 一段带通噪声：f0→f1 扫频，快起音 + 指数衰减 */
function burst(t0, dur, f0, f1, peak, q, hp) {
  var src = ctx.createBufferSource();
  src.buffer = noise();
  src.playbackRate.value = .9 + Math.random() * .3;
  var bp = ctx.createBiquadFilter();
  bp.type = 'bandpass'; bp.Q.value = q;
  bp.frequency.setValueAtTime(f0, t0);
  bp.frequency.exponentialRampToValueAtTime(f1, t0 + dur);
  var hpf = ctx.createBiquadFilter();
  hpf.type = 'highpass'; hpf.frequency.value = hp;
  var g = ctx.createGain();
  g.gain.setValueAtTime(0, t0);
  g.gain.linearRampToValueAtTime(peak, t0 + Math.min(.012, dur * .12));
  g.gain.exponentialRampToValueAtTime(.0006, t0 + dur);
  src.connect(hpf); hpf.connect(bp); bp.connect(g); g.connect(sfxBus);
  src.start(t0); src.stop(t0 + dur + .05);
}

/* 颗粒：极短的噪声脉冲。
   纸张声的本质是**颗粒**，不是持续噪声——纤维与皱褶逐次释放，
   每次都是一记 5–20ms 的微冲击。少了颗粒就是「风」或「布」，不像纸。 */
function grain(t0, dur, f, amp, q) {
  var src = ctx.createBufferSource();
  src.buffer = noise();
  var bp = ctx.createBiquadFilter();
  bp.type = 'bandpass'; bp.frequency.value = f; bp.Q.value = q || 1.1;
  var hp = ctx.createBiquadFilter();
  hp.type = 'highpass'; hp.frequency.value = 1500;
  var g = ctx.createGain();
  g.gain.setValueAtTime(0, t0);
  g.gain.linearRampToValueAtTime(amp, t0 + .0012);
  g.gain.exponentialRampToValueAtTime(.0004, t0 + dur);
  src.connect(hp); hp.connect(bp); bp.connect(g); g.connect(sfxBus);
  src.start(t0); src.stop(t0 + dur + .012);
}

/* 低频闷响：书本离开/碰到支撑的那一记 */
function thump(t0, f, amp, dur) {
  var o = ctx.createOscillator(), g = ctx.createGain();
  o.type = 'sine';
  o.frequency.setValueAtTime(f, t0);
  o.frequency.exponentialRampToValueAtTime(f * .55, t0 + dur);
  g.gain.setValueAtTime(0, t0);
  g.gain.linearRampToValueAtTime(amp, t0 + .008);
  g.gain.exponentialRampToValueAtTime(.0005, t0 + dur);
  o.connect(g); g.connect(sfxBus); o.start(t0); o.stop(t0 + dur + .05);
}

/* ---------- 四个动作 ---------- */
function pageTurn() {
  if (!ensure() || !on) return;
  if (samples.page.length) {                       /* 4 段随机取一，每次都不完全一样 */
    playBuf(samples.page[Math.floor(Math.random() * samples.page.length)], .95);
    return;
  }
  var t0 = ctx.currentTime + .01, N = 46;
  for (var i = 0; i < N; i++) {
    var u = i / N;
    grain(t0 + Math.pow(u, .72) * .27 + Math.random() * .013,
          .005 + Math.random() * .017,
          2400 + Math.random() * 6300,
          (.045 + Math.random() * .085) * (1 - u * .42));
  }
  thump(t0 + .20, 190, .05, .09);
}

function pullBook() {
  if (!ensure() || !on) return;
  if (samples.pull) { playBuf(samples.pull, .9); return; }
  var t = ctx.currentTime + .01;
  burst(t, .34, 620, 2200, .13, .68, 300);
  thump(t + .03, 116, .17, .24);                   /* 少了这记，「搬书」会显得单薄 */
  for (var i = 0; i < 14; i++) {
    grain(t + .05 + Math.random() * .30, .005 + Math.random() * .012,
          3000 + Math.random() * 4500, .018 + Math.random() * .030);
  }
}

function closeBook() {
  if (!ensure() || !on) return;
  var t = ctx.currentTime + .01;
  thump(t, 150, .24, .26);
  burst(t + .015, .16, 900, 2600, .12, .7, 380);
  for (var i = 0; i < 20; i++) {
    grain(t + .01 + Math.random() * .16, .005 + Math.random() * .014,
          2600 + Math.random() * 5000, .020 + Math.random() * .045);
  }
}

function openBook() {
  if (!ensure() || !on) return;
  var t = ctx.currentTime + .01;
  burst(t, .30, 600, 1900, .14, .62, 300);
  thump(t + .06, 132, .11, .18);
  for (var i = 0; i < 22; i++) {
    grain(t + .04 + Math.random() * .34, .005 + Math.random() * .015,
          2600 + Math.random() * 5200, .020 + Math.random() * .045);
  }
}

/* ---------- 背景乐：真素材优先，缺失则合成兜底 ---------- */
function fadeBgm(target, ms) {
  if (!bgmEl) return;
  if (bgmFade) clearInterval(bgmFade);
  var v0 = bgmEl.volume, t0 = Date.now();
  bgmFade = setInterval(function () {
    if (!bgmEl) { clearInterval(bgmFade); bgmFade = null; return; }
    var k = Math.min(1, (Date.now() - t0) / ms);
    bgmEl.volume = v0 + (target - v0) * k;
    if (k >= 1) { clearInterval(bgmFade); bgmFade = null; }
  }, 60);
}

/* BGM 走 <audio> 而不是 Web Audio：933KB 不适合内嵌，
   而 file:// 下 fetch 会被拦、媒体元素加载同目录文件不受此限——页面仍能双击即开。 */
function startMusic() {
  if (!ensure()) return;
  if (!bgmEl && !bgmFailed) {
    try {
      bgmEl = new Audio();
      bgmEl.loop = true;
      bgmEl.preload = 'auto';
      bgmEl.volume = 0;
      bgmEl.src = BGM_SRC;
    } catch (e) { bgmFailed = true; bgmEl = null; }
  }
  if (bgmEl) {
    var p = bgmEl.play();
    if (p && p.catch) p.catch(function () { bgmFailed = true; startSynthMusic(); });
    fadeBgm(.38, 1400);
    bgmEl.onerror = function () { bgmFailed = true; bgmEl = null; startSynthMusic(); };
    return;
  }
  startSynthMusic();
}

/* 合成环境乐：两个纯五度垫底 + 极慢呼吸 + 稀疏单音（平均 7 秒一音，不走顺阶） */
function startSynthMusic() {
  if (!ctx) return;
  if (drones.length) return;
  var t = ctx.currentTime + .05;
  [[110.00, .085], [164.81, .058]].forEach(function (d, i) {
    var o = ctx.createOscillator(), g = ctx.createGain();
    o.type = 'sine'; o.frequency.value = d[0];
    g.gain.value = d[1];
    var lfo = ctx.createOscillator(), lg = ctx.createGain();
    lfo.frequency.value = .045 + i * .019;
    lg.gain.value = d[1] * .45;
    lfo.connect(lg); lg.connect(g.gain);
    o.connect(g); g.connect(musBus);
    o.start(t); lfo.start(t);
    drones.push(o); drones.push(lfo);
  });
  musBus.gain.cancelScheduledValues(t);
  musBus.gain.setValueAtTime(0, t);
  musBus.gain.linearRampToValueAtTime(.85, t + 1.2);
  scheduleNote();
}

function scheduleNote() {
  if (noteTimer) clearTimeout(noteTimer);
  noteTimer = setTimeout(function () {
    if (!on || document.hidden) { scheduleNote(); return; }
    if (ctx && ctx.state === 'running' && !bgmEl) {
      var t = ctx.currentTime + .02;
      var f = SCALE[noteIdx % SCALE.length];
      noteIdx += 1 + Math.floor(Math.random() * 2);   /* 不走顺阶，避免听出旋律 */
      var o = ctx.createOscillator(), g = ctx.createGain();
      o.type = 'triangle'; o.frequency.value = f * 2;
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(.075, t + .04);
      g.gain.exponentialRampToValueAtTime(.0004, t + 2.6);
      o.connect(g); g.connect(musBus); o.start(t); o.stop(t + 2.8);
    }
    scheduleNote();
  }, 4200 + Math.random() * 5200);
}

function stopMusic() {
  if (bgmEl) {
    fadeBgm(0, 800);
    var el = bgmEl;
    setTimeout(function () { if (el && el.volume < .02) el.pause(); }, 900);
  }
  if (ctx) {
    var t = ctx.currentTime;
    musBus.gain.cancelScheduledValues(t);
    musBus.gain.setValueAtTime(musBus.gain.value, t);
    musBus.gain.linearRampToValueAtTime(0, t + .8);
  }
  if (noteTimer) { clearTimeout(noteTimer); noteTimer = null; }
}

/* ---------- 开关 ---------- */
function set(v) {
  on = !!v;
  try { localStorage.setItem(PREF, on ? '1' : '0'); } catch (e) {}
  if (on) {
    startMusic();
    if (ctx) grain(ctx.currentTime + .01, .028, 4200, .06);   /* 开启确认音，定调 */
  } else stopMusic();
  try { window.dispatchEvent(new CustomEvent('wh:audio', { detail: on })); } catch (e) {}
  return on;
}

/* 页面隐藏即挂起（BGM 是 <audio>，不归 AudioContext 管，要单独停） */
document.addEventListener('visibilitychange', function () {
  if (document.hidden) {
    if (ctx && ctx.state === 'running') ctx.suspend();
    if (bgmEl && !bgmEl.paused) bgmEl.pause();
  } else if (on) {
    if (ctx && ctx.state === 'suspended') ctx.resume();
    if (bgmEl && bgmEl.paused) { var p = bgmEl.play(); if (p && p.catch) p.catch(function () {}); }
  }
});

/* 首次手势自动开声：浏览器规定「要一次用户手势才能响」，
   但手势之后就没理由再让听不见——rick 要听得见声音。
   明确关过（localStorage='0'）就不再自作主张。 */
var gestured = false;
function firstGesture() {
  if (gestured) return;
  gestured = true;
  var remembered = null;
  try { remembered = localStorage.getItem(PREF); } catch (e) {}
  if (remembered === '0') return;          /* 用户明确关过，尊重 */
  if (!on) set(true);
}
window.addEventListener('pointerdown', firstGesture, { once: false });
window.addEventListener('keydown', firstGesture, { once: false });

return {
  set: set,
  toggle: function () { return set(!on); },
  on: function () { return on; },
  supported: function () { return !!(window.AudioContext || window.webkitAudioContext); },
  /* 记住偏好，但**不自动开**——没手势会被浏览器拦，演示现场也多半不希望它自己响 */
  preferOn: function () { try { return localStorage.getItem(PREF) === '1'; } catch (e) { return false; } },
  /* 供自测：ctx 为 null = 根本没建起来，「开着但没声」就是这么发生的 */
  state: function () { return ctx ? ctx.state : 'none'; },
  /* 素材到底用上没有：解码成功才说明真音频在工作，否则跑的是合成兜底 */
  info: function () {
    return {
      pageDecoded: samples.page.length,
      pullDecoded: !!samples.pull,
      bgmFailed: bgmFailed,
      bgm: bgmEl ? { paused: bgmEl.paused, vol: +bgmEl.volume.toFixed(3) } : null
    };
  },
  page: pageTurn, pull: pullBook, open: openBook, close: closeBook
};
})();
