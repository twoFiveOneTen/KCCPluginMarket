---
name: ios-gui-tester
description: "Takes a specified code change (a GitHub PR, uncommitted local edits, or a branch-to-branch diff), works out which user-visible behaviour it can affect, writes GUI test cases, waits for the user to approve them, then drives the iOS Simulator through the ios-simulator-skill scripts (accessibility-driven navigation, plus Claude Desktop's built-in simulator MCP for the live panel when available) to execute each case with screenshots as evidence, and writes a Markdown test report into the repo. Use this skill whenever the user wants a code change verified through the UI rather than through unit tests: '帮我 GUI 测一下这个 PR', '这次改动在模拟器上跑一遍', '生成 GUI 测试用例并执行', '这个分支的改动会影响哪些界面，测一测', '出个界面测试报告', 'run GUI tests for these changes', 'verify this on the simulator', or when they ask what a diff breaks on screen and want it actually clicked through. Also trigger when the user asks for regression testing of a change on an iPhone simulator, or for a test report of a PR's UI impact. Do NOT use for reading a diff and commenting on code quality (use pr-reviewer) or for writing XCTest unit tests."
---

# iOS GUI Tester

把一段代码改动，变成「在模拟器上真的点过一遍」的证据。

流程是：**备好工具** → 拿改动 → 分析影响范围 → 写用例 → **停下来等用户确认** → 构建装包 → 逐条执行留证据 → 出报告。

四条底线，先说清楚：

**用例没拿到用户明确同意，一步都不许往下走。** 写用例花几分钟，跑一轮要构建、装包、逐条点击，是几十倍的时间；方向错了这些全白花，而用户扫一眼用例表就能拦住。Step 4 末尾有一道必须走的确认关卡——**把用例贴出来不等于用户同意了**，贴完就开测是这个 skill 最常见的跑偏方式。

**模拟器的每一次交互都走 `ios-simulator-skill` 的脚本**，别自己拼 `idb ui tap`、也不要去开 Simulator.app 手动点。理由不只是统一：脚本按无障碍树语义定位、输出固定格式，每一步事后都能照着命令复核；手搓 idb 命令或者手动点，就是把现场变成黑箱。裸 `xcrun simctl` 只保留脚本确实够不着的那几件事（Step 5、Step 6 会点名），除此之外不扩大。

**影响范围不等于「改了哪些文件」。** diff 给的是文件，用户看到的是页面。改一个共用函数，diff 里只有那一处，但界面上受影响的可能有五个入口——**回归就漏在这里**。所以分析必须沿调用链往上走到用户摸得到的入口，再横向找出所有共用这段代码的老功能。

**报告里的每个「通过」都必须有当场看到的实据撑着。** GUI 测试最大的失效模式不是测出 bug，而是模型按「这么改了应该没问题」的推理写了一份全绿报告。你没点到的用例就写「阻塞」，测不了的改动就写「未覆盖」——一句诚实的「这块没测」比一条假绿用例值钱得多。

## Step 0 — 备好工具

主力是 **`ios-simulator-skill`**：一套 29 个命令行脚本，按无障碍树语义定位控件，全程用 Bash 调。先确认它在：

```bash
ls ~/.claude/skills/ios-simulator-skill/SKILL.md || echo "未安装，见下方安装流程"
```

下文一律把脚本目录写成 `$SKILL`。**每次跑 Bash 都是一个新 shell，变量不会留到下一条命令**，所以实际执行时要么每条命令前面带上 `SKILL=~/.claude/skills/ios-simulator-skill &&`，要么直接写全路径。忘了这件事的表现是 `python3 /scripts/navigator.py: No such file`——看到这个报错先回来看这一段，别去怀疑脚本装坏了。**会话里还有 Claude Desktop 内置模拟器 MCP**（工具名 `mcp__Claude_Code_iOS_Simulator__control` / `__build`）**时，它是脚本的补充，不是替代**。分工按下面三条走：

- **`control { action: "attach" }` 开实时面板**——用户能在自己屏幕上看着你点的每一下。脚本是 headless 的，这是它给不了的，有就一定要开，而且开在最前面。它的返回里有**这台设备的点尺寸**（如 `402x874 points`），记下来，后面从截图估坐标时要用。
- **`build` / `build_status` 构建**——省掉自己拼 `xcodebuild` 命令行（Step 5 两条路都写了）。
- **`touch_path` / `touch2_path` 做复杂手势**——曲线拖拽、长按后拖动、双指旋转。这几样 `gesture.py` 做不到（它只有固定的 `--pinch in/out`），拖拽排序、图片旋转缩放这类用例只能靠它。

