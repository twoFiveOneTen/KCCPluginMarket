---
name: ios-gui-tester
description: "Takes a specified code change (a GitHub PR, uncommitted local edits, or a branch-to-branch diff), works out which user-visible behaviour it can affect, writes GUI test cases, waits for the user to approve them, then drives the iOS Simulator to execute each case with screenshots as evidence, and writes a Markdown test report into the repo. Use this skill whenever the user wants a code change verified through the UI rather than through unit tests: '帮我 GUI 测一下这个 PR', '这次改动在模拟器上跑一遍', '生成 GUI 测试用例并执行', '这个分支的改动会影响哪些界面，测一测', '出个界面测试报告', 'run GUI tests for these changes', 'verify this on the simulator', or when they ask what a diff breaks on screen and want it actually clicked through. Also trigger when the user asks for regression testing of a change on an iPhone simulator, or for a test report of a PR's UI impact. Do NOT use for reading a diff and commenting on code quality (use pr-reviewer) or for writing XCTest unit tests."
---

# iOS GUI Tester

把一段代码改动，变成「在模拟器上真的点过一遍」的证据。

流程是：拿改动 → 分析影响范围 → 写用例 → 用户确认 → 装包 → 逐条执行留截图 → 出报告。

这件事有两个地方最容易做假，先说清楚：

**影响范围不等于「改了哪些文件」。** diff 给的是文件，用户看到的是页面。改一个共用函数，diff 里只有那一处，但界面上受影响的可能有五个入口——**回归就漏在这里**。所以分析必须沿调用链往上走到用户摸得到的入口，再横向找出所有共用这段代码的老功能。

**报告里的每个「通过」都必须有截图撑着。** GUI 测试最大的失效模式不是测出 bug，而是模型按「这么改了应该没问题」的推理写了一份全绿报告。你没点到的用例就写「阻塞」，测不了的改动就写「未覆盖」——一句诚实的「这块没测」比一条假绿用例值钱得多。

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
4. **模拟器**：`xcrun simctl list devices available` 挑一台，记下 UDID 和型号，报告里要写。

## Step 3 — 分析影响范围

这一步的产出是「哪些界面可能变了」，从三个方向找：

**纵向：改动点 → 用户入口。** grep 改动函数/属性的调用方，一路往上追到某个 ViewController 或页面，那才是用例的起点。追不到入口的改动，说明它可能根本不在 GUI 路径上——记下来，Step 4 归到「未覆盖」。

**横向：谁还在用这段代码。** 同一个函数的其他调用方就是回归面。这些老功能没人改，但可能被顺手改坏了，而且没人会想到去点它们。

**状态维度：改动依赖什么前置条件。** 空数据 / 有数据、首次安装 / 已有配置、权限已授 / 未授、深色模式、大字体档位、RTL 语言、iPad 与横屏——改动如果落在某个分支里，只在默认状态下点一遍是测不到的。

整理成表，Step 4 的用例直接从它长出来：

| 改动点 | 用户可见入口 | 预期行为变化 | 回归风险 |
|--------|-------------|-------------|---------|

**同时列出 GUI 测不了的部分。** 数据迁移、后台同步、纯算法、日志埋点这类界面上看不出差异的改动，写清楚为什么测不了，以及替代验证方式：跑对应单测、`sqlite3` 查沙盒里的库核对落库值、或者看运行日志。硬给它编一条 GUI 用例，只会产出一条无意义的绿灯。

## Step 4 — 写用例，等用户确认

用例要**能被机械执行**——写「点首页右下角的 + 按钮」，不是「新建一条回忆」；预期结果要**能从截图判定**——写「顶部出现『编辑』标题栏，正文区光标闪烁」，不是「进入编辑态」。含糊的用例执行时全靠临场发挥，等于没写。

| 编号 | 标题 | 类型 | 前置条件 | 操作步骤 | 预期结果 |
|------|------|------|---------|---------|---------|
| TC-01 | ... | 新功能/回归/边界 | ... | 1. ... 2. ... | ... |

优先级：改动主路径 > 回归面 > 边界与异常。**数量控制在 8~15 条**——每条用例在模拟器上都要真点一遍，写 40 条的结果是跑不完，最后靠脑补补齐。

把用例表和「未覆盖清单」一起给用户过目，等确认。用户说「直接跑」就跳过这一步；用户改了用例就按改后的来。

## Step 5 — 把这次改动装进模拟器

顺序有讲究：**先 attach 面板再构建**。面板打开是秒开的，用户能从构建阶段就看着；等 launch 时才顺带附加，用户前面几分钟是盲的。

