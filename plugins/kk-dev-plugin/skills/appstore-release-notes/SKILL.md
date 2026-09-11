---
name: appstore-release-notes
description: "Generates the App Store \"What's New\" release notes for the version on the current repo's release- branch, by diffing it against main: collects commits and their linked GitHub issues, keeps only the changes a user can actually notice, writes every new feature as its own short bullet, folds all bug fixes and minor tweaks into a single \"已知问题的修复\" line, and outputs both a 简体中文 and an English version as plain text ready to paste into App Store Connect, plus a traceability table mapping each bullet back to its issue. Use this skill whenever the user is about to ship a version and needs the store copy — '生成这个版本的 App Store 更新说明', '写一下发版文案', '这版更新了什么，写个更新说明', 'release notes 写一下', '把 release 分支和 main 的差异整理成更新说明', '版本要提审了，更新内容写一下', 'what's new 文案', or when they ask what changed in this release and want it phrased for end users rather than for developers. Also trigger when they ask for a bilingual changelog for an app store submission. Do NOT use for internal engineering changelogs or git history summaries aimed at developers — this skill deliberately throws away everything users can't see."
---

# App Store 发布更新说明

把 `release-x.y.z` 相对 `main` 的改动，写成用户在 App Store 「新增内容」里读到的那段话。中英双语，纯文本，短。

这件事的难点不在收集 diff，而在**扔掉东西**。一个版本几十条 commit，其中大半是评审返工、重构、埋点、lint、本地化文件对齐 —— 用户一条都看不见。把它们写进更新说明，等于让用户在应用商店读你的 git log。

## Step 1 — 收集素材

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/appstore-release-notes/scripts/collect_changes.py
```

脚本默认拿当前 `release-*` 分支（不在该分支上就取最近更新的那个）对比 `main`，把 commit 按 issue 归并，带上 issue 的标题、标签和正文。需要时用 `--release` / `--base` 指定分支，`--no-issues` 跳过 gh 只看 commit。

- 提示某些 issue 取不到、且本机访问 GitHub 要走代理：在命令前加 `HTTPS_PROXY=http://127.0.0.1:7890` 重跑。
- issue 节里的「实现说明（PR #N）」是该需求对应的 PR 描述，通常比 issue 正文更贴近最终做出来的东西，拿来理解功能。极少数情况下 `PR #N` 会自己单独成一节（PR 没写 `Closes #N` 关联 issue），那也是实现说明，不是一条独立的新功能。
- 没有 issue 可查时照常继续，只是分类要多花点心思去读 commit 措辞。

## Step 2 — 决定每条改动用户看不看得见

对每个 issue（不是每条 commit）问一句：**装了新版本的用户，不看更新说明，自己能发现这个变化吗？**

**能，而且是多了一项能力或一个新界面 → 新功能，单独成条。** 例如新增的页面、新的开关、额度从 1 提到 3、原来做不到的操作现在能做。issue 标签是 `feature` 通常落在这里，但以实际内容为准 —— 标签是开发者随手打的，不是判据。

**看得见但只是原有功能变顺手了，或者原本就该这样 → 并入「已知问题的修复」。** 崩溃、显示错乱、文案不对、弹窗太小、大字体下按钮折行，都属于这类。用户明确要求这些合成一条，不要逐条罗列。

**看不见 → 直接丢掉。** 埋点与坐标精度、SwiftLint 清理、删测试 target、代码分层调整、评审返工、本地化文件排版对齐、版本号提交、单元测试。这些不写进更新说明不是偷懒，是因为写了只会稀释真正的信息。

判断吃不准时，看 issue 正文里用户视角的那句话（「用户没有后悔恢复的可能」这种），而不是实现要点。

一个 issue 里混着新功能和杂项很常见（比如「某版本优化任务」下面挂着四件不相干的事），要拆开分别归类，别整包处理。

## Step 3 — 写中文条目

每条一行，句式是「**功能名：用户得到了什么**」，说收益不说实现。

- ❌ 回忆删除改为软删除，新增 `deletedDate` 标记与回收站数据层
- ✅ 回收站：删除的回忆会先进入回收站，30 天内随时可以恢复