**定位、点击、滑动、输入、判定这五件事走脚本**，因为它们要靠无障碍树。开工前先探一次内置 MCP 有没有树：

```
control { action: "inspect" }
```

报 `'inspect' is not available` 就是没有——那它的 `tap` 只能从截图估坐标，比脚本的语义定位低一档，别混用。真返回了树，说明这套环境的内置 MCP 支持了它，那它比脚本多一个能力：**`inspect` 带 `x`/`y` 可以查「某个坐标上是什么控件」**，正好补上脚本的缺口（见下面「做不到」表），Step 6 判定失败前的排查就用它。

脚本这条路整个断掉时（idb 环境坏了，`sim_health_check.sh` 也修不好），内置 MCP 是**独立的备用通道**：它不依赖 idb。这时可以降级用它的 `tap` / `swipe` / `text` 把这轮跑完，但必须做两件事——每点一下就截图确认真的点中了（坐标是估的，点空是静悄悄的），以及在报告「环境」栏写明本轮判定基于截图、可靠性低一档。别默不作声地降级。

这是本轮的能力边界，写用例（Step 4）时按它量力：

| 能做 | 怎么做 |
|---|---|
| 按文案/类型/ID 找控件，拿到 point 单位的 frame | `navigator.py --find-text/--find-exact/--find-type/--find-id` |
| 读整屏结构、列所有可点元素 | `screen_mapper.py` / `navigator.py --list` |
| 点击、长按、滑动、滚动、捏合、下拉刷新 | `navigator.py --tap`、`gesture.py` |
| 文本输入、特殊键、硬件键、清空输入框、收键盘 | `keyboard.py` |
| 装包、启动、冷启、卸载、深链、列已装应用 | `app_launcher.py` |
| 构建与跑测（渐进式报错） | `build_and_test.py` |
| 深色模式、动态字体档位、语言与地区 | `appearance.py` |
| 权限授予/撤销/重置（13 类） | `privacy_manager.py` |
| 注入定位、状态栏、推送、剪贴板 | `location.py`、`status_bar.py`、`push_notification.py`、`clipboard.py` |
| 查沙盒文件、UserDefaults、CoreData 库路径 | `container.py` |
| 抓日志、卡顿事件 | `log_monitor.py`、`hang_watcher.py` |
| 横竖屏旋转、摇一摇 | 脚本没封装，直接调底层的 `idb ui rotate` / `idb ui shake`。**注意横屏下只能读不能点**，见 Step 6「横竖屏」 |

| 脚本做不到 | 怎么办 |
|---|---|
| 曲线拖拽、长按后拖动、双指旋转 | 有内置 MCP 就用它的 `touch_path` / `touch2_path`；没有就归到「未覆盖」 |
| 查「某个坐标上是什么控件」 | 内置 MCP 的 `inspect { x, y }` 可用就用它；否则 `screen_mapper.py` 读整屏 + 截图比对 |
| 模拟内存警告 | 宿主菜单才有，写进用例前置条件请用户手动做 |
| 视觉 diff | `visual_diff.py` 依赖 Pillow，未装时 `pip3 install pillow` |

### 安装 ios-simulator-skill（没有时）

先把要做的事告诉用户——下载脚本包、装 Facebook IDB——**得到他同意再执行**。这会动他机器上的环境，不是你该自作主张的范围。

```bash
# 1. 脚本包
curl -L https://github.com/conorluddy/ios-simulator-skill/releases/latest/download/ios-simulator-skill.zip -o /tmp/ios-sim-skill.zip
mkdir -p ~/.claude/skills/ios-simulator-skill
unzip -q /tmp/ios-sim-skill.zip -d ~/.claude/skills/ios-simulator-skill

# 2. 前置：Facebook IDB。点击/输入/无障碍树全靠它，缺了整套交互脚本都会失败
which idb || (brew tap facebook/fb && brew install facebook/fb/idb-companion facebook/fb/idb-cli)

# 3. 体检：macOS、Xcode、simctl、idb、Python 3.12+、可用模拟器一次报全
bash ~/.claude/skills/ios-simulator-skill/scripts/sim_health_check.sh
```