```
mcp__Claude_Code_iOS_Simulator__control  { action: "attach", device: "<型号或 UDID>" }
mcp__Claude_Code_iOS_Simulator__build    { action: "build", project_path: "<绝对路径>.xcodeproj", scheme: "<S>", device: "<型号>" }
mcp__Claude_Code_iOS_Simulator__build    { action: "build_status", build_id: "<上一步返回的 id>" }   # 轮询到结束
mcp__Claude_Code_iOS_Simulator__control  { action: "launch", app_path: "<build_status 返回的 .app 路径>", bundle_id: "<bundleId>" }
```

没有模拟器 booted 时 attach 会报错，这是正常的——先 build 或 `xcrun simctl boot <UDID>`，起来后再 attach。

MCP 不可用时退回 simctl，**并且明确告诉用户你在用什么工具代替**，不要悄悄降级：

```bash
xcodebuild -project <X>.xcodeproj -scheme <S> -configuration Debug -destination "id=<UDID>" build
xcrun simctl boot <UDID>
xcrun simctl install <UDID> <DerivedData>/Build/Products/Debug-iphonesimulator/<App>.app
xcrun simctl launch <UDID> <bundleId>
xcrun simctl io <UDID> screenshot /tmp/shot.png      # 再用 Read 看图
```

**装完确认装的就是这次改动的包**：核对 `.app` 的时间戳晚于你开始构建的时刻，或者直接在界面上找到这次改动引入的可见元素。测了半天旧包全绿，是这类工作最尴尬的失败方式，而这一步只要十秒。

**要验「首次安装」态就 uninstall 再 install**，这是把 UserDefaults 清回默认最省事的办法。

## Step 6 — 逐条执行，边跑边留证据

每条用例按步骤驱动，关键节点截图存到报告目录的 `screenshots/` 下，命名带用例号（`TC-01-3.png`）。

几个实操要点：

- **点之前先截图**。坐标是从上一张截图上读出来的，界面一变坐标就废了；凭记忆点是 GUI 自动化里最常见的错误来源。
- **坐标单位是 device point，不是截图像素**。截图回来的是像素图（iPhone 17 Pro 是 402×874 point，截图 3 倍），换算要自己做。
- **`tap` 切不动 `UISwitch`**，点在滑块正中也没反应，要用 `swipe` 在开关上横划（关：从右往左约 30pt）。
- **判定基于截图里实际看到的东西**，不是基于「改了这里所以应该显示 X」。看不清就 `screenshot` 后放大细看。
- **失败先看日志再下结论**：`xcrun simctl spawn <UDID> log show --last 2m --style compact --predicate 'process == "<App名>"'`。要分清三件事——功能真坏了 / 流程压根没走到那一步 / 是我点错了地方。直接把第三种写成 bug，会浪费开发者半天时间。
- **卡住最多重试两次**，然后记为「阻塞」并写清卡在哪一步，继续下一条。一条用例死磕到底会拖垮整轮测试，而它本身往往只是个定位问题。

需要特定前置状态的用例（定位、权限、语言），用 launch 参数或 simctl 预置，比手点系统弹窗稳得多：

```bash
xcrun simctl privacy <UDID> grant location <bundleId>
xcrun simctl location <UDID> set 39.90869,116.39123
xcrun simctl launch <UDID> <bundleId> -AppleLanguages '(ar)' -AppleLocale ar_EG   # 验 RTL 本地化
```

## Step 7 — 出报告

写到被测仓库的 `gui-test-reports/<YYYYMMDD-HHmm>-<改动简述>.md`，截图放同目录的 `screenshots/`，报告里用相对路径引用，这样报告能直接贴进 PR 或留档。目录不在 `.gitignore` 里时提醒用户一句——截图会让仓库变大，是否入库由用户决定。

```markdown
# GUI 测试报告 — <改动标识>

| 项 | 内容 |
|----|------|
| 被测改动 | PR #123 / 本地未提交改动 / `release-x`...`dev-y` |
| 构建 | scheme `<S>` · Debug · commit `<短 sha>` |
| 环境 | iPhone 17 Pro · iOS 26.0 · <UDID 前 8 位> |
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
- **步骤与实际**：1. ... → 看到 ...（![](screenshots/TC-01-1.png)）
- **预期**：... / **实际**：...

## 四、发现的问题
### 问题 1：<一句话描述现象>
- **复现步骤**：...
- **现象**：...（截图）
- **期望**：...
- **关联改动**：`path/to/File.swift:88`，本次 diff 中的 <哪一处>
- **日志**：<相关片段>

## 五、结论与建议
<能不能合；哪些问题必须先修；哪些改动建议补单测而不是 GUI 覆盖>
```

结论要给得干脆——**这次改动能不能合**，以及卡在哪儿。用户找你做 GUI 测试，最终要的是这个判断，不是一张表格。
