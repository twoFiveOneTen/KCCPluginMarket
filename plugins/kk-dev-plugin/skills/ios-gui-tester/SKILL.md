---
name: ios-gui-tester
description: "Takes a specified code change (a GitHub PR, uncommitted local edits, or a branch-to-branch diff), works out which user-visible behaviour it can affect, writes GUI test cases, waits for the user to approve them, then drives the iOS Simulator through the ios-simulator-mcp MCP server to execute each case with screenshots as evidence, and writes a Markdown test report into the repo. Use this skill whenever the user wants a code change verified through the UI rather than through unit tests: '帮我 GUI 测一下这个 PR', '这次改动在模拟器上跑一遍', '生成 GUI 测试用例并执行', '这个分支的改动会影响哪些界面，测一测', '出个界面测试报告', 'run GUI tests for these changes', 'verify this on the simulator', or when they ask what a diff breaks on screen and want it actually clicked through. Also trigger when the user asks for regression testing of a change on an iPhone simulator, or for a test report of a PR's UI impact. Do NOT use for reading a diff and commenting on code quality (use pr-reviewer) or for writing XCTest unit tests."
---

# iOS GUI Tester

把一段代码改动，变成「在模拟器上真的点过一遍」的证据。

流程是：**备好模拟器 MCP** → 拿改动 → 分析影响范围 → 写用例 → **停下来等用户确认** → 构建装包 → 逐条执行留证据 → 出报告。

四条底线，先说清楚：

**用例没拿到用户明确同意，一步都不许往下走。** 写用例花几分钟，跑一轮要构建、装包、逐条点击，是几十倍的时间；方向错了这些全白花，而用户扫一眼用例表就能拦住。Step 4 末尾有一道必须走的确认关卡——**把用例贴出来不等于用户同意了**，贴完就开测是这个 skill 最常见的跑偏方式。

**模拟器的每一次交互都走 `ios-simulator-mcp`**（工具名形如 `mcp__ios-simulator__ui_tap`）。不要用 `xcrun simctl` 敲点击、也不要去开 Simulator.app 自己点。理由不只是统一：这套工具能读到无障碍树（`ui_find_element` / `ui_describe_all`），控件位置和状态是**查出来的**，不是从截图上肉眼估的——这是 GUI 自动化里判定可靠与不可靠的分界线。命令行只保留两处 MCP 确实够不着的事（构建、boot 指定机型），Step 5 会点名，除此之外绕到命令行就是把用户能复核的现场变成黑箱。

**影响范围不等于「改了哪些文件」。** diff 给的是文件，用户看到的是页面。改一个共用函数，diff 里只有那一处，但界面上受影响的可能有五个入口——**回归就漏在这里**。所以分析必须沿调用链往上走到用户摸得到的入口，再横向找出所有共用这段代码的老功能。

**报告里的每个「通过」都必须有当场看到的实据撑着。** GUI 测试最大的失效模式不是测出 bug，而是模型按「这么改了应该没问题」的推理写了一份全绿报告。你没点到的用例就写「阻塞」，测不了的改动就写「未覆盖」——一句诚实的「这块没测」比一条假绿用例值钱得多。

## Step 0 — 确认 ios-simulator-mcp 在位

先看当前会话的工具列表里有没有 `mcp__ios-simulator__*`（例如 `mcp__ios-simulator__get_booted_sim_id`）。**有就直接进 Step 1**，别多跑一遍安装检查。

没有的话，先把要做的事告诉用户——装 Facebook IDB（Homebrew + pipx）、把 MCP server 注册进 Claude Code——**得到他同意再执行**。这两条会动他机器上的环境，不是你该自作主张的范围。

```bash
# 1. 前置：Facebook IDB。ios-simulator-mcp 的点击/输入/无障碍树全靠它，缺了整套 ui_* 都会失败
which idb || (brew tap facebook/fb && brew install idb-companion && pipx install fb-idb)

# 2. 注册 MCP server（-s user：GUI 测试是跨项目的需求，装在用户级省得每个仓库再装一次）
claude mcp add ios-simulator -s user -- npx -y ios-simulator-mcp

# 3. 确认写进去了
claude mcp list
```

前置还需要 Node 20+、macOS、装好 Xcode 与 iOS 模拟器；缺哪样报错会直说，照报错补。IDB 的安装步骤以官方文档 <https://fbidb.io/docs/installation> 为准，上面这条命令跑不通就去看它，别自己试别的包名。