以 `sim_health_check.sh` 的输出为准，缺哪样补哪样。两个常见告警可以先放过：Pillow 只影响 `visual_diff.py`，idb-companion「版本测不出」在 Xcode 26 上不影响使用。

**和 MCP 不同，脚本装完当场就能用，不需要重启会话**——`ls $SKILL/SKILL.md` 有输出就直接进 Step 1。

## Step 1 — 拿到改动

三种来源，用户给哪种用哪种；没说清就问，别猜：

```bash
# GitHub PR
gh pr diff <编号>
gh pr view <编号> --json title,body,headRefName,baseRefName,files

# 本地改动（含未提交）
git status && git diff HEAD

# 分支比较
git diff <base>...<head>          # 三点：只看 head 独有的改动
```

分支比较**务必用三个点**。两点 diff 会把 base 分支上别人的提交也算进来，影响范围凭空膨胀，测一堆跟这次改动无关的东西。

`gh` 报 TLS / 连接超时通常是它不读系统代理，前面加上再试：`HTTPS_PROXY=http://127.0.0.1:7890 gh pr diff <编号>`。

先 `--stat` 摸规模，再读关键 hunk。**光读 diff 不够**——diff 只带 3 行上下文，看不出这个函数被谁调用、改动前后的分支条件是什么。把改动涉及的文件整个读一遍，这是后面所有判断的地基。

## Step 2 — 摸清这个仓库怎么构建、怎么跑

每个 iOS 项目的 scheme、bundleId、构建方式都不一样，从仓库现场读，不要凭记忆写：

1. **`CLAUDE.md` / `README.md`** —— 构建命令、测试命令、已知的坑通常写在这儿，这是最权威的来源。
2. **scheme**：`xcodebuild -list -project <X>.xcodeproj`（有 `.xcworkspace` 就用 `-workspace`）
3. **bundleId**：`xcodebuild -showBuildSettings -scheme <S> -configuration Debug | grep PRODUCT_BUNDLE_IDENTIFIER` —— Debug 配置常带 `.debug` 后缀，用错了就是 launch 不起来或者启到了旧的 Release 包。
4. **模拟器**：用户指定了机型/系统版本就按他说的，没指定就用当前已启动的那台——`python3 $SKILL/scripts/sim_list.py` 看总览（哪台 booted、什么 iOS 版本），没有 booted 的用 `python3 $SKILL/scripts/simulator_selector.py --suggest` 挑一台。型号和 iOS 版本记下来，报告里要写。

   绝大多数脚本的 `--udid` 可以省，缺省就打给当前 booted 那台。但**落盘截图和多设备场景要完整 UDID**，而 `sim_list.py` 的总览是截断显示的，取完整值用：`xcrun simctl list devices | grep Booted`。

## Step 3 — 分析影响范围

这一步的产出是「哪些界面可能变了」，从三个方向找：

**纵向：改动点 → 用户入口。** grep 改动函数/属性的调用方，一路往上追到某个 ViewController 或页面，那才是用例的起点。追不到入口的改动，说明它可能根本不在 GUI 路径上——记下来，Step 4 归到「未覆盖」。

**横向：谁还在用这段代码。** 同一个函数的其他调用方就是回归面。这些老功能没人改，但可能被顺手改坏了，而且没人会想到去点它们。

**状态维度：改动依赖什么前置条件。** 空数据 / 有数据、首次安装 / 已有配置、权限已授 / 未授、深色模式、大字体档位、RTL 语言、iPad 与横屏——改动如果落在某个分支里，只在默认状态下点一遍是测不到的。

整理成表，Step 4 的用例直接从它长出来：

| 改动点 | 用户可见入口 | 预期行为变化 | 回归风险 |
|--------|-------------|-------------|---------|

**同时列出 GUI 测不了的部分。** 数据迁移、后台同步、纯算法、日志埋点这类界面上看不出差异的改动，写清楚为什么测不了，以及建议的替代验证方式——跑对应单测、补一条临时日志、或者请开发者本地核对落库数据。硬给它编一条 GUI 用例，只会产出一条无意义的绿灯。

## Step 4 — 写用例，等用户确认

