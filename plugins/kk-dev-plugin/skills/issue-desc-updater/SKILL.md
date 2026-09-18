---
name: issue-desc-updater
description: "Takes a GitHub issue number, finds the dev branch that implemented it, works out what the branch ACTUALLY shipped (net diff against the right baseline, not the commit-by-commit story), then rewrites the issue body as 原始需求 + 实现情况 + 与原始需求的差异 — keeping the original requirement text verbatim — and updates the issue after the user approves the new body. Use this skill whenever the user wants an issue's description brought in line with what was really built: '把 issue-296 的描述按实际实现更新一下', 'issue 描述和最后做出来的东西对不上，同步一下', '根据 dev 分支的改动更新 issue', '给这个 issue 补一份实现说明', '需求改过好几轮，issue 正文还是最初那版，帮我更新', 'update the issue description to match what we actually shipped', 'sync issue body with the branch', or when they point at an issue and say the delivered result differs from what was written. Also trigger when they ask what a dev branch actually did relative to its issue, or want a 需求 vs 实现 差异对照. Do NOT use for implementing an issue (use issue-implementer), reviewing a PR (use pr-reviewer), or writing user-facing App Store copy (use appstore-release-notes)."
---

# Issue 描述更新

issue 正文是需求刚提出时写的，开发做完、PR 合了，正文还停在最初那一版。这个 skill 把开发分支真正做出来的东西写回 issue，让它从「当初想要什么」变成「最后交付了什么」。

有两件事贯穿整个流程，先说清楚：

**原始需求逐字保留，一个字都不要改写。** `gh issue edit` 是整段覆盖正文，改完原文就没了（GitHub 有编辑历史，但没人会去翻）。而且差异表里写「原需求第 3 条没保留」时，读的人得能在正文里找到第 3 条——把原需求「顺手润色」一下，这句话就悬空了。

**写最终状态，不是开发流水账。** 一条 dev 分支上二十几个提交，里面有返工、有中途被推翻的设计、有「处理 PR 评论」。issue 正文要回答的是「现在代码里是什么样」，不是「我们怎么走到这一步的」。中途被删掉的设计只配在差异表里出现一次。

## Step 1 — 收集素材

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/issue-desc-updater/scripts/collect_issue_changes.py <issue编号>
```

脚本按 issue 号在分支名里搜开发分支，定出 diff 范围，打印 issue 正文原文、评论、关联 PR、提交列表和 diffstat。

最该核对的是输出里的**分叉点来源**那一行。基线选错，diff 里会混进 release 分支上别人的提交，实现说明就会多出一堆不属于这个 issue 的内容。脚本按三档推断并写明用了哪档：

| 来源 | 含义 | 可信度 |
|---|---|---|
| PR 的 base 分支 | 开 PR 时声明的基线 | 直接用 |
| 候选基线（分支独有提交最少） | 从哪拉的，独有的就只有自己那些提交 | 扫一眼提交列表，是否都属于这个 issue |
| commit 信息匹配 issue-N | 分支已合并进基线，只能这么圈 | 必须人工核对，混了别的 issue 的提交要用 `--base` 重来 |

常见中断，停下来说清楚而不是绕过去：

- 没找到分支 → 先 `git fetch --all --prune`；分支名不含 issue 号就用 `--branch` 指定
- 有多条同号分支（同一需求开过两轮）→ 脚本会警告并用最近提交的那条，确认是不是用户想要的
- `gh` 报 TLS / 超时 → 前面加 `HTTPS_PROXY=http://127.0.0.1:7890` 重跑；未登录则 `gh auth login`
- issue 正文已经有「实现情况」章节 → 说明之前更新过，这次是增量更新，见最后一节

## Step 2 — 读 diff，搞清楚到底交付了什么

diffstat 和 commit 标题只能告诉你「动了哪儿」，不能告诉你「做成了什么样」。commit 写着「新增状态枚举」，八个提交之后可能又被删了——只看提交列表就会把一个已经不存在的设计写进 issue。

脚本给出的范围是三点 diff 的净结果，这正是要的口径：

```bash
git diff <脚本给出的范围> -- <文件路径>
```

按改动分布挑文件读，优先级大致是：**新增的核心类 > 数据模型 / 数据库 schema > 关键调用方的改动 > 配置与资源**。整份 diff 几千行时不必逐行读完，但每个新增的类至少要知道它是什么、被谁调用、解决什么问题——说不出这三点就还没读懂，别急着下笔。