**装完必须重启 Claude Code 会话，这一轮拿不到新工具。** MCP 工具是会话启动时加载的，`claude mcp add` 成功不等于当前对话里能调。所以装完就**停在这里**，告诉用户重启会话后重新发起这次 GUI 测试——不要因为「已经装好了」就退回 `xcrun simctl` 硬把这轮跑完，那正是这个 skill 要避免的黑箱。

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
4. **模拟器**：用户指定了机型/系统版本就按他说的，没指定就用当前已启动的那台（`get_booted_sim_id`）。型号和 iOS 版本记下来，报告里要写。

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

**用例里出现中文输入的，现在就标出来。** `ui_type` 只接受 ASCII 可打印字符，中文和 emoji 输不进去（Step 6 有绕法）。这在写用例阶段就该定下怎么办，不要等跑到一半才发现这条做不了。

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

五步，构建之外全是 MCP：

```
1. mcp__ios-simulator__open_simulator      # 打开 Simulator.app，用户在自己屏幕上看得见
2. mcp__ios-simulator__get_booted_sim_id   # 拿 UDID，后面构建和装包都要用
3. xcodebuild ...                          # 构建（MCP 不做构建，见下）
4. mcp__ios-simulator__install_app   { app_path: "<.app 绝对路径>" }
5. mcp__ios-simulator__launch_app    { bundle_id: "<bundleId>", terminate_running: true }
```

**`open_simulator` 不要省，而且放在最前面。** 它秒开，作用是让用户从构建阶段就盯着这块屏幕；你后面点的每一下他都在同一个窗口里看得到。跳过它照样能跑（idb 直接驱动已启动的模拟器），但用户就全盲了，出问题没法跟你对齐现场。

**MCP 够不着的只有两件事**，用命令行补，别扩大：

```bash
# ① boot 指定机型（get_booted_sim_id 返回空，或启着的不是用户要的机型时）
xcrun simctl list devices available | grep "iPhone 17 Pro"
xcrun simctl boot <UDID>

# ② 构建（ios-simulator-mcp 只负责模拟器，不负责编译）
xcodebuild -project <绝对路径>.xcodeproj -scheme <S> -configuration Debug \
  -destination "platform=iOS Simulator,id=<UDID>" \
  -derivedDataPath /tmp/gui-test-build build
# 有 .xcworkspace 就把 -project 换成 -workspace
# 产物：/tmp/gui-test-build/Build/Products/Debug-iphonesimulator/<App>.app
```

构建失败先把完整报错给用户看，不要自己改工程配置去凑编过——那已经不是 GUI 测试的范围了。

**多台模拟器同时开着时，每个 MCP 调用都显式传 `udid`。** 所有工具的 `udid` 都是可选的，不传就打给「当前 booted」那台；开了两台就成了随机赌博，点到隔壁机器上还会得出一条莫名其妙的失败。只有一台时可以省。

MCP 报错时**把错误原样告诉用户，停在这儿等他处理**。`idb` 相关的报错基本都是环境问题（IDB 没装好、companion 没起来、Xcode 没选对、模拟器没授权），多数需要用户输密码才能修，绕过去只是把问题推迟到更难查的地方。

**装完先确认装的是这次改动的包**：`list_apps` 看 bundleId 在不在，再 `ui_view` 截一眼，在界面上找到这次改动引入的可见元素，或者核对 `.app` 的时间戳晚于构建开始时刻。测了半天旧包全绿是这类工作最尴尬的失败方式，而这一步只要十秒。

要验「首次安装」态（UserDefaults 回默认）时，MCP 没有卸载动作：在主屏用 `ui_tap` 给图标一个 `duration: "1.0"` 的长按进抖动态删掉，或者请用户跑一句 `xcrun simctl uninstall <UDID> <bundleId>`，然后重新 `install_app` + `launch_app`。

## Step 6 — 逐条执行，边跑边留证据

工具对照表，照着挑：

| 要做的事 | 工具 |
|---------|------|
| 按文案找控件、拿坐标 | `ui_find_element { search: ["新建"], type: "Button" }` |
| 读整屏结构 | `ui_describe_all` |
| 查某个坐标上是什么控件 | `ui_describe_point { x, y }` |
| 看一眼当前屏幕 | `ui_view`（压缩图，回到对话里） |
| 存证截图 | `screenshot { output_path: "<绝对路径>.png" }` |
| 点击 / 长按 | `ui_tap { x, y, duration? }` |
| 滑动 / 滚动 / 拨开关 | `ui_swipe { x_start, y_start, x_end, y_end, delta? }` |
| 输入文本（仅 ASCII） | `ui_type { text }` |
| 深链直达某页 | `open_url { url: "myapp://..." }` |
| 用例间复位 | `launch_app { bundle_id, terminate_running: true }` |
| 整轮录屏（可选） | `record_video` / `stop_recording` |