用例要**能被机械执行**——写「点首页右下角的 + 按钮」，不是「新建一条回忆」；预期结果要**能被查证**——写「顶部出现『编辑』标题栏，右上角『完成』按钮为 enabled」，不是「进入编辑态」。含糊的用例执行时全靠临场发挥，等于没写。预期结果尽量写成无障碍树里查得到的东西（某个 label 出现/消失、某个按钮可点），这类判定是确定的；纯视觉的（布局错位、颜色、文字截断）才靠截图看。

| 编号 | 标题 | 类型 | 前置条件 | 操作步骤 | 预期结果 |
|------|------|------|---------|---------|---------|
| TC-01 | ... | 新功能/回归/边界 | ... | 1. ... 2. ... | ... |

优先级：改动主路径 > 回归面 > 边界与异常。**数量控制在 8~15 条**——每条用例在模拟器上都要真点一遍，写 40 条的结果是跑不完，最后靠脑补补齐。

**用例里出现中文输入的，现在就标出来。** 模拟器的文本输入对中文和 emoji 不一定吃得下（底层的 idb 输入通道对非 ASCII 字符不保证，Step 6 有绕法）。这在写用例阶段就该定下怎么办，不要等跑到一半才发现这条做不了。

### 确认关卡（不能跳）

把用例表和「未覆盖清单」贴给用户之后，**必须调用 `AskUserQuestion` 停下来**，等他真的回话：

```
问题："以上 N 条 GUI 用例，是否按这个方案在模拟器上执行？"
选项：
  - 按这个跑        → 进入 Step 5
  - 我要改用例      → 听他改完，改完再回到这一关重新问
  - 只跑其中几条    → 问清跑哪几条，其余标注为「本轮未执行」
```

为什么要用工具而不是写一句「请确认」：贴完用例接着往下写，模型自己很容易把「我已经展示过了」当成用户同意了，然后一路测到底——用户回过神来时机器已经点了二十分钟。`AskUserQuestion` 会真的把回合交还给用户，这是唯一可靠的刹车。

例外只有一个：用户在最开始就说了「分析完直接跑」「不用问我」。这时把用例表贴出来，然后直接进 Step 5。

## Step 5 — 把这次改动装进模拟器

**先把屏幕给用户看，再开始构建。** 有内置 MCP 就 `control { action: "attach" }`，没有就 `open -a Simulator`（Xcode 27 起改名 DeviceHub，`open -a Simulator` 会失败，直接跳过即可）。秒开，作用是让用户从构建阶段就盯着这块屏幕；你后面点的每一下他都在同一个窗口里看得到。跳过照样能跑，但用户就全盲了，出问题没法跟你对齐现场。没有已启动的模拟器时 `attach` 会直接报错——先 boot 再 attach：

```bash
python3 $SKILL/scripts/simctl_boot.py --name "iPhone 17 Pro" --wait-ready
```

**构建有两条路，会话里有内置 MCP 就走 A，否则走 B。**

**A · 内置 MCP 构建**——它的 `build_status` 直接返回 `.app` 路径，省掉自己找产物：

```
1. build { action: "build", project_path 或 workspace_path（绝对路径）,
           scheme, configuration: "Debug", device: "<机型或 UDID>" }   # 立即返回 build_id
2. build { action: "build_status", build_id }        # 轮询到成功，拿 .app 路径与编译错误
```

**B · 脚本构建**——`build_and_test.py` 的报错是渐进式的，默认只回一行摘要，要细节再按 xcresult ID 取：

```bash
# 构建；有 .xcworkspace 就把 --project 换成 --workspace
python3 $SKILL/scripts/build_and_test.py \
  --project <绝对路径>.xcodeproj --scheme <S> --configuration Debug --simulator "iPhone 17 Pro"
# → Build: SUCCESS (0 errors, 3 warnings) [xcresult-20260918-143052]

# 失败时按返回的 ID 取详情，不要一上来就 --verbose 把整个构建日志灌进上下文
python3 $SKILL/scripts/build_and_test.py --get-errors <xcresult-id>
```

**`build_and_test.py` 不会告诉你 `.app` 在哪，也不接受 `-derivedDataPath`**，产物落在 Xcode 默认 DerivedData 里。装包前先把路径查出来（`-showBuildSettings` 只读配置，不会真的构建）：

```bash
APP_DIR=$(xcodebuild -project <绝对路径>.xcodeproj -scheme <S> -configuration Debug \
  -destination "platform=iOS Simulator,id=<UDID>" -showBuildSettings 2>/dev/null \
  | awk -F' = ' '/ BUILT_PRODUCTS_DIR /{print $2; exit}')
ls "$APP_DIR"/*.app
```

