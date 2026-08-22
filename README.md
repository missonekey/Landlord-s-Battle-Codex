# 斗地主 · Dou Dizhu（Codex 插件）

一个完整复刻标准「斗地主」规则的卡牌游戏，以 **Codex 插件**形式分发：在 Codex 中一句话即可启动，本地浏览器对战两名策略 AI。

- 🎮 完整标准规则：叫分制叫地主（不叫 / 1 / 2 / 3 分）、底牌、全部牌型、炸弹/王炸/春天/反春翻倍
- 🧠 两名「Codex 参与」的 AI 玩家：内置策略引擎，会算牌、会配合队友、会拆牌压牌
- 🔉 游戏声音：出牌/不出语音播报（对三、要不起、炸弹、王炸…）+ 按钮点击音效，可一键关闭
- 🃏 卡牌全部由代码手绘（SVG），无任何外部图片素材
- 🖥 界面参考腾讯欢乐斗地主布局：三家出牌集中展示在中央对战区，头像皇冠标识地主、剩余牌数徽标、底牌/倍数/记牌器清晰分区
- 🔒 完全离线本地运行，仅监听 127.0.0.1
- ✅ 通过 58 项自动化测试 + 数千局 AI 全自动模拟 + 前端冒烟测试

---

## 一、安装

### 方式 A：从市场安装（推荐，适合使用者）

本仓库自带**仓库级市场文件** `.agents/plugins/marketplace.json`（符合 Codex 插件规范），发布者把仓库推到 GitHub 等平台后，使用者只需：

```bash
codex plugin marketplace add <仓库地址>   # 例如 https://github.com/你的用户名/doudizhu
codex plugin install doudizhu
```

然后在 Codex 中说「玩斗地主」即可。

### 方式 B：个人市场安装（作者本机）

```bash
# 在本项目根目录执行（需要 python3）
./install.sh
```

脚本会：
1. 把插件复制到 `~/plugins/doudizhu`
2. 在个人市场 `~/.agents/plugins/marketplace.json` 注册 `doudizhu` 条目（符合 Codex 插件规范）

验证：

```bash
codex plugin list          # 应能看到 doudizhu
python3 ~/plugins/doudizhu/scripts/start_game.py   # 手动启动游戏
```

## 二、发布（供作者）

1. 保持仓库根目录下的 `.agents/plugins/marketplace.json` 与 `doudizhu/` 插件目录不动。
2. 把整个仓库推送到公开仓库（如 GitHub）。
3. 告诉使用者执行 `codex plugin marketplace add <仓库地址>` + `codex plugin install doudizhu`。
4. 发布新版本时：修改 `doudizhu/.codex-plugin/plugin.json` 的 `version` 并推送即可。

> 插件运行时零第三方依赖（仅 Python 3.7+ 标准库 + 浏览器），任何平台均可安装使用。

## 三、使用

在 Codex 中说：

> 玩斗地主 / 启动斗地主游戏

Codex 会运行 `python3 scripts/start_game.py`：

- **立即返回**（守护进程模式）：服务器在后台运行，浏览器自动打开（默认 `http://127.0.0.1:8765`）；
- 服务器**已运行**时再次启动，只会重新打开浏览器，不重复起服务；
- 停止服务器：`python3 scripts/stop_game.py`。

### 游戏操作

| 阶段 | 操作 |
| --- | --- |
| 叫地主 | 点「不叫 / 1分 / 2分 / 3分」（必须高于当前最高分） |
| 出牌 | 点击手牌选中（可多选）→ 点「出牌」；点「不出」过牌 |
| 提示 | 点「提示」让 AI 建议一种出法 |
| 设置 | 右上角「设置」：AI 出牌速度、记牌器开关、托管模式 |
| 重开 | 右上角「新一局」随时重开；结算后点「再来一局」 |

### 规则（完整标准规则）