每条用例按步骤驱动，关键节点确认真实界面，并**在看到的当下就把它写成一行观察记录**（`TC-01 步骤3：顶部出现「编辑」标题栏，右上角「完成」为 enabled，正文区 3 行文本`）。报告里「实际结果」一栏只能从这些当场记录里长出来，攒到最后再回忆必然失真。

几个实操要点：

- **定位优先用 `ui_find_element`，不要从截图上肉眼估坐标。** 它返回的 frame 已经是 point 单位，中心点 `(x + width/2, y + height/2)` 直接喂给 `ui_tap`。截图是像素图（iPhone 是 2x/3x），拿截图像素当坐标点必偏——这是 GUI 自动化最常见的错误来源。找不到元素时才退回 `ui_describe_all` 通读结构，再不行才目测。
- **判定优先看无障碍树。** 「按钮变可点」「标题变成 X」「列表多了一行」在 `ui_describe_all` / `ui_find_element` 里是确定的事实；截图留给视觉类判定（布局错位、颜色、文字截断、图片没加载）。两者都留一份最好：树用来判定，图用来存证。
- **点之前先确认当前在哪一屏。** 界面一变坐标就废了，上一步的 frame 不能拿到下一步用。
- **`ui_type` 只吃 ASCII 可打印字符**，中文和 emoji 输不进去。绕法按优先级：换成 ASCII 测试数据（只要用例验的不是中文本身）→ 用 `open_url` 带参数深链把数据灌进去 → 请用户手动敲一次那段中文。都不行就把这条记为「未覆盖」并写明原因，**不要硬试出一条假失败**。
- **`ui_tap` 拨不动的控件（开关类常见）改用 `ui_swipe`** 在控件上横划（关：从右往左约 30pt）。
- **判成失败之前，先排除是自己点错了。** 用 `ui_describe_point` 查一下刚才那个坐标上到底是什么控件，再确认界面有没有停在上一步、有没有弹窗/键盘挡住。功能真坏了 / 流程没走到那一步 / 我点歪了——把第三种写成 bug，会浪费开发者半天时间去查一个不存在的问题。
- **卡住最多重试两次**，然后记为「阻塞」并写清卡在哪一步、当时屏幕上是什么，继续下一条。一条用例死磕到底会拖垮整轮，而它本身往往只是个定位问题。
- **用例之间复位状态**：`launch_app { terminate_running: true }` 一次冷启，比从当前页面一层层退回去可靠，也避免上一条用例的残留状态污染下一条。

需要特定前置状态时，能在 App 里或系统「设置」里点到的就点过去——语言与地区、通知与定位权限、深色模式、文字大小都在设置 App 中，`ui_find_element` + `ui_tap` 点得到；App 内的深层页面用 `open_url` 走 URL Scheme 直达，省掉一串导航点击，也少一串出错机会。

模拟器宿主菜单才能做的事（注入具体经纬度、摇一摇、模拟内存警告）这套工具够不着，**别为此绕到别的操作方式**：把它写进用例的前置条件请用户手动设一次，或者归到「未覆盖」并注明原因。少测一条并说明，好过为了跑通而换一套用户看不见的操作方式。

## Step 7 — 出报告

写到被测仓库的 `gui-test-reports/<YYYYMMDD-HHmm>-<改动简述>.md`，这样报告能直接贴进 PR 或留档。目录还没被 `.gitignore` 收编时提醒用户一句，是否入库由他定。

`screenshot` 的 `output_path` 直接给报告同目录 `screenshots/` 下的**绝对路径**（相对路径会落到 `~/Downloads` 或 `IOS_SIMULATOR_MCP_DEFAULT_OUTPUT_DIR`，不是你以为的地方），报告里用相对路径引用。每条用例至少留一张关键节点的图；失败的用例把出问题那一屏留下来，这是开发者复现的起点。

证据以 Step 6 的当场观察记录为主——每一步写清屏幕上**实际**是什么，而不是「符合预期」。

```markdown
# GUI 测试报告 — <改动标识>

| 项 | 内容 |
|----|------|
| 被测改动 | PR #123 / 本地未提交改动 / `release-x`...`dev-y` |
| 构建 | scheme `<S>` · Debug · commit `<短 sha>` |
| 环境 | iPhone 17 Pro · iOS 26.0 · ios-simulator-mcp |
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
