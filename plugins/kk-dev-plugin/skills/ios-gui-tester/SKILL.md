---
name: ios-gui-tester
description: "Takes a specified code change (a GitHub PR, uncommitted local edits, or a branch-to-branch diff), works out which user-visible behaviour it can affect, writes GUI test cases, waits for the user to approve them, then drives the iOS Simulator to execute each case with screenshots as evidence, and writes a Markdown test report into the repo. Use this skill whenever the user wants a code change verified through the UI rather than through unit tests: '帮我 GUI 测一下这个 PR', '这次改动在模拟器上跑一遍', '生成 GUI 测试用例并执行', '这个分支的改动会影响哪些界面，测一测', '出个界面测试报告', 'run GUI tests for these changes', 'verify this on the simulator', or when they ask what a diff breaks on screen and want it actually clicked through. Also trigger when the user asks for regression testing of a change on an iPhone simulator, or for a test report of a PR's UI impact. Do NOT use for reading a diff and commenting on code quality (use pr-reviewer) or for writing XCTest unit tests."
---

# iOS GUI Tester

把一段代码改动，变成「在模拟器上真的点过一遍」的证据。

流程是：拿改动 → 分析影响范围 → 写用例 → **停下来等用户确认** → 装包 → 逐条执行留证据 → 出报告。

四条底线，先说清楚：

**用例没拿到用户明确同意，一步都不许往下走。** 写用例花几分钟，跑一轮要构建、装包、逐条点击，是几十倍的时间；方向错了这些全白花，而用户扫一眼用例表就能拦住。Step 4 末尾有一道必须走的确认关卡——**把用例贴出来不等于用户同意了**，贴完就开测是这个 skill 最常见的跑偏方式。

**模拟器一律用 Claude Desktop 自带的 iOS 模拟器工具驱动**（`mcp__Claude_Code_iOS_Simulator__build` / `control`）。不要用 `xcrun simctl` 命令行，也不要去开 Simulator.app 自己点：走 MCP 时 `attach` 出来的面板是用户实时看得见的，你点了什么、界面怎么变，他和你看的是同一块屏幕；绕到命令行他就全盲了，出问题也没法跟你对齐现场。

**影响范围不等于「改了哪些文件」。** diff 给的是文件，用户看到的是页面。改一个共用函数，diff 里只有那一处，但界面上受影响的可能有五个入口——**回归就漏在这里**。所以分析必须沿调用链往上走到用户摸得到的入口，再横向找出所有共用这段代码的老功能。

**报告里的每个「通过」都必须有当场看到的实据撑着。** GUI 测试最大的失效模式不是测出 bug，而是模型按「这么改了应该没问题」的推理写了一份全绿报告。你没点到的用例就写「阻塞」，测不了的改动就写「未覆盖」——一句诚实的「这块没测」比一条假绿用例值钱得多。

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
4. **模拟器**：MCP 的 `device` 参数收型号名（`"iPhone 17 Pro"`），不传就用当前已附加或已启动的那台。用户指定了机型/系统版本就按他说的，没指定就用默认那台，型号和 iOS 版本记下来，报告里要写。

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

用例要**能被机械执行**——写「点首页右下角的 + 按钮」，不是「新建一条回忆」；预期结果要**能从截图判定**——写「顶部出现『编辑』标题栏，正文区光标闪烁」，不是「进入编辑态」。含糊的用例执行时全靠临场发挥，等于没写。

| 编号 | 标题 | 类型 | 前置条件 | 操作步骤 | 预期结果 |
|------|------|------|---------|---------|---------|
| TC-01 | ... | 新功能/回归/边界 | ... | 1. ... 2. ... | ... |

优先级：改动主路径 > 回归面 > 边界与异常。**数量控制在 8~15 条**——每条用例在模拟器上都要真点一遍，写 40 条的结果是跑不完，最后靠脑补补齐。

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

全程用 Claude Desktop 自带的模拟器工具，四步：

```
mcp__Claude_Code_iOS_Simulator__control  { action: "attach", device: "iPhone 17 Pro" }
mcp__Claude_Code_iOS_Simulator__build    { action: "build", project_path: "<绝对路径>.xcodeproj", scheme: "<S>", device: "iPhone 17 Pro" }
mcp__Claude_Code_iOS_Simulator__build    { action: "build_status", build_id: "<上一步返回的 id>" }   # 轮询到结束
mcp__Claude_Code_iOS_Simulator__control  { action: "launch", app_path: "<build_status 返回的 .app 路径>", bundle_id: "<bundleId>" }
```

`project_path` 必须是绝对路径，相对路径会被直接拒绝；有 `.xcworkspace` 就换成 `workspace_path`。

**第一步的 attach 不要省。** 它秒开，作用是让用户从构建阶段就盯着这块屏幕；`launch` 虽然也会自己附加，但那已经是几分钟以后了，中间用户是全盲的。没有模拟器在跑时 attach 会报一句无害的错，这是正常的——先跑 `build`（它会带起目标模拟器），起来之后再 attach 一次。