- **叫地主**：轮流叫 1/2/3 分，必须高过当前最高分；两家不叫后叫分最高者当地主；三家都不叫则重新发牌。
- **牌型**：单张、对子、三张、三带一、三带二、顺子（≥5 张连续，不含 2 与王）、连对（≥3 对）、飞机（带单 / 带对）、四带二（带两张单或两对，不可带王炸）、炸弹、王炸。
- **大小**：同型比主牌大小；炸弹压一切普通牌型；王炸压一切。
- **翻倍**：每出一个炸弹 ×2、王炸 ×2；地主春天（农民未出牌）×2；农民反春（地主只出一手）×2。
- **结算**：底分 1 × 叫分 × 倍数。地主赢：每名农民输一份，地主得两份；农民赢则反之。
- **累计积分**：跨局累计，顶栏实时显示。

## 四、目录结构

```
doudizhu/                      # 插件根目录
├── .codex-plugin/plugin.json  # Codex 插件清单（官方规范）
├── skills/play-doudizhu/      # 技能：指导 Codex 启动游戏
├── scripts/
│   ├── start_game.py          # 守护进程式启动：后台起服务器 + 打开浏览器
│   ├── stop_game.py           # 停止服务器
│   └── make_icon.py           # 纯标准库生成插件图标 PNG
├── assets/                    # icon.png / logo.png（手绘生成）
└── game/                      # 游戏本体（全部 Python 标准库）
    ├── cards.py               # 54 张牌定义
    ├── rules.py               # 牌型识别与大小比较（100% 规则）
    ├── ai.py                  # 策略引擎：叫分 / 出牌 / 压牌 / 配合
    ├── engine.py              # 对局引擎：流程 / 计分 / 春天 / 快照
    ├── server.py              # HTTP 服务器：静态文件 + API + 机器人调度
    ├── index.html / css/ / js/   # 前端（SVG 手绘卡牌渲染）
tests/                         # 自动化测试
.agents/plugins/marketplace.json  # 仓库级市场文件（发布用）
install.sh / install_plugin.py # 个人安装脚本
```

## 五、技术架构

- **逻辑在服务端（Python 标准库）**：发牌、叫分、牌型判定、AI 决策、计分全部由服务器权威判定——可被单元测试完整覆盖。
- **前端只负责渲染**：浏览器每 400ms 轮询 `/api/state`，所有交互通过 `/api/action` 提交，服务端校验合法性并返回错误信息。
- **守护进程式启动**：`start_game.py` 启动后台服务器后立即返回，Codex 会话不被阻塞；重复启动自动复用；`stop_game.py` 一键停止。
- **机器人调度**：轮到 AI 时服务端按设置延迟自动出牌；刷新页面不丢牌局（状态保存在本地服务器）。
- **无任何第三方依赖**：运行时仅需 Python 3.7+ 与一个现代浏览器。

## 六、测试

```bash
python3 -m unittest discover -s tests -v   # 59 项：规则 / AI / 引擎 / 服务器 / 启动停止
osascript -l JavaScript tests/js_smoke.js  # 前端冒烟（JavaScriptCore 渲染全流程）
```

覆盖内容：全部牌型识别与比较、非法出牌拒绝、叫分流程、春天/反春/炸弹计分、
数百局 AI vs AI 全自动模拟（每步校验合法性、牌数守恒、得分守恒）、
HTTP API 端到端（含托管模式完整对局）、守护进程启动/复用/停止全流程、前端三阶段渲染冒烟。

## 七、常见问题

- **浏览器没自动打开**：手动访问终端输出的地址（默认 `http://127.0.0.1:8765`）。
- **页面卡住**：刷新浏览器即可，牌局状态在本地服务器，刷新不丢局。
- **端口被占用**：脚本会自动换端口，以实际输出为准。
- **想停止**：`python3 scripts/stop_game.py`。
- **重复启动**：`start_game.py` 检测到已有服务器时只重新打开浏览器，不会开第二个实例。

## 许可证

MIT