嫌这一步绕，就直接用 `xcodebuild ... -derivedDataPath /tmp/gui-test-build build` 自己构建，产物固定落在 `/tmp/gui-test-build/Build/Products/Debug-iphonesimulator/<App>.app`——代价是编译报错要自己从满屏输出里捞。

**装包启动，两条路共用：**

```bash
python3 $SKILL/scripts/app_launcher.py --install "<.app 绝对路径>"
python3 $SKILL/scripts/app_launcher.py --launch "<bundleId>"
```

构建失败先把完整报错给用户看（路径 A 的报错在 `build_status` 里，路径 B 用 `--get-errors`），不要自己改工程配置去凑编过——那已经不是 GUI 测试的范围了。

**多台模拟器同时开着时，每条脚本命令都显式带 `--udid`。** 这个参数缺省就打给「当前 booted」那台；开了两台就成了随机赌博，点到隔壁机器上还会得出一条莫名其妙的失败。只有一台时可以省。

脚本报错时**把错误原样告诉用户，停在这儿等他处理**。交互类脚本（`navigator.py` / `gesture.py` / `keyboard.py`）的报错基本都是 idb 环境问题——先跑一次 `bash $SKILL/scripts/sim_health_check.sh` 定位是哪一环。两个高频故障记住就行：读得到无障碍树但点击/输入全无反应，是 idb-companion 版本太老（Xcode 27 需要 ≥ 1.5.1，`brew upgrade facebook/fb/idb-companion`）；每条 idb 调用都报 `Connection refused`，是死掉的 companion 还挂在注册表里，`idb disconnect <UDID>` 清掉。多数环境问题需要用户输密码才能修，绕过去只是把问题推迟到更难查的地方。

**装完先确认装的是这次改动的包**：`python3 $SKILL/scripts/app_launcher.py --list | grep <bundleId>` 看在不在，再 `python3 $SKILL/scripts/screen_mapper.py` 在界面上找到这次改动引入的可见元素，或者核对 `.app` 的时间戳晚于构建开始时刻。测了半天旧包全绿是这类工作最尴尬的失败方式，而这一步只要十秒。

要验「首次安装」态（UserDefaults 回默认）时，卸载重装一行就够：

```bash
python3 $SKILL/scripts/app_launcher.py --uninstall <bundleId>
python3 $SKILL/scripts/app_launcher.py --install "<.app 绝对路径>"
```

## Step 6 — 逐条执行，边跑边留证据

命令对照表，`SKILL=~/.claude/skills/ios-simulator-skill`，所有脚本都支持 `--json` 和 `--udid`：

| 要做的事 | 命令 |
|---------|------|
| 按文案找控件（模糊 / 精确 / 按类型 / 按 ID） | `navigator.py --find-text "新建"` ·`--find-exact` ·`--find-type Button` ·`--find-id` |
| 读整屏结构 / 列所有可点元素 | `screen_mapper.py` · `navigator.py --list` |
| 找到并点击（一步到位，不用手算坐标） | `navigator.py --find-text "新建" --tap` |
| 同名控件有多个时选第几个 | `navigator.py --find-text "删除" --index 1 --tap` |
| 按坐标点击（找不到控件时的兜底） | `navigator.py --tap-at "180,420"` |
| 长按 | `gesture.py --long-press "180,420" --duration 1.0` |
| 方向滑动 / 滚动 / 拨开关 | `gesture.py --swipe up` · `--scroll down --scroll-amount 3` · `--swipe-from "300,500" --swipe-to "200,500"` |
| 捏合缩放 / 下拉刷新 | `gesture.py --pinch in\|out` · `gesture.py --refresh` |
| 曲线拖拽 / 长按后拖 / 双指旋转 | 脚本没有，用内置 MCP 的 `control { action: "touch_path" \| "touch2_path" }` |
| 输入文本 | `navigator.py --find-type TextField --enter-text "abc"` · `keyboard.py --type "abc"` |
| 清空输入框 / 收起键盘 / 特殊键 | `keyboard.py --clear` · `--dismiss` · `--key return` |
| 按 Home / 锁屏等硬件键 | `keyboard.py --button home\|lock\|volume-up` |
| 深链直达某页 | `app_launcher.py --open-url "myapp://..."` |
| 用例间复位（冷启） | `app_launcher.py --restart <bundleId>` |
| 看一眼当前屏幕 / 存证截图落盘 | `xcrun simctl io <UDID> screenshot "<绝对路径>.png"` |
| 整轮录屏（可选） | `xcrun simctl io <UDID> recordVideo "<路径>.mp4"`，`Ctrl-C` 停 |

