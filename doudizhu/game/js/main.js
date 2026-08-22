/* 斗地主 · 主逻辑（轮询状态、渲染界面、处理交互） */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };

  var state = null;
  var selection = new Set();      // 选中的牌 id
  var handCardsSig = '';          // 手牌内容签名（内容变化才重建 DOM）
  var handSelSig = '';            // 选中签名（仅选中变化只更新 class）
  var lastShownResult = -1;       // 已展示的结算版本
  var polling = false;
  var lastPlaySigs = ['', '', ''];
  var lastSeatState = [null, null, null];
  var lastBottomSig = '';
  var lastErrorToastAt = 0;

  // 游戏声音总开关：语音播报 + 按钮音效（默认开启，localStorage 持久化）
  var voiceEnabled = true;
  var voiceReady = false;   // 首次状态同步后置 true（跳过刷新时的历史出牌播报）
  try {
    if (typeof localStorage !== 'undefined' && localStorage.getItem('ddz_voice') === '0') {
      voiceEnabled = false;
    }
  } catch (e) {}

  var NAME = ['你', '下家', '上家'];

  /* ---------------- 网络 ---------------- */

  function getState() {
    return fetch('/api/state', { cache: 'no-store' })
      .then(function (r) { return r.json(); });
  }

  function postAction(payload) {
    return fetch('/api/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then(function (r) { return r.json(); });
  }

  function poll() {
    if (polling) return;
    polling = true;
    getState().then(function (s) {
      state = s;
      render();
      voiceReady = true;
    }).catch(function () {
      var now = Date.now();
      if (now - lastErrorToastAt > 5000) {
        lastErrorToastAt = now;
        toast('与游戏服务器连接失败，请刷新页面重试', true);
      }
    }).then(function () { polling = false; });
  }

  /* ---------------- 工具 ---------------- */

  function toast(msg, isError) {
    var el = $('toast');
    el.textContent = msg;
    el.className = 'toast' + (isError ? ' error' : '');
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { el.className = 'toast hidden'; }, 2600);
  }

  // 可执行叫分/出牌/不出等操作（含叫分阶段）
  function canActHuman() {
    if (!state) return false;
    return (state.phase === 'bidding' || state.phase === 'playing') &&
      state.human_turn && !state.settings.auto_pilot;
  }

  // 可选牌（仅出牌阶段；叫分阶段不允许点选手牌）
  function canSelectCards() {
    if (!state) return false;
    return state.phase === 'playing' && state.human_turn && !state.settings.auto_pilot;
  }

  function humanWon() {
    if (!state || !state.winners) return false;
    var w = state.winners[0];
    if (state.human === state.landlord) return w === state.human;
    return w !== state.landlord;   // 农民阵营获胜
  }

  /* ---------------- 语音播报 ---------------- */

  // 牌值 → 斗地主术语念法（J=勾、Q=圈、K=凯、A=尖）
  var RANK_SPEAK = {
    3: '三', 4: '四', 5: '五', 6: '六', 7: '七', 8: '八', 9: '九', 10: '十',
    11: '勾', 12: '圈', 13: '凯', 14: '尖', 15: '二', 16: '小王', 17: '大王'
  };

  function comboSpeech(type, mainRank) {
    switch (type) {
      case 'single': return RANK_SPEAK[mainRank];
      case 'pair': return '对' + RANK_SPEAK[mainRank];
      case 'triple': return '三个' + RANK_SPEAK[mainRank];
      case 'triple_single': return '三带一';
      case 'triple_pair': return '三带二';
      case 'straight': return '顺子';
      case 'pair_chain': return '连对';
      case 'airplane': return '飞机';
      case 'airplane_single': return '飞机带翅膀';
      case 'airplane_pair': return '飞机带翅膀';
      case 'four_two_single': return '四带二';
      case 'four_two_pair': return '四带两对';
      case 'bomb': return '炸弹';
      case 'rocket': return '王炸';
      default: return '';
    }
  }

  /* 叫分事件 → 语音文本（腾讯斗地主风格） */
  function bidSpeech(ev) {
    if (!ev) return '';
    switch (ev.kind) {
      case 'bid': return ['', '一分', '两分', '三分'][ev.bid] || '叫分';
      case 'pass': return '不叫';
      case 'landlord': return '抢地主';
      case 'redeal': return '重新发牌';
      default: return '';
    }
  }

  function speak(text) {
    if (!text || !voiceEnabled) return;
    try {
      if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) return;
      window.speechSynthesis.cancel();   // 打断上一条，避免连续出牌时语音堆积
      var u = new window.SpeechSynthesisUtterance(text);
      var v = pickVoice();
      if (v) u.voice = v;
      u.lang = 'zh-CN';
      // 语气微调：炸弹/王炸沉稳有力，普通出牌稍快利落
      if (text === '炸弹' || text === '王炸') {
        u.rate = 0.92;
        u.pitch = 0.85;
      } else {
        u.rate = 1.08;
        u.pitch = 1.0;
      }
      window.speechSynthesis.speak(u);
    } catch (e) {}
  }

  /* 选择系统里最自然的中文语音（跨平台：自动探测 + 择优 + 兜底，不依赖特定系统） */
  var voicesCache = [];
  var voicesLoaded = false;

  function loadVoices() {
    try {
      if (!window.speechSynthesis) return;
      var v = window.speechSynthesis.getVoices();
      if (v && v.length) {
        voicesCache = v;
        voicesLoaded = true;
      }
    } catch (e) {}
  }

  // 识别中文语音（覆盖 zh / zh-CN / zh_CN / cmn 普通话 / yue 粤语等语言码）
  function isChineseVoice(v) {
    var l = (v && v.lang ? String(v.lang) : '').toLowerCase();
    return l.indexOf('zh') === 0 || l.indexOf('cmn') === 0 || l.indexOf('yue') === 0;
  }

  function pickVoice() {
    if (!voicesCache.length) return null;
    // 1) 名字命中常见自然中文语音（跨平台启发，含 macOS/Windows/Edge/Chrome/Android）
    var pref = ['meijia', 'ting-ting', 'tingting', 'sinji', 'yu-shu',
                'xiaoxiao', 'xiaoyi', 'yunxi', 'xiaohan',
                'google 普通话', '普通话', 'siri'];
    for (var i = 0; i < pref.length; i++) {
      for (var j = 0; j < voicesCache.length; j++) {
        var v = voicesCache[j];
        var nm = (v.name || '').toLowerCase();
        if (nm.indexOf(pref[i]) >= 0 && isChineseVoice(v)) return v;
      }
    }
    // 2) 本地中文语音优先（离线可用、更稳定）
    var zh = [];
    for (var j = 0; j < voicesCache.length; j++) {
      if (isChineseVoice(voicesCache[j])) zh.push(voicesCache[j]);
    }
    for (var j = 0; j < zh.length; j++) { if (zh[j].localService) return zh[j]; }
    // 3) 兜底：任意中文语音
    return zh[0] || null;
  }

  // 初始化 + voiceschanged 事件 + 延迟重试（不同浏览器 voices 加载时机差异很大）
  loadVoices();
  if (window.speechSynthesis) {
    window.speechSynthesis.onvoiceschanged = loadVoices;
  }
  setTimeout(loadVoices, 300);
  setTimeout(loadVoices, 1500);

  function announcePlay(lp) {
    if (!lp) return;   // 槽位清空（新一轮开始）不播报
    if (lp.passed) {
      speak('要不起');
    } else {
      speak(comboSpeech(lp.type, lp.main_rank));
    }
  }

  /* 按钮点击音效（Web Audio 合成短促清脆声，零资源文件） */
  var audioCtx = null;

  function playClickSound(freq) {
    if (!voiceEnabled) return;
    try {
      var AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      if (!audioCtx) audioCtx = new AC();
      if (audioCtx.state === 'suspended') audioCtx.resume();
      var osc = audioCtx.createOscillator();
      var gain = audioCtx.createGain();
      osc.type = 'triangle';
      osc.frequency.value = freq || 760;
      gain.gain.setValueAtTime(0.25, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.08);
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start();
      osc.stop(audioCtx.currentTime + 0.08);
    } catch (e) {}
  }

  // 事件委托：任意按钮点击都播放音效（主按钮/叫分按钮音调略高）
  document.addEventListener('click', function (e) {
    var btn = e.target && typeof e.target.closest === 'function'
      ? e.target.closest('button') : null;
    if (!btn || btn.disabled) return;
    var primary = btn.classList && typeof btn.classList.contains === 'function' &&
      (btn.classList.contains('primary') || btn.classList.contains('bid-big'));
    playClickSound(primary ? 920 : 760);
  });

  /* ---------------- 渲染 ---------------- */

  function render() {
    if (!state) return;
    renderTopbar();
    renderBidEvent();
    renderSeats();
    renderCenter();
    renderHand();
    renderControls();
    renderResult();
  }

  var lastRoundInfo = '';
  var lastMultBadge = '';
  var lastStatusHtml = '';
  var lastMultRowHtml = '';
  var lastLogLine = '';
  var lastHandCount = '';
  var lastBidEventSig = '';

  function renderBidEvent() {
    // 叫分事件变化时语音播报（叫分/不叫/抢地主/重新发牌）
    var be = state.bid_event;
    var sig = be ? (be.kind + '|' + (be.bid || 0) + '|' + be.player) : '';
    if (sig === lastBidEventSig) return;
    lastBidEventSig = sig;
    if (be && voiceReady) speak(bidSpeech(be));
  }

  function renderTopbar() {
    var ri = '第 ' + state.round_no + ' 局';
    if (ri !== lastRoundInfo) { lastRoundInfo = ri; $('roundInfo').textContent = ri; }
    var mb = '倍数 x' + state.multiplier;
    if (mb !== lastMultBadge) { lastMultBadge = mb; $('multBadge').textContent = mb; }
  }

  function renderSeats() {
    var base = ['seat seat-player', 'seat seat-right', 'seat seat-left'];
    for (var p = 0; p < 3; p++) {
      var active = (state.phase === 'bidding' || state.phase === 'playing') && state.turn === p;
      var v = state.scores[p];
      var scoreCls = 'seat-score' + (v > 0 ? ' pos' : v < 0 ? ' neg' : '');
      var roleText, roleCls;
      if (state.landlord === p) {
        roleText = '地主'; roleCls = 'role-badge landlord';
      } else if (state.phase === 'playing' || state.phase === 'round_over') {
        roleText = '农民'; roleCls = 'role-badge';
      } else {
        roleText = ''; roleCls = 'role-badge';
      }
      var leftText, leftCls;
      if (p === 0) {
        leftText = ''; leftCls = 'cards-left hidden';
      } else {
        var n = state.hand_counts[p];
        leftText = String(n);
        leftCls = 'cards-left' + (n === 1 && state.phase === 'playing' ? ' one' : '');
      }

      // 座位状态签名：完全相同则跳过，避免每 400ms 重复写 DOM（样式重算）
      var seatSig = [active ? 1 : 0, v, scoreCls, roleText, roleCls, leftText, leftCls].join('|');
      if (seatSig !== lastSeatState[p]) {
        lastSeatState[p] = seatSig;
        $('seat' + p).className = base[p] + (active ? ' active' : '');
        $('arrow' + p).className = 'turn-arrow arrow-' +
          (p === 2 ? 'ul' : p === 1 ? 'ur' : 'dn') + (active ? ' on' : '');
        var sc = $('score' + p);
        sc.textContent = (v > 0 ? '+' : '') + v;
        sc.className = scoreCls;
        var role = $('role' + p);
        role.textContent = roleText;
        role.className = roleCls;
        var left = $('left' + p);
        left.textContent = leftText;
        left.className = leftCls;
        // 头像：地主显示地主形象，其余显示农民形象
        $('avatar' + p).innerHTML = (state.landlord === p)
          ? DDZ.landlordAvatar() : DDZ.farmerAvatar();
      }

      // 最近出牌（中央对战区槽位）
      var lp = state.last_plays[p];
      var sig = lp ? (lp.passed ? 'P' : lp.cards.join(',')) : '';
      if (sig !== lastPlaySigs[p]) {
        lastPlaySigs[p] = sig;
        var el = $('lastPlay' + p);
        if (!lp) {
          el.innerHTML = '';
        } else if (lp.passed) {
          el.innerHTML = '<span class="pass-chip">不出</span>';
        } else {
          el.innerHTML = lp.cards.map(function (c) {
            return '<span class="mini anim">' + DDZ.cardSVG(c) + '</span>';
          }).join('');
        }
        // 语音播报：任何一方出牌/不出都播报（跳过首次渲染）
        if (voiceReady) announcePlay(lp);
      }
    }
    var hc = state.hand_counts[0] + ' 张';
    if (hc !== lastHandCount) { lastHandCount = hc; $('handCount').textContent = hc; }
  }

  function renderCenter() {
    var st = $('status');
    var statusHtml;
    if (state.phase === 'bidding') {
      if (state.human_turn) {
        statusHtml = '请叫地主' + (state.bid_highest > 0
          ? ' · <span class="beat">当前最高 ' + state.bid_highest + ' 分</span>' : '');
      } else {
        statusHtml = '等待 <span class="turn-name">' + NAME[state.turn] + '</span> 叫分…';
      }
    } else if (state.phase === 'playing') {
      if (state.human_turn) {
        if (state.must_beat) {
          statusHtml = '轮到你出牌 · 需压过 <span class="beat">' + state.must_beat.label + '</span>';
        } else {
          statusHtml = '轮到你出牌（先手）';
        }
      } else {
        statusHtml = '等待 <span class="turn-name">' + NAME[state.turn] + '</span> 出牌…';
      }
    } else {
      statusHtml = '本局结束 · ' + (state.round_result || '');
    }
    if (statusHtml !== lastStatusHtml) {
      lastStatusHtml = statusHtml;
      st.innerHTML = statusHtml;
    }

    // 底牌（地主确定后翻开）
    var bSig = (state.bottom_visible ? 'V' : 'H') + state.bottom.map(function (c) { return c.id; }).join(',');
    if (bSig !== lastBottomSig) {
      lastBottomSig = bSig;
      $('bottomCards').innerHTML = state.bottom.map(function (c) {
        return '<span class="mini anim">' + DDZ.cardSVG(c.id, !state.bottom_visible) + '</span>';
      }).join('');
    }

    // 倍数构成
    var chips = ['<span class="chip mult">倍数 x' + state.multiplier + '</span>'];
    if (state.bombs_used > 0) chips.push('<span class="chip">炸弹 x' + state.bombs_used + '</span>');
    if (state.rockets_used > 0) chips.push('<span class="chip">王炸 x' + state.rockets_used + '</span>');
    var multHtml = chips.join('');
    if (multHtml !== lastMultRowHtml) { lastMultRowHtml = multHtml; $('multRow').innerHTML = multHtml; }

    // 日志
    var lg = state.log.length ? state.log[state.log.length - 1] : '';
    if (lg !== lastLogLine) { lastLogLine = lg; $('logLine').textContent = lg; }
  }

  function renderHand() {
    var cards = state.hands['0'] || [];
    var csig = cards.map(function (c) { return c.id; }).join(',');
    var ssig = Array.from(selection).sort(function (a, b) { return a - b; }).join(',');

    if (csig !== handCardsSig) {
      // 手牌内容变化 → 全量重建（出牌/发牌等）
      handCardsSig = csig;
      var ids = new Set(cards.map(function (c) { return c.id; }));
      var needsPrune = Array.from(selection).some(function (id) { return !ids.has(id); });
      if (needsPrune) {
        selection = new Set(Array.from(selection).filter(function (id) { return ids.has(id); }));
        ssig = Array.from(selection).sort(function (a, b) { return a - b; }).join(',');
      }
      cardOrder = cards.map(function (c) { return c.id; });
      // 每张牌显式递增 z-index：锁定"右压左"的正常重叠，
      // 避免选中/悬停的 transform 创建 stacking context 后盖住旁边的牌
      $('hand').innerHTML = cards.map(function (c, i) {
        var sel = selection.has(c.id) ? ' selected' : '';
        return '<div class="card' + sel + '" data-id="' + c.id +
          '" data-idx="' + i + '" style="z-index:' + (i + 1) + '">' + DDZ.cardSVG(c.id) + '</div>';
      }).join('');
      handSelSig = ssig;
    } else if (ssig !== handSelSig) {
      // 仅选中变化 → 只更新 class（不重建整手牌，点选/框选更流畅）
      handSelSig = ssig;
      var nodes = $('hand').querySelectorAll('.card');
      for (var i = 0; i < nodes.length; i++) {
        var nid = Number(nodes[i].getAttribute('data-id'));
        nodes[i].classList.toggle('selected', selection.has(nid));
      }
    }
  }

  var lastBidPanelHidden = null;
  var lastBidDisabled = [-1, -1, -1, -1];
  var lastPassDisabled = null;
  var lastPlayDisabled = null;
  var lastHintDisabled = null;
  var lastHintText = null;

  function renderControls() {
    var auto = state.settings.auto_pilot;
    var hint = $('ctrlHint');

    if (state.phase === 'bidding') {
      if (lastBidPanelHidden !== false) {
        lastBidPanelHidden = false;
        $('bidPanel').classList.remove('hidden');
      }
      showEls(['btnPass', 'btnPlay', 'btnHint'], false);
      var can = canActHuman();
      for (var v = 0; v <= 3; v++) {
        var dis = !can || (v !== 0 && v <= state.bid_highest);
        if (dis !== lastBidDisabled[v]) {
          lastBidDisabled[v] = dis;
          $('btnBid' + v).disabled = dis;
        }
      }
      var hb = auto ? '托管中…' : '';
      if (hb !== lastHintText) { lastHintText = hb; hint.textContent = hb; }
    } else if (state.phase === 'playing') {
      if (lastBidPanelHidden !== true) {
        lastBidPanelHidden = true;
        $('bidPanel').classList.add('hidden');
      }
      showEls(['btnPass', 'btnPlay', 'btnHint'], true);
      var canP = canActHuman();
      var passDis = !canP || !state.can_pass;
      var playDis = !canP || selection.size === 0;
      var hintDis = !canP;
      if (passDis !== lastPassDisabled) { lastPassDisabled = passDis; $('btnPass').disabled = passDis; }
      if (playDis !== lastPlayDisabled) { lastPlayDisabled = playDis; $('btnPlay').disabled = playDis; }
      if (hintDis !== lastHintDisabled) { lastHintDisabled = hintDis; $('btnHint').disabled = hintDis; }
      var hp = auto ? '托管中…' : '';
      if (hp !== lastHintText) { lastHintText = hp; hint.textContent = hp; }
    } else {
      if (lastBidPanelHidden !== true) {
        lastBidPanelHidden = true;
        $('bidPanel').classList.add('hidden');
      }
      showEls(['btnPass', 'btnPlay', 'btnHint'], false);
      var he = '本局已结束，点「再来一局」或右上角「新一局」继续';
      if (he !== lastHintText) { lastHintText = he; hint.textContent = he; }
    }
  }

  function showEls(ids, show) {
    ids.forEach(function (id) { $(id).classList.toggle('hidden', !show); });
  }

  function renderResult() {
    if (state.phase !== 'round_over' || !state.winners) {
      if (!document.getElementById('resultModal').classList.contains('hidden')) {
        document.getElementById('resultModal').classList.add('hidden');
      }
      return;
    }
    if (state.version === lastShownResult) return;
    lastShownResult = state.version;

    var win = humanWon();
    $('resultTitle').textContent = win ? '🎉 你赢了！' : '😢 你输了';
    var rs = state.round_scores[0];
    var parts = [];
    parts.push('本局得分：<span class="' + (rs >= 0 ? 'big win' : 'big lose') + '">' +
      (rs >= 0 ? '+' : '') + rs + '</span>');
    var notes = ['叫分 ' + state.bid + ' 分', '倍数 x' + state.multiplier];
    if (state.bombs_used) notes.push('炸弹 x' + state.bombs_used);
    if (state.rockets_used) notes.push('王炸 x' + state.rockets_used);
    if (state.spring) notes.push('春天翻倍');
    if (state.anti_spring) notes.push('反春翻倍');
    parts.push(notes.join(' · '));
    parts.push('累计比分：你 ' + state.scores[0] + '　上家 ' + state.scores[2] + '　下家 ' + state.scores[1]);
    $('resultBody').innerHTML = parts.map(function (p) { return '<div>' + p + '</div>'; }).join('');
    $('resultModal').classList.remove('hidden');
  }

  /* ---------------- 交互 ---------------- */

  function toggleSelect(id) {
    if (selection.has(id)) {
      selection.delete(id);
    } else {
      selection.add(id);
    }
    renderHand();
    renderControls();
  }

  /* ---------- 手牌选择：单击切换 + 按住左右拖动框选连续选中 ---------- */
  var cardOrder = [];           // 当前手牌顺序（与 DOM 一致）
  var dragState = null;         // {anchor, current, moved, wasSelected, id}

  function cardIndexById(id) {
    return cardOrder.indexOf(id);
  }

  function applyRangeSelection(anchorIdx, curIdx) {
    // 累加模式：把拖过的区间并入现有选中（支持多次乱序选牌）
    var lo = Math.min(anchorIdx, curIdx);
    var hi = Math.max(anchorIdx, curIdx);
    for (var i = lo; i <= hi; i++) selection.add(cardOrder[i]);
    renderHand();
    renderControls();
  }

  $('hand').addEventListener('pointerdown', function (e) {
    if (!canSelectCards()) return;   // 仅出牌阶段可选牌
    var node = e.target && typeof e.target.closest === 'function'
      ? e.target.closest('.card') : null;
    if (!node) return;
    var id = Number(node.getAttribute('data-id'));
    var idx = cardIndexById(id);
    if (idx < 0) return;
    dragState = { anchor: idx, current: idx, moved: false, wasSelected: selection.has(id), id: id };
    // 按住牌时切换为"抓手"光标
    try { if (document.body) document.body.style.cursor = 'grabbing'; } catch (e) {}
    if (e.cancelable) e.preventDefault();
  });

  document.addEventListener('pointermove', function (e) {
    if (!dragState) return;
    var el = typeof document.elementFromPoint === 'function'
      ? document.elementFromPoint(e.clientX, e.clientY) : null;
    var node = el && typeof el.closest === 'function' ? el.closest('.card') : null;
    if (!node) return;
    var idx = cardIndexById(Number(node.getAttribute('data-id')));
    if (idx < 0 || idx === dragState.current) return;
    dragState.current = idx;
    dragState.moved = true;
    applyRangeSelection(dragState.anchor, idx);
  });

  var lastDragEndAt = -1e9;   // 最近一次框选结束时间：只抑制"同一手势紧随派发的 click"

  function endDrag() {
    if (!dragState) return;
    var st = dragState;
    dragState = null;
    try { if (document.body) document.body.style.cursor = ''; } catch (e) {}
    if (st.moved) {
      // 框选松手后，浏览器会在极短时间内（<10ms，同一手势）同步派发一个 click；
      // 记录时间戳，仅抑制这个紧随的 click，避免拖到牌缝误出牌。
      lastDragEndAt = Date.now();
    } else {
      // 单击：切换该牌的选中状态
      toggleSelect(st.id);
    }
  }
  document.addEventListener('pointerup', endDrag);
  document.addEventListener('pointercancel', endDrag);

  var lastBlankClickPlay = 0;   // 最近一次"空白单击出牌"时间（用于抑制双击误触不出）

  function isBlankArea(t) {
    return !(t && typeof t.closest === 'function' &&
             (t.closest('.card') || t.closest('button')));
  }

  $('app').addEventListener('click', function (e) {
    // 仅抑制框选松手同一手势紧随派发的 click（60ms 内）；
    // 用户随后主动点击空白（移动+按下 > 60ms）立即出牌，无需点两次。
    if (Date.now() - lastDragEndAt < 60) return;
    if (!isBlankArea(e.target)) return;
    if (!canActHuman() || selection.size === 0) return;
    lastBlankClickPlay = Date.now();
    playSelectedCards();
  });

  $('app').addEventListener('dblclick', function (e) {
    if (!isBlankArea(e.target)) return;      // 牌上/按钮上不触发
    if (Date.now() - lastBlankClickPlay < 600) return;  // 刚用空白单击出过牌
    if (!canActHuman()) return;
    if (!state.can_pass) { toast('现在不能不出（必须出牌）'); return; }
    postAction({ action: 'pass' }).then(function (res) {
      if (res.state) { state = res.state; render(); }
    });
  });

  function playSelectedCards() {
    if (selection.size === 0) return;
    var cards = Array.from(selection);   // Set → 数组（slice.call 对 Set 无效，会得到空数组）
    selection = new Set();               // 乐观清空，立即反馈
    renderHand();
    renderControls();
    postAction({ action: 'play', cards: cards }).then(function (res) {
      if (!res.ok && res.error) toast(res.error, true);
      if (res.state) { state = res.state; render(); }
    });
  }

  $('btnPlay').addEventListener('click', function () {
    if (selection.size === 0) { toast('请先选牌'); return; }
    playSelectedCards();
  });

  $('btnPass').addEventListener('click', function () {
    postAction({ action: 'pass' }).then(function (res) {
      if (res.state) { state = res.state; render(); }
    });
  });

  $('btnHint').addEventListener('click', function () {
    postAction({ action: 'hint' }).then(function (res) {
      if (res.hint) {
        if (res.hint.kind === 'bid') {
          if (res.hint.value > 0 && res.hint.value > state.bid_highest) {
            toast('建议叫 ' + res.hint.value + ' 分');
          } else {
            toast('建议不叫');
          }
        } else if (res.hint.kind === 'play') {
          if (res.hint.pass) {
            toast('建议不出');
          } else {
            selection = new Set(res.hint.cards);
            renderHand();
            renderControls();
            toast('已为你选好：' + res.hint.cards.length + ' 张，点「出牌」打出');
          }
        }
      }
      if (res.state) { state = res.state; render(); }
    });
  });

  for (var v = 0; v <= 3; v++) {
    (function (val) {
      $('btnBid' + v).addEventListener('click', function () {
        postAction({ action: 'bid', bid: val }).then(function (res) {
          if (res.state) { state = res.state; render(); }
        });
      });
    })(v);
  }

  function newRound() {
    postAction({ action: 'new_round' }).then(function (res) {
      selection = new Set();
      lastPlaySigs = ['', '', ''];
      lastBottomSig = '';
      handCardsSig = '';
      handSelSig = '';
      if (res.state) { state = res.state; render(); }
    });
  }

  $('btnNewRound').addEventListener('click', function () {
    if (state && state.phase !== 'round_over' &&
        !window.confirm('确定要重新开始一局吗？当前对局将作废。')) {
      return;
    }
    newRound();
  });
  $('btnAgain').addEventListener('click', function () {
    $('resultModal').classList.add('hidden');
    newRound();
  });
  $('btnCloseResult').addEventListener('click', function () {
    $('resultModal').classList.add('hidden');
  });

  /* ---------------- 设置 ---------------- */

  $('btnSettings').addEventListener('click', function () {
    $('setSpeed').value = state.settings.bot_delay_ms;
    $('speedVal').textContent = (state.settings.bot_delay_ms / 1000).toFixed(1) + ' 秒';
    $('setAuto').checked = state.settings.auto_pilot;
    $('setVoice').checked = voiceEnabled;
    $('settingsModal').classList.remove('hidden');
  });
  $('btnCloseSettings').addEventListener('click', function () {
    $('settingsModal').classList.add('hidden');
  });

  var delayTimer = null;
  $('setSpeed').addEventListener('input', function () {
    $('speedVal').textContent = (Number(this.value) / 1000).toFixed(1) + ' 秒';
    clearTimeout(delayTimer);
    var ms = Number(this.value);
    delayTimer = setTimeout(function () {
      postAction({ action: 'set_delay', ms: ms });
    }, 300);
  });
  $('setAuto').addEventListener('change', function () {
    postAction({ action: 'set_auto', on: this.checked });
  });
  $('setVoice').addEventListener('change', function () {
    voiceEnabled = this.checked;
    try {
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem('ddz_voice', this.checked ? '1' : '0');
      }
    } catch (e) {}
  });

  /* ---------------- 启动 ---------------- */

  poll();
  setInterval(poll, 400);
})();
