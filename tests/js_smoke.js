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
    getAttribute: function () { return null; },
    setAttribute: function () {},
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
setTimeout = function () { return 0; };
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
var nextPostResponse = null;
fetch = function (url, opts) {
  var isState = String(url).indexOf("/api/state") >= 0;
  if (!isState && opts) lastPostBody = String(opts.body || "");
  return thenable({
    headers: { get: function () { return "test-token"; } },
    json: function () {
      if (isState) return currentState;
      var out = nextPostResponse || { ok: true, state: currentState };
      nextPostResponse = null;
      return out;
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
  wf.settings.started = false;
  currentState = wf;
  _pollFn();
  check(!els.welcomeModal.classList.contains("hidden"), "全新未开始时显示开始弹窗");
  var started = JSON.parse(JSON.stringify(wf));
  started.settings.started = true;
  started.version += 1;
  nextPostResponse = { ok: true, state: started };
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

  // ---- 非法出牌保留选择，空白区域不再误触出牌/不出 ----
  clickCardAt(0);
  clickCardAt(1);
  nextPostResponse = { ok: false, error: '所选牌型不合法', state: currentState };
  lastPostBody = null;
  els.btnPlay.fire("click");
  var rejected = JSON.parse(lastPostBody || "{}");
  check(rejected.action === "play" && rejected.cards.length === 2,
        "非法出牌请求正确送达");
  check(!els.btnPlay.disabled, "非法出牌后保留选择（出牌按钮仍可用）");

  lastPostBody = null;
  els.app.fire("click", { target: { closest: function () { return null; } } });
  check(!lastPostBody, "空白单击不触发出牌");
  els.app.fire("dblclick", { target: { closest: function () { return null; } } });
  check(!lastPostBody, "空白双击不触发不出");
  // 清理保留的两张选择，后续测试从空选择继续。
  clickCardAt(0);
  clickCardAt(1);

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
  els.btnCloseSettings.fire("click");
  check(els.settingsModal.classList.contains("hidden"), "设置弹窗关闭");
  els.setAuto.fire("change");
  detail.push("  ✓ 切换托管无异常");

  // ---- 阶段 3：结算 ----
  // 恢复一个已结算但尚未重新确认“开始”的存档：只能显示结算，且应关闭设置，
  // 不能叠加欢迎、设置、结算三层弹窗。
  els.btnSettings.fire("click");
  var restoredOver = readJson("tests/snapshots/over.json");
  restoredOver.settings.started = false;
  currentState = restoredOver;
  _pollFn();
  check(els.welcomeModal.classList.contains("hidden"), "恢复已结算存档不叠加开始弹窗");
  check(els.settingsModal.classList.contains("hidden"), "结算时自动关闭设置弹窗");
  check(!els.resultModal.classList.contains("hidden"), "恢复已结算存档显示结算弹窗");

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
