/* 斗地主 · 卡牌 SVG 渲染器（全部卡牌由代码手绘，无外部图片） */
(function () {
  'use strict';

  var RANK_TEXT = {
    3: '3', 4: '4', 5: '5', 6: '6', 7: '7', 8: '8', 9: '9', 10: '10',
    11: 'J', 12: 'Q', 13: 'K', 14: 'A', 15: '2', 16: '小王', 17: '大王'
  };
  var SUIT_TEXT = { 0: '♠', 1: '♥', 2: '♣', 3: '♦' };
  var SUIT_RED = { 0: false, 1: true, 2: false, 3: true };

  function cardInfo(id) {
    id = Number(id);
    if (id === 52) return { rank: 16, suit: null };
    if (id === 53) return { rank: 17, suit: null };
    return { rank: (id % 13) + 3, suit: Math.floor(id / 13) };
  }

  function rankName(id) {
    return RANK_TEXT[cardInfo(id).rank];
  }

  function cardLabel(id) {
    var info = cardInfo(id);
    if (info.suit === null) return RANK_TEXT[info.rank];
    return SUIT_TEXT[info.suit] + RANK_TEXT[info.rank];
  }

  function colorOf(info) {
    if (info.suit === null) return info.rank === 17 ? '#d0342c' : '#20242b';
    return SUIT_RED[info.suit] ? '#d0342c' : '#20242b';
  }

  /* 普通牌面 */
  function faceSVG(info) {
    var color = colorOf(info);
    var rankT = RANK_TEXT[info.rank];
    var suitT = SUIT_TEXT[info.suit];
    // 牌面中央统一为大花色符号（J/Q/K/A/2 与 3-10 完全一致，只靠角标区分牌值）
    var big = '<text x="50" y="94" text-anchor="middle" font-size="64" fill="' + color + '">' + suitT + '</text>';
    return '' +
      '<rect x="1" y="1" width="98" height="138" rx="9" fill="#ffffff" stroke="#c9cdd4" stroke-width="1.5"/>' +
      '<text x="11" y="27" font-size="24" font-weight="bold" fill="' + color + '">' + rankT + '</text>' +
      '<text x="11" y="46" font-size="17" fill="' + color + '">' + suitT + '</text>' +
      '<g transform="translate(100 140) rotate(180)">' +
        '<text x="11" y="27" font-size="24" font-weight="bold" fill="' + color + '">' + rankT + '</text>' +
        '<text x="11" y="46" font-size="17" fill="' + color + '">' + suitT + '</text>' +
      '</g>' +
      big;
  }

  /* 王牌（小王/大王） */
  function jokerSVG(rank) {
    var big = rank === 17;
    var c1 = big ? '#e04a3c' : '#414a58';
    var c2 = big ? '#a21f14' : '#14181f';
    var tag = big ? '大' : '小';
    return '' +
      '<defs><linearGradient id="jg' + (big ? 'B' : 'S') + '" x1="0" y1="0" x2="1" y2="1">' +
        '<stop offset="0" stop-color="' + c1 + '"/><stop offset="1" stop-color="' + c2 + '"/>' +
      '</linearGradient></defs>' +
      '<rect x="1" y="1" width="98" height="138" rx="9" fill="url(#jg' + (big ? 'B' : 'S') + ')" stroke="#00000040" stroke-width="1.5"/>' +
      '<text x="50" y="82" text-anchor="middle" font-size="54" font-weight="bold" fill="#ffffff">王</text>' +
      '<text x="50" y="112" text-anchor="middle" font-size="16" letter-spacing="2" fill="#ffffffcc">JOKER</text>' +
      '<text x="88" y="28" text-anchor="middle" font-size="22" font-weight="bold" fill="#ffffff">' + tag + '</text>' +
      '<text x="12" y="126" text-anchor="middle" font-size="22" font-weight="bold" fill="#ffffff">' + tag + '</text>';
  }

  /* 牌背 */
  function backSVG() {
    return '' +
      '<defs><pattern id="backpat" width="20" height="20" patternUnits="userSpaceOnUse">' +
        '<rect width="20" height="20" fill="#1e4e8f"/>' +
        '<path d="M10 3 L17 10 L10 17 L3 10 Z" fill="#2c66b0"/>' +
      '</pattern></defs>' +
      '<rect x="1" y="1" width="98" height="138" rx="9" fill="url(#backpat)" stroke="#0f3460" stroke-width="2"/>' +
      '<rect x="7" y="7" width="86" height="126" rx="7" fill="none" stroke="#ffd76a" stroke-width="1.4" opacity="0.85"/>' +
      '<circle cx="50" cy="70" r="19" fill="#0f3460" stroke="#ffd76a" stroke-width="1.6"/>' +
      '<text x="50" y="78" text-anchor="middle" font-size="19" font-weight="bold" fill="#ffd76a">斗</text>';
  }

  /* 对外：生成卡牌 SVG 字符串 */
  function cardSVG(id, faceDown) {
    var info = cardInfo(id);
    var inner;
    if (faceDown) {
      inner = backSVG();
    } else if (info.suit === null) {
      inner = jokerSVG(info.rank);
    } else {
      inner = faceSVG(info);
    }
    return '<svg viewBox="0 0 100 140" class="card-svg" aria-hidden="true">' + inner + '</svg>';
  }

  /* 地主头像：红色瓜皮帽 + 金珠 + 得意大笑 + 小胡子 */
  function landlordAvatarSVG() {
    return '<svg viewBox="0 0 100 100" class="avatar-svg" aria-hidden="true">' +
      '<circle cx="50" cy="50" r="49" fill="#7e2b23"/>' +
      '<circle cx="50" cy="50" r="45" fill="#a83a2c"/>' +
      '<path d="M27 41 Q27 16 50 16 Q73 16 73 41 Q50 33 27 41 Z" fill="#c0392b"/>' +
      '<rect x="25" y="38" width="50" height="8" rx="4" fill="#8e2b20"/>' +
      '<rect x="25" y="38" width="50" height="3.5" rx="1.75" fill="#ffd76a"/>' +
      '<circle cx="50" cy="15" r="5.5" fill="#ffd76a"/>' +
      '<circle cx="50" cy="62" r="21" fill="#f6d9ae"/>' +
      '<path d="M39 53 Q44 49 49 53" stroke="#3a2b20" stroke-width="2.4" fill="none" stroke-linecap="round"/>' +
      '<path d="M51 53 Q56 49 61 53" stroke="#3a2b20" stroke-width="2.4" fill="none" stroke-linecap="round"/>' +
      '<circle cx="44" cy="60" r="2.7" fill="#3a2b20"/>' +
      '<circle cx="56" cy="60" r="2.7" fill="#3a2b20"/>' +
      '<path d="M41 68 Q50 77 59 68 Q50 71 41 68 Z" fill="#7e4431"/>' +
      '<path d="M44 70 Q50 74 56 70" stroke="#7e4431" stroke-width="2" fill="none" stroke-linecap="round"/>' +
      '<path d="M42 73 Q50 77 58 73" stroke="#4a3526" stroke-width="2.6" fill="none" stroke-linecap="round"/>' +
      '</svg>';
  }

  /* 农民头像：草帽 + 微笑 + 腮红 */
  function farmerAvatarSVG() {
    return '<svg viewBox="0 0 100 100" class="avatar-svg" aria-hidden="true">' +
      '<circle cx="50" cy="50" r="49" fill="#6e5a2c"/>' +
      '<circle cx="50" cy="50" r="45" fill="#7d6a3a"/>' +
      '<ellipse cx="50" cy="40" rx="39" ry="11" fill="#e6b84a"/>' +
      '<path d="M33 38 Q33 12 50 12 Q67 12 67 38 Q50 30 33 38 Z" fill="#d9a63a"/>' +
      '<rect x="33" y="34.5" width="34" height="6" rx="3" fill="#b5812c"/>' +
      '<circle cx="50" cy="63" r="21" fill="#f6d9ae"/>' +
      '<circle cx="44" cy="60" r="2.7" fill="#3a2b20"/>' +
      '<circle cx="56" cy="60" r="2.7" fill="#3a2b20"/>' +
      '<path d="M43 68 Q50 73 57 68" stroke="#8c5a3a" stroke-width="2.6" fill="none" stroke-linecap="round"/>' +
      '<circle cx="37" cy="66" r="4" fill="#f2a48b" opacity="0.85"/>' +
      '<circle cx="63" cy="66" r="4" fill="#f2a48b" opacity="0.85"/>' +
      '</svg>';
  }

  window.DDZ = {
    cardSVG: cardSVG,
    backSVG: function () { return '<svg viewBox="0 0 100 140" class="card-svg" aria-hidden="true">' + backSVG() + '</svg>'; },
    cardInfo: cardInfo,
    cardLabel: cardLabel,
    rankName: rankName,
    RANK_TEXT: RANK_TEXT,
    SUIT_TEXT: SUIT_TEXT,
    landlordAvatar: landlordAvatarSVG,
    farmerAvatar: farmerAvatarSVG
  };
})();