有几类文件不值得细读，扫一眼确认性质即可，它们在正文里各占一句就够：

- 本地化文件（`*.strings`）→「N 种语言均已翻译」
- 单元测试 → 列出新增的测试类名
- `project.pbxproj`、资源文件 → 通常不必提

**读 commit 历史的价值在于找「中途改变的决策」。** 像「删除无用的数据字段」「改用 X 方案」这类提交，是原设计被推翻的信号——差异表里那几条差不多都从这儿来。看到这种提交，回去 diff 确认最终状态，然后记下来。

读完之后，在心里过一遍：**这个分支交付的能力，用几句话怎么说清楚。** 说不清就回去补读。

## Step 3 — 逐条对照原始需求

把原始需求拆成条目（编号列表就按编号，一段话就按语义拆），每条给一个结局：

- **照做了** → 不进差异表。差异表塞满「做了」只会淹没真正的信息。
- **做了但和描述不一样** → 进差异表，写清最终是什么样、为什么不一样
- **没做** → 进差异表，写明原因（做不了 / 不必要 / 被后续讨论取消）

需求在 issue 评论里被改过很常见——评论里的最新表述才是当时的需求。如果实现跟着评论走、和正文不一致，差异表里注明「按评论 N 调整」，读的人才不会以为是实现跑偏了。

反过来，**实现里有原需求完全没提的东西也要写**（顺手加的开关、为了做成这件事必须先改的底层）。这类内容放在「实现情况」里正常描述即可，不用进差异表。

## Step 4 — 组装新正文

```markdown
## 需求

<原始正文，逐字照抄，不改写不精简不重新编号>

## 实现情况

### 1. <模块名>

- <做成了什么，附关键类名 / 方法名 / 字段名>
- <行为上的取舍：什么情况下展示、什么情况下不展示>

### 2. <模块名>

...

## 与原始需求的差异

| 原需求 | 实际实现 |
|---|---|
| <原文里的那一条，带上它的编号> | <最终是什么样，以及为什么> |
```

写「实现情况」时的分寸：**带上代码里的真名**（类名、方法名、字段名、接口路径），这是 issue 正文和代码之间唯一的锚点，半年后有人回来查就靠它。但不要贴代码、不要解释实现细节——一条说清「做了什么 + 关键取舍」即可。

按模块分节，不按提交顺序。节的顺序遵循数据流向：数据层 → 业务逻辑 → UI → 周边（搜索、导出、设置）→ 测试，读起来比按时间顺序顺得多。

没有任何差异时，「与原始需求的差异」整节省略，不要写一个「无」了事的空表格。

## Step 5 — 确认后写回

改 issue 正文是对外可见的操作，队友订阅了这个 issue 会收到通知，而且是整段覆盖。所以**先把完整的新正文贴给用户看，等明确确认再写**。

确认后，先备份原文再写回。用 `--body-file` 而不是 `--body`：正文里有反引号、`$`、换行和表格，走 shell 字符串一定会被转义弄坏。

```bash
gh issue view <编号> --json body --jq .body > /tmp/issue-<编号>-backup.md
gh issue edit <编号> --body-file /tmp/issue-<编号>-new.md
```

写回后报一句改了什么、备份在哪，并给出 issue 链接让用户点进去看渲染效果（表格在 Markdown 源码里看不出对没对齐）。

## 边界情况

- **issue 正文已经有「实现情况」章节**：说明之前更新过。这次是增量——保留「需求」节原样，把「实现情况」按本次新增的提交补充/修订，差异表合并去重。不要推倒重写，之前那版里可能有人工补充的信息。
- **分支还没合并**：照常做，但在汇报里说明「基于尚未合并的分支，后续若有返工需要再同步一次」。
- **一个 issue 对应多条分支/多个 PR**：脚本会列出来。取并集，diff 范围逐条算，实现情况合并写。
- **改动跨仓库**（主仓库 + 子模块）：脚本只看当前仓库。子模块里的改动要单独 `git -C <子模块路径> log` 看一遍，并在实现情况里注明属于哪个仓库。
- **issue 正文本来就是空的或只有一句话**：没有可对照的条目，差异表整节省略，只写实现情况。这种情况反而最值得更新——正文越空，实现说明的价值越大。
- **diff 和 issue 明显对不上**（分支做的是另一件事）：停下来告诉用户，别硬写。多半是分支找错了，用 `--branch` 指定正确的那条。