功能名要用 **app 里用户真正看到的那个词**。去 `Localizable.strings`（中文用 `zh-Hans.lproj`）里搜一下这个功能的按钮/标题文案再下笔 —— 代码里叫 `Trash`、界面上叫「回收站」，更新说明必须跟界面一致，否则用户按图索骥找不到。

其余约束：

- 条数控制在 3-5 条。新功能多于 5 个时合并同类项，或只留用户最有感的那几个，剩下的并进最后那条。
- 一条一行，尽量不超过 40 个字；确实需要补一句说明时才换行写第二行。
- 不写版本号、不写「我们」「本团队」、不写致谢和表情。
- 最后固定一条：`• 已知问题的修复与体验优化。`（没有任何修复时才省略，这种情况极少）

## Step 4 — 写英文版

英文不是中文的逐字翻译，是同一件事用英文 App Store 的惯常说法重写一遍：句子更短，多用名词短语，功能名首字母大写。

**术语必须对齐 `en.lproj/Localizable.strings` 里的真实译名**。中文叫「回收站」，英文界面上可能是 "Trash" 而不是想当然的 "Recycle Bin"；同一个功能出现两个名字，用户会以为是两件事。每个功能名都回 strings 文件查一次，别凭中文反推。

```
❌ Memory deletion has been changed to soft deletion, with a new recycle station
✅ Trash: deleted memories stay for 30 days and can be restored anytime.
```

## Step 5 — 输出

先给两段纯文本文案，再给溯源表。

**文案要放在代码块里**，方便用户整段复制到 App Store Connect。注意「新增内容」字段是**纯文本，不渲染 Markdown** —— `**加粗**` 会原样显示成一堆星号。能用的排版手段只有项目符号 `•`、换行和空行，够用了，克制地用。

````
## 简体中文（v{版本号}）

```
本次更新

• 回收站：删除的回忆会先进入回收站，30 天内随时可以恢复。
• 首页支持切换为「所有回忆录」，一屏浏览全部回忆。
• 免费用户单篇回忆最多可添加 3 张照片。
• 已知问题的修复与体验优化。
```

## English (v{版本号})

```
What's New

• Trash: deleted memories stay for 30 days and can be restored anytime.
• Switch the home feed to All Memoirs and browse every memory in one place.
• Free users can now add up to 3 photos to a single memory.
• Fixes for known issues and overall improvements.
```

## 条目来源

| 更新说明条目 | 来源 | 说明 |
|---|---|---|
| 回收站 | issue #294 | 新功能 |
| 首页切换所有回忆录 | issue #292 | 新功能 |
| 3 张照片上限 | issue #289 | 额度变化，用户可感知 |
| 已知问题的修复 | issue #291、#294、IJIJIN-11294 | iPad 详情页弹窗过小、大字体下按钮折行、时光图集字体未生效 |

未写入：issue #291 的埋点精度与 SwiftLint 清理、删除 UI 测试 target、各 issue 的评审返工与单测 —— 用户无感知。
````

这张表是给用户核对用的：他最清楚这一版到底做了什么，表格能让他一眼看出有没有漏掉卖点、有没有哪条名不副实。**被归入「已知问题的修复」但其实挺可感知的改进，要在说明列写清楚**，用户想把它提成独立一条时才有的选。

输出完直接问一句要不要调整某条，别自作主张改口径。用户说要存文件再存，默认只在对话里给。

## 边界情况

- **release 分支和 main 无差异**：脚本会报错退出。多半是分支名不对或本地落后，提示 `git fetch` 后重试，别硬编内容。
- **仓库没有 release- 分支**：问用户要发布的是哪个分支，用 `--release` 指定；不要默认拿当前分支对比。
- **这一版全是修复**：中文就写「本次更新修复了若干已知问题，并优化了使用体验。」一句话，不要为凑数把重构包装成功能。
- **commit 消息里没有 issue 号**：只能靠 commit 措辞判断，此时更要谨慎 —— 说不清用户能看见什么的改动，一律并进修复那条。
- **改动横跨多个版本**：release 分支从 main 切出后 main 又前进过时，`main..release` 仍只包含 release 上的提交，结果是对的；但如果用户说的版本范围和分支对不上，以用户说的为准，用 `--base` 指定实际上一个发布点（比如上个版本的 tag）。
