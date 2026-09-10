// 可选浏览器回归：需已安装 Playwright 与 Chromium；游戏运行时仍零第三方依赖。
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const base = process.env.DDZ_TEST_URL || 'http://127.0.0.1:9325';
const artifacts = fs.mkdtempSync(path.join(os.tmpdir(), 'ddz-playtest-'));
console.log('Screenshots: '+artifacts);

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.CHROME_EXECUTABLE ? { executablePath: process.env.CHROME_EXECUTABLE } : {}) });
  const errors = [];
  try {
    for (const [width, height] of [[1280,720], [390,844], [844,390], [320,568]]) {
      const context = await browser.newContext({ viewport: {width,height}, reducedMotion:'reduce' });
      const page = await context.newPage();
      page.on('pageerror', e => errors.push(e.message));
      await page.goto(base);
      // 独立测试局：选择人类先叫，避免随机 AI 手牌影响手动交互用例。
      let setup = await (await context.request.post(base+'/api/action', {data:{action:'set_delay',ms:5000}})).json();
      assert.equal(setup.ok, true, `${width}: failed to slow fixture bots`);
      setup = await (await context.request.post(base+'/api/action', {data:{action:'set_auto',on:false}})).json();
      assert.equal(setup.ok, true, `${width}: failed to disable fixture autopilot`);
      let s = await (await context.request.get(base+'/api/state')).json();
      for (let n=0; n<24 && (s.phase!=='bidding' || s.turn!==0 || s.bid_highest!==0); n++) {
        s = (await (await context.request.post(base+'/api/action', {data:{action:'new_round'}})).json()).state;
      }
      assert.equal(s.phase, 'bidding', `${width}: failed to prepare bidding fixture`);
      assert.equal(s.turn, 0, `${width}: failed to prepare human-first fixture`);
      assert.equal(s.bid_highest, 0, `${width}: fixture already has a higher bid`);
      await page.reload();
      if (await page.locator('#welcomeModal').isVisible()) await page.locator('#btnStartGame').click();
      await page.waitForFunction(() => !document.querySelector('#btnBid3').disabled);
      await page.screenshot({path:path.join(artifacts,`${width}x${height}-bidding.png`), animations:'disabled'});
      await page.locator('#btnBid3').click();
      await page.waitForFunction(() => !document.querySelector('#btnHint').disabled && !document.querySelector('#btnHint').classList.contains('hidden'));
      await page.screenshot({path:path.join(artifacts,`${width}x${height}-playing.png`), animations:'disabled'});
      const layout = await page.evaluate(() => {
        const box = e => {const r=e.getBoundingClientRect(); return {left:r.left,right:r.right,top:r.top,bottom:r.bottom};};
        return {viewport:[innerWidth,innerHeight], scroll:[document.documentElement.scrollWidth,document.documentElement.scrollHeight],
          controls:box(document.querySelector('#controls')), cards:[...document.querySelectorAll('#hand .card')].map(box)};
      });
      assert(layout.scroll[0] <= width+1, `${width}: horizontal overflow`);
      assert(layout.scroll[1] <= height+1, `${width}: vertical overflow ${JSON.stringify(layout)}`);
      assert(layout.controls.bottom <= height, `${width}: controls below viewport`);
      assert(layout.cards.every(r=>r.left>=0 && r.right<=width), `${width}: clipped hand`);

      const cards = page.locator('#hand .card');
      const ids = await cards.evaluateAll(nodes=>nodes.map(n=>Number(n.dataset.id)));
      const first = ids.find(id=>id<52);
      const second = ids.find(id=>id<52 && id%13!==first%13);
      // 用键盘选两张不同点数的普通牌；非法提交应保留它们。
      await page.locator(`[data-id="${first}"]`).focus();
      await page.keyboard.press('Space');
      await page.locator(`[data-id="${second}"]`).focus();
      await page.keyboard.press('Enter');
      // 已选两张不同点数牌：左键单击战场空白处应走出牌快捷入口。
      await page.locator('.battlefield').click({position:{x:8,y:8}});
      await page.waitForFunction(()=>document.querySelector('#toast').classList.contains('error'));
      assert.equal(await page.locator('#hand [aria-pressed="true"]').count(), 2);
      await page.route('**/api/action', route=>route.abort('failed'));
      await page.locator('#btnPlay').click();
      await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('未送达'));
      assert.equal(await page.locator('#hand [aria-pressed="true"]').count(), 2);
      await page.unroute('**/api/action');
      // 网络失败提示已经验证；清掉它，避免污染随后用于人工检查布局的设置截图。
      await page.evaluate(()=>document.querySelector('#toast').className='toast hidden');
      await page.locator('#btnSettings').click();
      await page.locator('#settingsModal').waitFor({state:'visible'});
      assert.equal(await page.evaluate(()=>document.activeElement.id),'setSpeed');
      await page.keyboard.press('Shift+Tab');
      assert.equal(await page.evaluate(()=>document.activeElement.id),'btnCloseSettings');
      await page.screenshot({path:path.join(artifacts,`${width}x${height}-settings.png`), animations:'disabled'});
      await page.keyboard.press('Escape');
      assert.equal(await page.evaluate(()=>document.activeElement.id),'btnSettings');
      await page.locator('#btnHint').click();
      await page.waitForFunction(()=>document.querySelectorAll('#hand [aria-pressed="true"]').length>0);
      const countBefore = await cards.count();
      await page.locator('.battlefield').click({position:{x:8,y:8}});
      await page.waitForFunction(n=>document.querySelectorAll('#hand .card').length<n,countBefore);
      // 注入一个可不出的前端状态，验证双击空白只提交 pass，两个前置 click 不会出牌。
      const shortcutState = JSON.parse(fs.readFileSync(path.join(__dirname,'snapshots/playing.json'),'utf8'));
      shortcutState.phase = 'playing'; shortcutState.turn = 0; shortcutState.human_turn = true;
      shortcutState.can_pass = true; shortcutState.settings.auto_pilot = false;
      let shortcutAction = null;
      await page.route('**/api/state', route=>route.fulfill({json:shortcutState}));
      await page.route('**/api/action', async route=>{
        shortcutAction = route.request().postDataJSON().action;
        await route.fulfill({json:{ok:true,state:shortcutState}});
      });
      await page.reload();
      await Promise.all([
        page.waitForResponse(r=>r.url().endsWith('/api/action')),
        page.locator('.battlefield').dblclick({position:{x:8,y:8}})
      ]);
      assert.equal(shortcutAction,'pass');
      await page.unroute('**/api/action');
      console.log(`PASS ${width}x${height}: layout, keyboard, blank-click play, blank-double-click pass, invalid selection, modal`);
      // 仅视觉压力夹具：三家同时展示最长的 20 张牌，检查各自槽位不溢出。
      const fixture = shortcutState;
      const longPlay = [0,13,26,1,14,27,2,15,28,3,16,29,4,17,30,5,6,7,8,9];
      fixture.last_plays = [0,1,2].map(player=>({player,passed:false,cards:longPlay,type:'airplane_single',main_rank:7,label:'飞机带单'}));
      await page.unroute('**/api/state');
      await page.route('**/api/state', route=>route.fulfill({json:fixture}));
      await page.reload();
      await page.waitForFunction(()=>document.querySelectorAll('.played-cards .mini').length===60);
      await page.screenshot({path:path.join(artifacts,`${width}x${height}-long-play-fixture.png`),animations:'disabled'});
      const fits = await page.evaluate(()=>[...document.querySelectorAll('.play-slot')].every(slot=>{
        const r=slot.getBoundingClientRect();
        return [...slot.querySelectorAll('.mini')].every(card=>{
          const c=card.getBoundingClientRect(); return c.left>=r.left-1 && c.right<=r.right+1;
        });
      }));
      assert(fits,`${width}: long combination outside its play slot`);
      const separated = await page.evaluate(()=>{
        const groups=[...document.querySelectorAll('.play-slot')].map(slot=>{
          const cards=[...slot.querySelectorAll('.mini')].map(card=>card.getBoundingClientRect());
          return {left:Math.min(...cards.map(r=>r.left)),right:Math.max(...cards.map(r=>r.right)),
            top:Math.min(...cards.map(r=>r.top)),bottom:Math.max(...cards.map(r=>r.bottom))};
        });
        return groups.every((a,i)=>groups.slice(i+1).every(b=>
          a.right<=b.left+1 || b.right<=a.left+1 || a.bottom<=b.top+1 || b.bottom<=a.top+1));
      });
      assert(separated,`${width}: long combinations visually overlap another play area`);
      await context.close();
    }
    // 一个动作在途时点击“新一局”，旧请求会中止并随后提交新局，不能吞掉点击。
    {
      const context = await browser.newContext({viewport:{width:844,height:390}});
      const page = await context.newPage();
      const fixture = JSON.parse(fs.readFileSync(path.join(__dirname,'snapshots/playing.json'),'utf8'));
      fixture.phase='playing'; fixture.turn=0; fixture.human_turn=true; fixture.settings.auto_pilot=false;
      let releaseHint;
      let roundResolve;
      const roundPosted = new Promise(resolve=>{ roundResolve=resolve; });
      await page.route('**/api/state', route=>route.fulfill({json:fixture}));
      await page.route('**/api/action', async route=>{
        const action=route.request().postDataJSON().action;
        if(action==='hint') await new Promise(resolve=>{ releaseHint=resolve; });
        if(action==='new_round') roundResolve();
        await route.fulfill({json:{ok:true,hint:{kind:'play',pass:false,cards:[fixture.hands['0'][0].id]},state:fixture}});
      });
      await page.goto(base);
      if(await page.locator('#welcomeModal').isVisible()) await page.locator('#btnStartGame').click();
      await page.locator('#btnHint').click();
      await page.waitForFunction(()=>document.querySelector('#btnHint').disabled);
      page.once('dialog',dialog=>dialog.accept());
      await page.locator('#btnNewRound').click();
      releaseHint();
      await Promise.race([roundPosted,new Promise((_,reject)=>setTimeout(()=>reject(new Error('new round was swallowed')),3000))]);
      console.log('PASS pending action does not swallow new-round request');
      await context.close();
    }
    // 实际浏览器托管跑完一局，验证结果弹窗与再来一局。
    const context = await browser.newContext({viewport:{width:1280,height:720}});
    const page = await context.newPage();
    page.on('pageerror', e=>errors.push(e.message));
    await page.goto(base);
    if (await page.locator('#welcomeModal').isVisible()) await page.locator('#btnStartGame').click();
    await page.locator('#btnSettings').click();
    await page.locator('#setSpeed').focus();
    await page.keyboard.press('Home');
    await page.waitForFunction(()=>document.querySelector('#speedVal').textContent.includes('0.2'));
    await page.locator('#setAuto').check();
    await page.locator('#btnCloseSettings').click();
    await page.locator('#resultModal').waitFor({state:'visible',timeout:45000});
    const result = await (await context.request.get(base+'/api/state')).json();
    assert.equal(result.phase,'round_over');
    const mult = 2 ** (result.bombs_used+result.rockets_used+(result.spring||result.anti_spring?1:0));
    assert.equal(result.multiplier,mult);
    assert((await page.locator('#resultBody').innerText()).includes('倍数 x'+mult));
    await page.screenshot({path:path.join(artifacts,'actual-round-result.png'),animations:'disabled'});
    await context.request.post(base+'/api/action',{data:{action:'set_auto',on:false}});
    await page.locator('#btnAgain').click();
    await page.locator('#resultModal').waitFor({state:'hidden'});
    assert.equal((await (await context.request.get(base+'/api/state')).json()).round_no,result.round_no+1);
    console.log('PASS actual autopilot round, result multiplier, replay; no uncaught page errors');
    await context.close();
    assert.deepEqual(errors, []);
    console.log('Screenshots: '+artifacts);
  } finally { await browser.close(); }
})().catch(e=>{console.error(e); process.exitCode=1;});
