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

  /* ---------------- 渲染 ---------------- */

  function render() {
    if (!state) return;
    renderTopbar();
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
  var lastCounterHtml = '';
  var lastLogLine = '';
  var lastHandCount = '';

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

    // 记牌器
    var counterHtml = '';
    if (state.settings.show_counter) {
      var ranks = [];
      for (var r = 3; r <= 17; r++) {
        var n = state.remaining[r];
        var label = DDZ.RANK_TEXT[r];
        if (label.length > 2) label = label.replace('王', '');
        ranks.push('<span class="' + (n === 0 ? 'counter-chip empty' : 'counter-chip') + '">' +
          '<span class="r">' + label + '</span><span class="n">' + (n === 0 ? '0' : String(n)) + '</span></span>');
      }
      counterHtml = ranks.join('');
    }
    if (counterHtml !== lastCounterHtml) { lastCounterHtml = counterHtml; $('counterRow').innerHTML = counterHtml; }

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

  var suppressClickUntil = 0;   // 框选拖动结束后的 click 抑制窗口

  function endDrag() {
    if (!dragState) return;
    var st = dragState;
    dragState = null;
    if (st.moved) {
      // 拖动结束：浏览器随后可能派发 click（松手位置在空白时），需抑制避免误出牌
      suppressClickUntil = Date.now() + 400;
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
    if (Date.now() < suppressClickUntil) return;   // 框选松手后的误触抑制
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
    $('setCounter').checked = state.settings.show_counter;
    $('setAuto').checked = state.settings.auto_pilot;
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
  $('setCounter').addEventListener('change', function () {
    postAction({ action: 'set_counter', show: this.checked });
  });
  $('setAuto').addEventListener('change', function () {
    postAction({ action: 'set_auto', on: this.checked });
  });

  /* ---------------- 启动 ---------------- */

  poll();
  setInterval(poll, 400);
})();