**截图和录屏是脚本够不着的那两件事**，直接用 `simctl`。skill 没有独立的截图脚本——`app_state_capture.py` 会连日志和层级一起抓，是出 bug 报告用的重家伙，不要拿它当截图工具。**`output_path` 一律给绝对路径。**

前置状态不用再去点「设置」App，一行命令搞定，这些在 Step 3 的「状态维度」里列出来的分支终于能真的测到：

| 要造的状态 | 命令 |
|---|---|
| 深色 / 浅色模式 | `appearance.py --theme dark` |
| 动态字体档位（XS…AX5） | `appearance.py --text-size XXL --bundle-id <bundleId>` |
| 语言与地区（含 RTL，ar/he/fa/ur 自动标记） | `appearance.py --locale ar --region SA --bundle-id <bundleId>` |
| 一键还原以上三项 | `appearance.py --reset` |
| 权限授予 / 撤销 / 重置（13 类服务） | `privacy_manager.py --bundle-id <X> --grant location,photos` |
| 注入经纬度 / 城市 / 轨迹回放 | `location.py --lat 39.9 --lng 116.4` · `--city beijing` · `--gpx "City Run"` |
| 干净状态栏（9:41、满电、满格） | `status_bar.py --preset clean` |
| 发一条推送 | `push_notification.py --bundle-id <X> --title "..." --body "..."` |
| 往剪贴板塞内容测粘贴 | `clipboard.py --copy "测试文本"` |
| 横竖屏旋转（转完只能读，不能点） | `idb ui rotate LANDSCAPE_LEFT --udid <UDID>`（见下方「横竖屏」） |
| 摇一摇（触发撤销弹窗等） | `idb ui shake --udid <UDID>` |

`--bundle-id` 给了就会自动重启 App 让设置生效，别自己再补一次冷启。

判不准「是功能坏了还是没写进库」时，直接查落库数据和日志，比在界面上反复点有效：

```bash
python3 $SKILL/scripts/container.py --userdefaults <bundleId>     # UserDefaults 全量（bundleId 是这个 flag 的值）
python3 $SKILL/scripts/container.py --core-data-path <bundleId>   # CoreData .sqlite 路径，拿到后可直接 sqlite3 查
python3 $SKILL/scripts/container.py --ls <bundleId> Documents     # 翻沙盒文件
python3 $SKILL/scripts/log_monitor.py --app <bundleId> --severity error --duration 30s
```

每条用例按步骤驱动，关键节点确认真实界面，并**在看到的当下就把它写成一行观察记录**（`TC-01 步骤3：顶部出现「编辑」标题栏，右上角「完成」为 enabled，正文区 3 行文本`）。报告里「实际结果」一栏只能从这些当场记录里长出来，攒到最后再回忆必然失真。

几个实操要点：

- **优先用 `--find-text ... --tap`，让坐标根本不出现。** 脚本自己查树、自己算中心点、自己点下去，这一路没有你估错的余地。找不到再退回 `screen_mapper.py` 通读结构换个文案试，最后才用 `--tap-at` 硬点坐标。
- **万不得已从截图上量坐标，别手算换算**，交给脚本：截图是像素图（iPhone 2x/3x），点击吃的是 point，直接喂必偏。
  ```bash
  python3 $SKILL/scripts/navigator.py --tap-at "360,840" \
    --screenshot-coords --screenshot-width 1179 --screenshot-height 2556
  ```
  `gesture.py` 的 `--swipe-from/--swipe-to` 同样支持这三个参数。硬点完一定截一张图确认真的点中了再往下走。
