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
var window = { confirm: function () { return true; } };
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
fetch = function (url, opts) {
  var isState = String(url).indexOf("/api/state") >= 0;
  if (!isState && opts) lastPostBody = String(opts.body || "");
  return thenable({
    json: function () {
      return isState ? currentState : { ok: true, state: currentState };
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
  var m1 = els.multRow._setCount, c1 = els.counterRow._setCount, s1 = els.status._setCount;
  _pollFn();
  _pollFn();
  check(els.multRow._setCount === m1 && els.counterRow._setCount === c1 &&
        els.status._setCount === s1,
        "相同状态轮询不重建 DOM（倍数/记牌器/状态）");

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

  // ---- 空白单击 = 出牌（任意空白区域，无需点按钮） ----
  _fakeNow += 1000;   // 越过框选后的 click 抑制窗口
  lastPostBody = null;
  clickCardAt(0);
  clickCardAt(1);   // 选两张
  els.app.fire("click", { target: { closest: function () { return null; } } });
  var bc = JSON.parse(lastPostBody || "{}");
  check(bc.action === "play" && (bc.cards || []).length === 2 &&
        [Number(cardIds[0]), Number(cardIds[1])].every(
          function (id) { return (bc.cards || []).indexOf(id) >= 0; }),
        "空白单击直接出牌 [" + (bc.cards || []).join(",") + "]");
  check(els.btnPlay.disabled, "空白出牌后选中清空（出牌按钮禁用）");
  lastPostBody = null;
  els.app.fire("click", { target: { closest: function () { return null; } } });
  check(!lastPostBody, "无选中时空白单击不发请求");

  // ---- 双击空白区域 = 不出（无选中时） ----
  _fakeNow += 1000;   // 让上一次"空白单击出牌"时间戳过期，双击才生效
  lastPostBody = null;
  els.app.fire("dblclick", { target: { closest: function () { return null; } } });
  var dbSent = JSON.parse(lastPostBody || "{}");
  check(dbSent.action === "pass", "双击空白触发不出");
  // 双击在牌上不触发
  lastPostBody = null;
  els.app.fire("dblclick", { target: fakeCard(cardIds[0]) });
  var db2 = JSON.parse(lastPostBody || "{}");
  check(!db2 || db2.action !== "pass", "双击在牌上不触发不出");
  // 刚用空白单击出过牌后，双击被抑制（不会误触发"不出"）
  lastPostBody = null;
  clickCardAt(0);
  clickCardAt(1);
  els.app.fire("click", { target: { closest: function () { return null; } } });  // 空白出牌
  var afterPlay = JSON.parse(lastPostBody || "{}");
  els.app.fire("dblclick", { target: { closest: function () { return null; } } });
  var db3 = JSON.parse(lastPostBody || "{}");
  check(afterPlay.action === "play" && db3.action !== "pass",
        "空白单击出牌后双击被抑制（不会误不出）");

  els.btnSettings.fire("click");
  check(!els.settingsModal.classList.contains("hidden"), "设置弹窗打开");
  els.btnCloseSettings.fire("click");
  check(els.settingsModal.classList.contains("hidden"), "设置弹窗关闭");
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
