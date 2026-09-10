// 斗地主前端 JS 冒烟测试（JXA / JavaScriptCore 运行）
// 用法: osascript -l JavaScript tests/js_smoke.js
ObjC.import("Foundation");

function readFile(path) {
  var err = Ref();
  var s = $.NSString.stringWithContentsOfFileEncodingError(path, $.NSUTF8StringEncoding, err);
  if (s.isNil()) throw new Error("read fail: " + path);
  return s.js;
}

function readJson(path) {
  return JSON.parse(readFile(path));
}

// ---------- 提取 index.html 中全部 id ----------
var html = readFile("doudizhu/game/index.html");
var idRe = /id="([^"]+)"/g;
var m, ids = [];
while ((m = idRe.exec(html)) !== null) ids.push(m[1]);

// ---------- DOM 元素模拟 ----------
function makeEl(id) {
  var el = {
    id: id,
    _text: "",
    value: "",
    checked: false,
    style: {},
    _cls: {},
    _ls: {},
    _attrs: {},
    getAttribute: function (name) { return this._attrs[name] || null; },
    setAttribute: function (name, value) { this._attrs[name] = value; },
    focus: function () { document.activeElement = this; },
    querySelectorAll: function () { return []; },
    addEventListener: function (type, fn) {
      (this._ls[type] = this._ls[type] || []).push(fn);
    },
    fire: function (type, evt) {
      var e = evt || {};
      if (typeof e.preventDefault !== "function") e.preventDefault = function () {};
      var ls = this._ls[type] || [];
      for (var i = 0; i < ls.length; i++) ls[i].call(this, e);
    }
  };
  // innerHTML 与 textContent 共享同一存储（与真实 DOM 语义一致）
  // 并统计 innerHTML 重建次数（用于验证渲染早退优化）
  el._setCount = 0;
  Object.defineProperty(el, "innerHTML", {
    get: function () { return el._text; },
    set: function (v) { el._text = String(v); el._setCount++; }
  });
  Object.defineProperty(el, "textContent", {
    get: function () { return el._text; },
    set: function (v) { el._text = String(v); }
  });
  el.className = "";
  el.classList = {
    toggle: function (c, force) {
      var on = force === undefined ? !el._cls[c] : !!force;
      if (on) el._cls[c] = true; else delete el._cls[c];
    },
    add: function (c) { el._cls[c] = true; },
    remove: function (c) { delete el._cls[c]; },
    contains: function (c) { return !!el._cls[c]; }
  };
  return el;
}

var els = {};
for (var i = 0; i < ids.length; i++) els[ids[i]] = makeEl(ids[i]);

var docListeners = {};
var document = {
  hidden: false,
  activeElement: null,
  getElementById: function (id) {
    if (!els[id]) throw new Error("getElementById 引用了不存在的 id: " + id);
    return els[id];
  },
  addEventListener: function (type, fn) {
    (docListeners[type] = docListeners[type] || []).push(fn);
  },
  fire: function (type, evt) {
    var e = evt || {};
    if (typeof e.preventDefault !== "function") e.preventDefault = function () {};
    var ls = docListeners[type] || [];
    for (var i = 0; i < ls.length; i++) ls[i](e);
  },
  elementFromPoint: function () { return null; }
};

// ---------- 全局环境 ----------
var window = {
  confirm: function () { return true; },
  speechSynthesis: {
    _last: null,
    _voice: null,
    cancel: function () {},
    speak: function (u) { this._last = u.text; this._voice = u.voice ? u.voice.name : null; },
    getVoices: function () {
      return [
        { name: 'Ting-Ting', lang: 'zh-CN', localService: true },
        { name: 'Meijia', lang: 'zh-CN', localService: true },
        { name: 'Daniel', lang: 'en-GB', localService: true }
      ];
    }
  },
  SpeechSynthesisUtterance: function (t) {
    this.text = t; this.lang = ''; this.rate = 1; this.pitch = 1;
  },
  __oscCount: 0,
  AudioContext: function () {
    return {
      state: 'running', currentTime: 0, destination: {},
      resume: function () {},
      createOscillator: function () {
        window.__oscCount++;
        return { type: '', frequency: { value: 0 }, connect: function () {}, start: function () {}, stop: function () {} };
      },
      createGain: function () {
        return { gain: { setValueAtTime: function () {}, exponentialRampToValueAtTime: function () {} }, connect: function () {} };
      }
    };
  }
};
var DDZ = null; // 浏览器中 window.DDZ 即全局 DDZ，这里手动桥接
var _pollFn = null;
setTimeout = function (fn) { if (fn && fn.name === 'poll') _pollFn = fn; return 0; };
clearTimeout = function () {};
setInterval = function (fn) { _pollFn = fn; return 1; };