- **判定优先看无障碍树。** 「按钮变可点」「标题变成 X」「列表多了一行」在 `screen_mapper.py` / `navigator.py --find-text` 里是确定的事实；截图留给视觉类判定（布局错位、颜色、文字截断、图片没加载）。两者都留一份最好：树用来判定，图用来存证。树里查不到的东西，判定就明确写成「截图上看到…」，别把看图的结论包装成确定事实。
- **每一步都重新查树，别缓存上一步的 frame。** 界面一变坐标就废了。用 `--find-text --tap` 时这是自动的，用 `--tap-at` 时得自己守住。
- **中文输入。** 底层 idb 的输入通道对非 ASCII 不保证，中文和 emoji 可能整段吞掉或只进去一半。先试一次 `keyboard.py --type`，进去了就正常测。真输不进去时按优先级绕：换成 ASCII 测试数据（只要用例验的不是中文本身）→ `clipboard.py --copy "中文"` 再在输入框长按粘贴 → `app_launcher.py --open-url` 带参数深链把数据灌进去 → 请用户手动敲一次。都不行就把这条记为「未覆盖」并写明原因，**不要硬试出一条假失败**。
- **点击拨不动的控件（开关类常见）改用滑动**：`gesture.py --swipe-from "340,220" --swipe-to "310,220"`（关：从右往左约 30pt）。
- **自定义坐标滑动别贴着屏幕边起手。** 起点落在离边缘几个点以内时，走的是系统边缘手势——左边=返回、上边=通知中心、下边=home/多任务、右边=控制中心，不是你要的那次列表滚动。贴边元素往里挪几个点再起手。`gesture.py --swipe up/down/left/right` 和 `--scroll` 是封装好的安全区滑动，能用就用它们，别自己拼坐标。
- **判成失败之前，先排除是自己点错了。** 内置 MCP 的 `inspect { x, y }` 可用时，直接查刚才那个坐标上到底是什么控件，一步定论；不可用就靠 `screen_mapper.py` 重读一遍整屏 + 截一张图：确认界面有没有停在上一步、有没有弹窗/键盘挡住。功能真坏了 / 流程没走到那一步 / 我点歪了——把第三种写成 bug，会浪费开发者半天时间去查一个不存在的问题。
- **卡住最多重试两次**，然后记为「阻塞」并写清卡在哪一步、当时屏幕上是什么，继续下一条。一条用例死磕到底会拖垮整轮，而它本身往往只是个定位问题。
- **用例之间复位状态**：`app_launcher.py --restart <bundleId>` 冷启一次，比从当前页面一层层退回去可靠，也避免上一条用例的残留状态污染下一条。

需要特定前置状态时，**先查上面那张状态表有没有对应脚本**——深色模式、字体档位、语言地区、权限、定位、推送、剪贴板都是一行命令，比在「设置」App 里点十几下可靠得多，也不会因为设置页改版就失效。表里没有的才点过去。App 内的深层页面用 `app_launcher.py --open-url` 走 URL Scheme 直达，省掉一串导航点击，也少一串出错机会。

### 横竖屏

`gesture.py` 没封装旋转，但它底层的 `idb` 有，直接调即可——横屏用例**不用**请用户手动按 Cmd+→：

```bash
idb ui rotate LANDSCAPE_LEFT --udid <UDID>
# 四个方向：PORTRAIT | PORTRAIT_UPSIDE_DOWN | LANDSCAPE_LEFT | LANDSCAPE_RIGHT
```

**别用截图尺寸判断转没转，会得出完全相反的结论。** `xcrun simctl io screenshot` 输出的**永远是设备原生方向的帧缓冲**：转到横屏后，截图尺寸一个像素都不变（还是 1206×2622），只有图里的内容是侧过来的。照尺寸判断会把一次成功的旋转判成「命令静默失败」。

可靠的判定是看无障碍树的坐标范围——横屏后元素的 x 会超出竖屏宽度：

```bash
python3 $SKILL/scripts/navigator.py --list | grep -oE '\([0-9]+, [0-9]+\)'
# iPhone 17 Pro 为例（402×874 点）：竖屏元素 x 上限 ~359，横屏能到 ~780
```

**横屏下只能读，不能点——这是硬约束，写用例时就要认。** 转到横屏后，无障碍树返回的是横屏坐标，但 idb 的输入通道仍停在竖屏坐标系，两边对不上：树说 `(150,42)` 是「Bookmarks」，按这个坐标查下去实际是竖屏布局里的灵动岛。后果是 `--find-text --tap` 会**若无其事地报告 `Tapped: Button "..."`，而屏幕纹丝不动**。两个方向（`LANDSCAPE_LEFT` / `LANDSCAPE_RIGHT`）都一样，换旋转方式（`idb` 还是宿主菜单）也一样。

