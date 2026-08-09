---
name: pr-reviewer
description: "Reviews the newest GitHub pull request on the current branch — reads the diff, finds correctness, security, performance and convention problems, outputs a Chinese review report, and after the user confirms, posts each problem as an inline comment anchored to the exact code line, skipping anything an existing comment already raised. Use this skill whenever the user asks to review a PR, look over a pull request, check a PR before merging, leave review comments on a PR, or do a code review on GitHub — even if they don't say 'pr-reviewer' explicitly. Also trigger on phrasings like 'review 一下我的 PR', '帮我看看这个 pull request', '给 PR 提点意见', '把问题评论到 PR 上', '合并前帮我审一下'. This skill PRODUCES review comments; if the user instead wants to handle comments other people already left on their PR, use pr-review-resolver."
---

# PR Reviewer

Review the newest pull request on the current branch, report what's wrong in 简体中文, and — once the user confirms — leave each finding as an inline comment on the exact line it concerns.

Two things make or break this skill: **not repeating what someone already said** (duplicate comments make reviews noisy and get the bot muted), and **anchoring comments to lines GitHub will actually accept** (the API rejects any line outside a diff hunk with a 422).

## Step 1 — 收集上下文

One script gathers everything: PR metadata, the diff, the set of lines that can carry an inline comment, and every comment already on the PR.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/pr-reviewer/scripts/pr_context.py
```

Pass a PR number as the sole argument if the user named one (`… pr_context.py 42`); otherwise it resolves the PR from the current branch.

Read its output carefully, then read the full diff it wrote to `<git-dir>/pr-review/pr.diff`.

Stop and tell the user if:
- 当前分支没有关联的 PR（脚本会报错）→ 提示用户先 `gh pr create` 或指定 PR 号
- `gh` 未登录 → 提示运行 `gh auth login`

## Step 2 — 审查 diff

Read the diff in full. For anything non-trivial, also read the surrounding file from disk — a diff hunk shows you 3 lines of context, which is rarely enough to tell whether a change is actually safe. Checking how a changed function is called elsewhere is often where the real bug shows up.

Look across four dimensions:

**正确性与崩溃风险** — 逻辑错误、空值/强制解包、数组越界、边界条件（0、负数、空集合）、并发竞态、错误被吞掉或未处理、资源未释放、异步回调时序。

**安全性** — 注入（SQL/命令/路径）、鉴权与权限校验缺失、密钥或 token 硬编码、用户输入未校验、不安全的反序列化、日志中泄露敏感信息。

**性能** — 循环里发请求或查数据库（N+1）、主线程/UI 线程阻塞、不必要的重复计算、大对象全量拷贝、内存泄漏与循环引用、缺失的索引或缓存。

**可读性与项目规范** — 命名词不达意、重复代码、魔法数字、死代码、过长函数。规范部分要有依据：先看仓库里的 `CLAUDE.md`、lint 配置、以及周边同类文件的既有写法，用它们当标准，而不是套用通用偏好。

### 什么值得写成评论

A finding earns a comment when you can name the concrete consequence — "这里 `user` 为 nil 时会崩溃"、"这个查询在循环里，列表有 100 条就会发 100 次请求"。If you can't finish the sentence "这会导致……", it's probably not worth the PR author's attention.

Skip these — they cost the author time and buy nothing:
- 纯个人偏好，且仓库里没有任何规范支持
- 复述代码在做什么，没有指出问题
- 与本次 diff 无关的既有代码（除非这次改动让它变危险了）
- 需要重构整个模块才能解决的宏观建议 —— 放进报告的总结里，不要挂成行内评论
- 自动生成的文件、锁文件、格式化产生的纯空白改动

Err on the side of fewer, sharper comments. A review with 5 real problems gets acted on; a review with 40 nitpicks gets ignored.

## Step 3 — 去重：跳过已有的问题

This is the step the user explicitly asked for, and it's the one that's easy to get wrong. `context.json` 里的 `existing_comments` 是 PR 上已有的全部行内评论（包括你上一次运行本 skill 留下的）。逐条比对你的每个发现：

**算重复，跳过：**
- 同一文件、行号相差在 3 行以内，且指向同一个问题
- 行号对不上，但描述的是同一处代码的同一个缺陷（比如同一个函数里同一个强制解包，只是评论挂在了函数签名那行）
- 已有评论提出了这个问题，作者在回复里解释或反驳了 —— 讨论已经在进行，再提一次没有意义

**不算重复，可以提：**
- 已有评论标了 `[已过期]`（`outdated: true`）——它锚定的代码已经被改掉了。但要先确认问题在新代码里**依然存在**，改掉了就别提了
- 同一行有已有评论，但你发现的是**另一类**问题（比如别人说命名，你说空指针）
- 已有评论只是提问或讨论，没有指出你要说的这个缺陷

判断时用语义，别用字符串匹配 —— 「这里可能 crash」和「`user!` 在未登录时会 nil」说的是同一件事。拿不准时倾向于跳过：漏提一个问题，作者还有别的机会发现；重复刷屏一次，整个 review 的可信度就没了。

同时扫一眼 `review_bodies`（已有的 review 总结），有些人习惯把问题列在总结里而不是挂行内。

## Step 4 — 输出报告并等待确认

发布行内评论是对外可见、且难以撤回的动作，所以**先在对话里输出完整报告，等用户明确说「发」再执行 Step 5**。用户如果一开始就说了「直接发」「不用确认」，可以跳过等待。

除代码标识符和文件路径外，报告全部用简体中文：

```
## PR #{number} Review 报告