// 可控时钟：用于精确模拟"框选后 400ms 抑制窗口""双击 600ms 抑制窗口"等时序
var _fakeNow = Date.now();
Date.now = function () { return _fakeNow; };

// 同步 thenable：让 main.js 的 Promise 链同步执行，便于捕获异常
// 注意：模拟 Promise 的展平语义（res 的返回值成为链上的新值）
function thenable(v) {
  return {
    then: function (res) {
      var out = res(v);
      return thenable(out === undefined ? v : out);
    },
    catch: function () { return thenable(v); }
  };
}

var currentState = readJson("tests/snapshots/bidding.json");
var lastPostBody = null;
var actionResult = null;
var fetchCount = 0;
var stateNotModified = false;
fetch = function (url, opts) {
  fetchCount++;
  var isState = String(url).indexOf("/api/state") >= 0;
  if (!isState && opts) lastPostBody = String(opts.body || "");
  return thenable({
    ok: true,
    status: isState && stateNotModified ? 304 : 200,
    headers: { get: function () { return '"test-etag"'; } },
    json: function () {
      return isState ? currentState : (actionResult || { ok: true, state: currentState });
    }
  });
};

// ---------- 运行 ----------
var ok = true;
var detail = [];
function check(cond, msg) {
  if (cond) { detail.push("  ✓ " + msg); }
  else { ok = false; detail.push("  ✗ FAIL: " + msg); }
}