所以横屏用例只写**读取类验证**：布局有没有错位、安全区有没有被刘海压住、可读宽度对不对、文字有没有截断。这恰好是横屏回归真正要看的东西。判定用 `screen_mapper.py` 读树 + 截图看版式，两者在横屏下都是准的。

```bash
idb ui rotate LANDSCAPE_LEFT --udid <UDID>    # 转横屏
python3 $SKILL/scripts/screen_mapper.py       # 读树：准
xcrun simctl io <UDID> screenshot <path>      # 截图：内容是横的，准
idb ui rotate PORTRAIT --udid <UDID>          # 转回竖屏，点击能力立刻恢复
```

**要在横屏下继续点，只能先转回竖屏**——不需要重启模拟器（转回去坐标系当场就恢复了）。真需要「横屏 + 点击」的用例，把它拆成「竖屏点到那个状态 → 转横屏 → 只看布局」，或者归到「未覆盖」。

**每条横屏用例跑完必须转回竖屏**，否则方向会泄漏到下一条用例，而下一条会在毫无征兆的情况下点不动任何东西——这个现象极像 App 卡死，很容易被误写成 bug。

App 自己锁了方向时（iPhone 上的「设置」就锁竖屏），转了也不会变——这时看到的「没生效」是 App 的正常行为，不是工具问题。判断依据仍是上面那条坐标范围。

## Step 7 — 出报告

写到被测仓库的 `gui-test-reports/<YYYYMMDD-HHmm>-<改动简述>.md`，这样报告能直接贴进 PR 或留档。目录还没被 `.gitignore` 收编时提醒用户一句，是否入库由他定。

存证图落到报告同目录的 `screenshots/` 下，报告里用相对路径引用，但 `xcrun simctl io <UDID> screenshot` 的落盘路径**必须给绝对路径**。每条用例至少留一张关键节点的图；失败的用例把出问题那一屏留下来，这是开发者复现的起点。

证据以 Step 6 的当场观察记录为主——每一步写清屏幕上**实际**是什么，而不是「符合预期」。

```markdown
# GUI 测试报告 — <改动标识>

| 项 | 内容 |
|----|------|
| 被测改动 | PR #123 / 本地未提交改动 / `release-x`...`dev-y` |
| 构建 | scheme `<S>` · Debug · commit `<短 sha>` |
| 环境 | iPhone 17 Pro · iOS 26.0 · <ios-simulator-skill（无障碍树判定）/ 内置 MCP 降级（判定基于截图，可靠性低一档）> · <实时面板已开> |
| 执行时间 | 2026-09-04 15:20 ~ 15:48 |
| 结论 | 通过 8 · 失败 2 · 阻塞 1 · 未覆盖 3 |

## 一、影响范围分析
| 改动点 | 用户可见入口 | 预期行为变化 | 回归风险 |

### GUI 未覆盖的改动
| 改动点 | 为什么 GUI 测不了 | 建议验证方式 |

## 二、执行结果总览
| 编号 | 标题 | 类型 | 结果 | 说明 |
| TC-01 | ... | 新功能 | ✅ 通过 | |
| TC-02 | ... | 回归 | ❌ 失败 | 见问题 1 |
| TC-03 | ... | 边界 | ⚠️ 阻塞 | 步骤 3 无法进入该页面 |

## 三、用例详情
### TC-01 <标题> ✅
- **前置条件**：...
- **步骤与实际**：1. 点首页右下角 + → 进入编辑页，顶部为「新建回忆」…… 2. ……
- **预期**：... / **实际**：<屏幕上实际是什么，不是「符合预期」>
- **截图**：![](screenshots/TC-01-step3.png)

## 四、发现的问题
### 问题 1：<一句话描述现象>
- **复现步骤**：...
- **现象**：<屏幕上实际看到什么> ![](screenshots/TC-02-fail.png)
- **期望**：...
- **关联改动**：`path/to/File.swift:88`，本次 diff 中的 <哪一处>
- **补充**：<排除「点错了」的依据、复现是否稳定、几次里出现几次>

## 五、结论与建议
<能不能合；哪些问题必须先修；哪些改动建议补单测而不是 GUI 覆盖>
```

结论要给得干脆——**这次改动能不能合**，以及卡在哪儿。用户找你做 GUI 测试，最终要的是这个判断，不是一张表格。