MCP 报错时**把错误原样告诉用户，停在这儿等他处理**，不要绕到 `xcrun simctl` 或手开 Simulator.app 去把流程走通。这类错误基本都是环境问题（Xcode 没选对、缺 iOS 平台、模拟器没授权），多数需要用户输密码才能修，你绕过去也只是把问题推迟到更难查的地方。

**装完先确认装的是这次改动的包**：截一张图，在界面上找到这次改动引入的可见元素，或者核对 `build_status` 返回的 `.app` 时间戳晚于构建开始时刻。测了半天旧包全绿是这类工作最尴尬的失败方式，而这一步只要十秒。

要验「首次安装」态（UserDefaults 回默认）时，MCP 没有卸载动作，在面板上长按图标删掉 App 再 `launch` 一次即可——`touch_path` 给一个 800ms 以上的长按就能进入抖动态。

## Step 6 — 逐条执行，边跑边留证据

每条用例按步骤驱动，关键节点 `screenshot` 看一眼真实界面，并**在看到的当下就把它写成一行观察记录**（`TC-01 步骤3：顶部出现「编辑」标题栏，正文区光标闪烁，右上角「完成」为可点态`）。

这一条是整份报告的地基：MCP 的截图是回到对话里的、不落盘，等整轮跑完再回忆「刚才那张图上有什么」必然失真，而报告里「实际结果」一栏只能从这些当场记录里长出来。用户想把截图作为文件留档时，如实说明这需要用 `xcrun simctl io <UDID> screenshot` 对同一台模拟器另外存盘（驱动仍然全走 MCP），**得到他同意再做**。

几个实操要点：

- **点之前先截图**。坐标是从上一张截图上读出来的，界面一变坐标就废了；凭记忆点是 GUI 自动化里最常见的错误来源。
- **坐标单位是 device point，不是截图像素**。截图回来的是像素图（iPhone 17 Pro 是 402×874 point，截图 3 倍），换算要自己做。
- **`tap` 切不动 `UISwitch`**，点在滑块正中也没反应，要用 `swipe` 在开关上横划（关：从右往左约 30pt）。
- **判定基于截图里实际看到的东西**，不是基于「改了这里所以应该显示 X」。控件太小看不清就先把它滚到屏幕中部、或收起键盘再截一张（`zoom` 这个 action 不存在，别调）。
- **判成失败之前，先排除是自己点错了**。截图对比三件事：点击位置是不是落在目标控件上、界面有没有停在上一步、有没有弹窗/键盘挡住。功能真坏了 / 流程没走到那一步 / 我点歪了——把第三种写成 bug，会浪费开发者半天时间去查一个不存在的问题。
- **卡住最多重试两次**，然后记为「阻塞」并写清卡在哪一步、当时屏幕上是什么，继续下一条。一条用例死磕到底会拖垮整轮，而它本身往往只是个定位问题。
- **用例之间复位状态**：`button` 按 `HOME` 回主屏，再 `launch` 一次；这比从当前页面一层层退回去可靠，也避免上一条用例的残留状态污染下一条。

需要特定前置状态时，能在 App 里或系统「设置」里点到的就点过去——语言与地区、通知与定位权限、深色模式、文字大小都在设置 App 中，MCP 点得到；App 内的深层页面可以用 `open_url` 走 URL Scheme 直达，省掉一串导航点击。

模拟器宿主菜单才能做的事（注入具体经纬度、摇一摇、模拟内存警告）MCP 够不着，**别为此绕到命令行**：把它写进用例的前置条件请用户手动设一次，或者归到「未覆盖」并注明原因。少测一条并说明，好过为了跑通而换一套用户看不见的操作方式。

## Step 7 — 出报告

写到被测仓库的 `gui-test-reports/<YYYYMMDD-HHmm>-<改动简述>.md`，这样报告能直接贴进 PR 或留档。目录还没被 `.gitignore` 收编时提醒用户一句，是否入库由他定。

证据以 Step 6 的当场观察记录为主——每一步写清屏幕上**实际**是什么，而不是「符合预期」。有另存的截图文件就放同目录 `screenshots/` 并用相对路径引用。

```markdown
# GUI 测试报告 — <改动标识>

| 项 | 内容 |
|----|------|
| 被测改动 | PR #123 / 本地未提交改动 / `release-x`...`dev-y` |
| 构建 | scheme `<S>` · Debug · commit `<短 sha>` |
| 环境 | iPhone 17 Pro · iOS 26.0 · Claude Desktop 模拟器面板 |
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

## 四、发现的问题
### 问题 1：<一句话描述现象>
- **复现步骤**：...
- **现象**：<屏幕上实际看到什么>
- **期望**：...
- **关联改动**：`path/to/File.swift:88`，本次 diff 中的 <哪一处>
- **补充**：<排除「点错了」的依据、复现是否稳定、几次里出现几次>

## 五、结论与建议
<能不能合；哪些问题必须先修；哪些改动建议补单测而不是 GUI 覆盖>
```

结论要给得干脆——**这次改动能不能合**，以及卡在哪儿。用户找你做 GUI 测试，最终要的是这个判断，不是一张表格。