try {
  eval(readFile("doudizhu/game/js/render.js"));
  DDZ = window.DDZ;
  eval(readFile("doudizhu/game/js/main.js"));
  detail.push("  ✓ 脚本加载并完成首次渲染");

  // ---- 阶段 1：叫分（轮到人类） ----
  currentState = readJson("tests/snapshots/bidding.json");
  _pollFn();
  check(els.status.textContent.indexOf("请叫地主") >= 0, "叫分阶段状态文案");
  check(!els.btnBid0.classList.contains("hidden"), "叫分按钮可见");
  check(!els.bidPanel.classList.contains("hidden"), "叫分面板显示在战场中央");
  check(readFile("doudizhu/game/index.html").indexOf("bid-big") >= 0
        && readFile("doudizhu/game/css/style.css").indexOf("bid-big") >= 0,
        "叫分按钮放大样式定义");
  // ---- 开始游戏弹窗 ----
  check(els.welcomeModal.classList.contains("hidden"), "已叫分时不再显示开始弹窗");
  var wf = JSON.parse(JSON.stringify(currentState));
  wf.bid_highest = 0;
  wf.bidder = null;
  wf.phase = 'bidding';
  currentState = wf;
  _pollFn();
  check(!els.welcomeModal.classList.contains("hidden"), "全新未开始时显示开始弹窗");
  els.btnStartGame.fire("click");
  check(els.welcomeModal.classList.contains("hidden"), "点击开始游戏后弹窗关闭");
  currentState = readJson("tests/snapshots/bidding.json");
  _pollFn();
  els.btnBid2.fire("click");
  detail.push("  ✓ 点击 2分 按钮无异常");
  els.btnBid1.fire("click"); // 第二次点击（服务端会拒绝，但前端不应崩溃）
  detail.push("  ✓ 重复点击无异常");

  // ---- 阶段 2：出牌（轮到人类） ----
  currentState = readJson("tests/snapshots/playing.json");
  _pollFn();
  check(els.status.textContent.indexOf("轮到你出牌") >= 0, "出牌阶段状态文案");
  check(!els.btnPlay.classList.contains("hidden"), "出牌按钮可见");
  check(els.bidPanel.classList.contains("hidden"), "出牌阶段叫分面板隐藏");
  check(els.multBadge.textContent.indexOf("倍数 x") === 0, "顶栏倍数徽标");
  var b1 = els.left1.textContent, b2 = els.left2.textContent;
  check(b1 === String(currentState.hand_counts[1]) && b2 === String(currentState.hand_counts[2]),
        "电脑剩余牌数徽标 (" + b1 + "/" + b2 + ")");
  check(els.hand.innerHTML.indexOf("<svg") >= 0, "手牌已渲染 SVG");
  var cardCount = (els.hand.innerHTML.match(/data-id="/g) || []).length;
  check(cardCount === currentState.hands["0"].length,
        "手牌数量正确 (" + cardCount + " 张)");
  // 手牌 z-index 严格递增（右压左的正常重叠，选中/悬停不遮挡旁边牌）
  var zs = (els.hand.innerHTML.match(/z-index:(\d+)/g) || []).map(function (m) { return Number(m.match(/\d+/)[0]); });
  var zOk = zs.length === cardCount;
  for (var zi = 1; zi < zs.length; zi++) { if (zs[zi] <= zs[zi - 1]) zOk = false; }
  check(zOk, "手牌 z-index 递增（右压左，选中不遮挡旁边牌）");
  // ---- 牌面统一：J/Q/K/A/2 中央也必须是花色符号（回归防护） ----
  var faceOk = true;
  var badFaces = [];
  for (var fId = 0; fId < 52; fId++) {
    var info = DDZ.cardInfo(fId);
    if (info.rank < 11 && info.rank !== 15) continue;  // 只看 J/Q/K/A/2
    var svg = DDZ.cardSVG(fId);
    if (svg.indexOf('font-size="64"') < 0 || svg.indexOf('font-size="52"') >= 0) {
      faceOk = false;
      badFaces.push(fId);
    }
  }
  check(faceOk, "J/Q/K/A/2 牌面中央统一为大花色" + (badFaces.length ? "（异常牌: " + badFaces.join(",") + "）" : ""));

  // ---- 渲染早退优化：轮询相同状态不得重建 DOM（卡顿修复的回归防护） ----
  var m1 = els.multRow._setCount, s1 = els.status._setCount, l1 = els.logLine._setCount;
  _pollFn();
  _pollFn();
  check(els.multRow._setCount === m1 && els.status._setCount === s1 &&
        els.logLine._setCount === l1,
        "相同状态轮询不重建 DOM（倍数/状态/日志）");

  els.btnHint.fire("click");
  detail.push("  ✓ 点击提示无异常");
  els.btnPlay.fire("click");
  detail.push("  ✓ 点击出牌（空选）无异常");
  els.btnPass.fire("click");
  detail.push("  ✓ 点击不出无异常");

  // ---- 真实点击手牌路径（pointer 事件：单击切换 + 拖动框选） ----
  var cardIds = currentState.hands["0"].map(function (c) { return String(c.id); });
  function fakeCard(id) {
    return { closest: function () { return { getAttribute: function () { return id; } }; } };
  }
  function clickCardAt(i) {
    var id = cardIds[i % cardIds.length];
    els.hand.fire("pointerdown", { target: fakeCard(id), cancelable: true });
    document.fire("pointerup", {});
  }
  function dragFromTo(i, j) {
    var id0 = cardIds[i % cardIds.length];
    els.hand.fire("pointerdown", { target: fakeCard(id0), cancelable: true });
    document.elementFromPoint = function () { return fakeCard(cardIds[j % cardIds.length]); };
    document.fire("pointermove", { clientX: 0, clientY: 0 });
    document.elementFromPoint = function () { return null; };
    document.fire("pointerup", {});
  }
  // 选中态通过「出牌按钮可用性」与「出牌实际发送的牌」验证（renderHand 选中变化不再重建 innerHTML）
  function playAndGetCards() {
    els.btnPlay.fire("click");
    var s = JSON.parse(lastPostBody || "{}");
    return s.cards || [];
  }

  // 单击选中 / 取消
  clickCardAt(0);
  check(!els.btnPlay.disabled, "点击手牌可选中（出牌按钮启用）");
  clickCardAt(0);
  check(els.btnPlay.disabled, "再次点击同一张取消选中（出牌按钮禁用）");

  // 多选两张
  clickCardAt(0);
  clickCardAt(1);
  check(!els.btnPlay.disabled, "多选后出牌按钮启用");
  var two = playAndGetCards();
  check(two.length === 2 &&
        [Number(cardIds[0]), Number(cardIds[1])].every(function (id) { return two.indexOf(id) >= 0; }),
        "多选两张并出牌 [" + two.join(",") + "]");
  check(els.btnPlay.disabled, "出牌后选中清空（出牌按钮禁用）");

  // ---- 框选（累加模式：可多次乱序选牌） ----
  dragFromTo(0, 3);
  var four = playAndGetCards();
  check(four.length === 4 &&
        [0, 1, 2, 3].every(function (i) { return four.indexOf(Number(cardIds[i])) >= 0; }),
        "框选 0-3 出牌 4 张 [" + four.join(",") + "]");
  dragFromTo(0, 3);
  dragFromTo(5, 2);   // 反向拖动，结果并入已有选中
  var six = playAndGetCards();
  check(six.length === 6 &&
        [0, 1, 2, 3, 4, 5].every(function (i) { return six.indexOf(Number(cardIds[i])) >= 0; }),
        "两次乱序框选累加出牌 6 张 [" + six.join(",") + "]");

  // ---- 框选松手的同一 click 要抑制，随后主动点空白应立即出牌 ----
  dragFromTo(0, 3);
  _fakeNow += 10;
  lastPostBody = null;
  els.app.fire("click", { target: { closest: function () { return null; } } });
  check(!lastPostBody, "框选松手同一手势的 click 被抑制");
  _fakeNow += 100;
  els.app.fire("click", { target: { closest: function () { return null; } } });
  var blankPlay = JSON.parse(lastPostBody || "{}");
  check(blankPlay.action === "play" && blankPlay.cards.length === 4,
        "左键单击空白区域出牌");

  // ---- 无选牌时左键双击空白区域不出 ----
  _fakeNow += 1000;
  lastPostBody = null;
  els.app.fire("dblclick", { target: { closest: function () { return null; } } });
  var blankPass = JSON.parse(lastPostBody || "{}");
  check(blankPass.action === "pass", "左键双击空白区域不出");
  lastPostBody = null;
  els.app.fire("dblclick", { target: fakeCard(cardIds[0]) });
  check(!lastPostBody, "双击牌面不触发不出");

  // ---- 非法出牌保留完整选择，可直接调整 / 重试 ----
  clickCardAt(0);
  clickCardAt(1);
  actionResult = { ok: false, error: '不是合法牌型', state: currentState };
  var rejected = playAndGetCards();
  check(rejected.length === 2 && !els.btnPlay.disabled, "非法出牌后保留选牌");
  actionResult = null;
  var retried = playAndGetCards();
  check(JSON.stringify(retried) === JSON.stringify(rejected) && els.btnPlay.disabled,
        "重试提交相同选牌，成功后才清空");

  els.hand.fire('click', { detail: 0, target: fakeCard(cardIds[0]) });
  check(!els.btnPlay.disabled, '键盘 / 辅助技术点击可选牌');
  playAndGetCards();
  check(els.hand.innerHTML.indexOf('aria-pressed=') >= 0 && DDZ.cardLabel(0) === '黑桃 3',
        '手牌有可读名称和选中语义');

  var beforeHidden = fetchCount;
  document.hidden = true;
  window.speechSynthesis._last = null;
  var hiddenState = JSON.parse(JSON.stringify(currentState));
  hiddenState.last_plays[2] = { player: 2, passed: false, cards: [0, 13], type: 'pair', main_rank: 3, label: '对子 3' };
  currentState = hiddenState;
  _pollFn();
  check(fetchCount > beforeHidden && window.speechSynthesis._last === '对三',
        '后台保留低频同步和出牌语音');
  document.hidden = false;
  document.fire('visibilitychange');
  check(fetchCount > beforeHidden, '回到前台立即同步状态');
  stateNotModified = true;
  var before304 = els.hand._setCount;
  _pollFn();
  check(els.hand._setCount === before304, '304 响应不重建手牌');
  stateNotModified = false;

  // ---- 语音播报：任何一方出牌/不出都触发 Web Speech 播报 ----
  var vs = JSON.parse(JSON.stringify(currentState));
  vs.last_plays[2] = { player: 2, passed: false, cards: [0, 13], type: 'pair', main_rank: 3, label: '对子 3' };
  currentState = vs;
  _pollFn();
  check(window.speechSynthesis._last === '对三', "出对子播报「对三」，实际: " + window.speechSynthesis._last);
  check(window.speechSynthesis._voice === 'Meijia', "自动选用自然中文语音（Meijia），实际: " + window.speechSynthesis._voice);
  var vs2 = JSON.parse(JSON.stringify(currentState));
  vs2.last_plays[0] = { player: 0, passed: true, cards: [], type: null, main_rank: null, label: '不出' };
  currentState = vs2;
  _pollFn();
  check(window.speechSynthesis._last === '要不起', "不出播报「要不起」，实际: " + window.speechSynthesis._last);
  // 炸弹/王炸播报
  var vs3 = JSON.parse(JSON.stringify(currentState));
  vs3.last_plays[1] = { player: 1, passed: false, cards: [3, 16, 29, 42], type: 'bomb', main_rank: 6, label: '炸弹 6' };
  currentState = vs3;
  _pollFn();
  check(window.speechSynthesis._last === '炸弹', "炸弹播报「炸弹」，实际: " + window.speechSynthesis._last);

  // ---- 叫分语音播报 ----
  var vb = JSON.parse(JSON.stringify(currentState));
  vb.bid_event = { kind: 'bid', bid: 3, player: 0 };
  currentState = vb;
  _pollFn();
  check(window.speechSynthesis._last === '三分', "叫 3 分播报「三分」，实际: " + window.speechSynthesis._last);
  var vb2 = JSON.parse(JSON.stringify(currentState));
  vb2.bid_event = { kind: 'landlord', bid: 3, player: 2 };
  currentState = vb2;
  _pollFn();
  check(window.speechSynthesis._last === '抢地主', "地主确定播报「抢地主」，实际: " + window.speechSynthesis._last);
  var vb3 = JSON.parse(JSON.stringify(currentState));
  vb3.bid_event = { kind: 'pass', player: 1 };
  currentState = vb3;
  _pollFn();
  check(window.speechSynthesis._last === '不叫', "不叫播报「不叫」，实际: " + window.speechSynthesis._last);

  // ---- 按钮点击音效（Web Audio 合成） ----
  window.__oscCount = 0;
  document.fire("click", { target: { closest: function (sel) {
    return sel === 'button' ? { disabled: false, classList: { contains: function (c) { return c === 'primary'; } } } : null;
  } } });
  check(window.__oscCount > 0, "按钮点击触发音效（oscillator 创建 " + window.__oscCount + " 次）");
  // 禁用按钮不触发音效
  window.__oscCount = 0;
  document.fire("click", { target: { closest: function (sel) {
    return sel === 'button' ? { disabled: true, classList: { contains: function () { return false; } } } : null;
  } } });
  check(window.__oscCount === 0, "禁用按钮不触发音效");

  els.btnSettings.fire("click");
  check(!els.settingsModal.classList.contains("hidden"), "设置弹窗打开");
  check(document.activeElement === els.setSpeed && els.app.inert, '弹窗打开后聚焦设置并隔离背景');
  document.fire('keydown', { key: 'Tab', shiftKey: true });
  check(document.activeElement === els.btnCloseSettings, 'Shift Tab 在弹窗内循环');
  els.btnCloseSettings.fire("click");
  check(els.settingsModal.classList.contains("hidden"), "设置弹窗关闭");
  check(!els.app.inert, '关闭弹窗后恢复背景操作');
  els.setAuto.fire("change");
  detail.push("  ✓ 切换托管无异常");

  // ---- 阶段 3：结算 ----
  currentState = readJson("tests/snapshots/over.json");
  _pollFn();
  check(!els.resultModal.classList.contains("hidden"), "结算弹窗显示");
  check(els.resultTitle.textContent.length > 0, "结算标题: " + els.resultTitle.textContent);
  // 地主身份标签应显示
  var l = currentState.landlord;
  check(els["role" + l].textContent === "地主", "地主身份标签 (player " + l + ")");
  // 头像形象：地主显示地主形象（红瓜皮帽），农民显示农民形象（草帽）
  check(els["avatar" + l].innerHTML.indexOf("c0392b") >= 0 &&
        els["avatar" + l].innerHTML.indexOf("ffd76a") >= 0,
        "地主头像显示地主形象（瓜皮帽）");
  var f1 = (l + 1) % 3, f2 = (l + 2) % 3;
  check(els["avatar" + f1].innerHTML.indexOf("e6b84a") >= 0 &&
        els["avatar" + f2].innerHTML.indexOf("e6b84a") >= 0,
        "农民头像显示农民形象（草帽）");

  // ---- 玩家胜利：播放喝彩（语音断言；彩带为纯视觉特效） ----
  var winState = JSON.parse(JSON.stringify(currentState));
  winState.version = 99;   // 新版本触发结算渲染
  winState.winners = [0];
  winState.landlord = 0;   // 玩家是地主且获胜
  currentState = winState;
  _pollFn();
  check(els.resultTitle.textContent.indexOf("你赢了") >= 0, "玩家胜利标题");
  check(window.speechSynthesis._last === "太棒了！你赢了！",
        "玩家胜利播放喝彩语音，实际: " + window.speechSynthesis._last);
  els.btnAgain.fire("click");
  detail.push("  ✓ 再来一局无异常");
  els.btnCloseResult.fire("click");
  detail.push("  ✓ 关闭结算无异常");

  // ---- 阶段 4：新一局按钮 ----
  els.btnNewRound.fire("click");
  detail.push("  ✓ 新一局无异常");

  if (ok) { console.log("SMOKE OK"); }
  else { console.log("SMOKE FAIL"); }
  for (var d = 0; d < detail.length; d++) console.log(detail[d]);
} catch (e) {
  ok = false;
  console.log("SMOKE FAIL (runtime error): " + e);
}
ok;