**标题**：{title}
**分支**：{head} → {base}    **作者**：@{author}
**改动**：{N} 个文件，+{A} −{B}

### 发现的问题

| # | 严重度 | 文件位置 | 问题 | 说明 |
|---|-------|---------|------|------|
| 1 | 🔴 严重 | `src/Foo.swift:42` | 强制解包崩溃风险 | `user` 在未登录时为 nil，此处 `user!` 会触发崩溃 |
| 2 | 🟡 建议 | `src/Api.swift:88` | 循环内发起网络请求 | 列表每项一次请求，100 项即 100 次调用，建议改批量接口 |
| 3 | 🔵 提示 | `src/Bar.swift:17` | 魔法数字 `86400` | 建议提取为常量 `secondsPerDay` |

### 跳过的重复项

| 文件位置 | 问题 | 已有评论 |
|---------|------|---------|
| `src/Foo.swift:42` | 强制解包 | @alice 已提出 |

### 整体评价

{两三句话：这个 PR 整体质量如何、有没有需要重构或架构层面讨论的点、能不能合并}

共发现 N 个问题（严重 X / 建议 Y / 提示 Z），跳过 M 个已有评论覆盖的问题。
确认后我会把这 N 个问题作为行内评论发到 PR 对应代码行上。
```

严重度：
- `🔴 严重` — 会崩溃、有安全漏洞、逻辑明确错误，合并前必须修
- `🟡 建议` — 性能问题、错误处理缺失、明确违反项目规范，应该修
- `🔵 提示` — 可读性、命名、小重构，修不修都行

没发现问题时不要硬凑。直接说「PR #{number} 未发现需要指出的问题」，简述你检查了什么，然后停下。

## Step 5 — 发布行内评论

用户确认后，把发现写成 findings JSON（写到临时文件即可，比如 `<git-dir>/pr-review/findings.json`）：

```json
{
  "summary": "## 🤖 Review 总结\n\n本次改动共发现 3 个问题：严重 1、建议 1、提示 1。详见各行内评论。\n\n整体评价：……",
  "comments": [
    {
      "path": "src/Foo.swift",
      "line": 42,
      "body": "**🔴 正确性** — 强制解包崩溃风险\n\n`user` 在未登录场景下为 nil，这里的 `user!` 会直接触发崩溃。\n\n```suggestion\nguard let user = user else { return }\n```"
    }
  ]
}
```

然后发布：

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/pr-reviewer/scripts/post_review.py <git-dir>/pr-review/findings.json
```

脚本会校验每条评论的行号是否落在 diff hunk 内，一次性提交为 `COMMENT` 类型的 review（不 approve、也不 request changes —— 那是人该做的决定）。落不到 diff 行上的问题会被自动并入总结正文，不会丢失。想先看看会发什么，加 `--dry-run`。

### 行内评论怎么写

每条评论遵循同一个结构，作者扫一眼就知道严重度和该做什么：

```
**{严重度图标} {维度}** — {一句话结论}

{为什么是问题：具体的触发条件和后果}

{怎么改：一句话，或一个 suggestion 代码块}
```

- **锚定到问题代码的最后一行**。跨多行的问题用 `start_line` + `line` 圈出范围。
- **`line` 必须是 `context.json` 里 `commentable` 列出的行号**，否则 GitHub 会拒绝。脚本会拦下来，但你自己对着行号写能省一轮往返。
- **`suggestion` 代码块只在替换内容恰好覆盖被评论的那几行时才用**。范围对不上的话，GitHub 的「Apply suggestion」按钮会生成错误的代码，比不给建议更糟 —— 这种情况就用普通代码块。
- 说人话，对事不对人。写「这里 nil 时会崩」，不写「你没考虑 nil」。

## 边界情况

- **当前分支有多个 PR**：`gh pr view` 取的是当前分支关联的那个。用户提到具体 PR 号时优先用用户给的。
- **PR 是 Draft**：照常 review，在报告里注明这是草稿，评论语气偏建议。
- **超大 PR（几千行以上）**：先按文件重要性排序，优先审核心逻辑，跳过锁文件、生成代码、纯格式化改动。在报告里说明你实际审了哪些文件、跳过了什么 —— 别让用户以为你全看了。
- **PR 已合并或已关闭**：仍然可以评论，但先提醒用户这个 PR 已经 merged/closed，问是否还要发。
- **发布返回 422**：几乎都是行号不在 diff hunk 内。回到 `context.json` 的 `commentable` 重新对行号，别猜。
- **本次没有可评论的发现，但有整体建议**：findings 的 `comments` 留空、只填 `summary` 也能发，会作为一条 review 总结出现。
