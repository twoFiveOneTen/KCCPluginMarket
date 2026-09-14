---
name: pr-review-resolver
description: "Fetches all unresolved review comments from a GitHub PR, determines whether each one points to a real code problem, fixes genuine issues directly in the codebase, outputs a Markdown table report, then asks the user via multiple-choice whether to commit and push the fixes, reply to each review thread, and mark those threads resolved. Use this skill whenever the user mentions reviewing PR comments, resolving review feedback, handling code review suggestions, acting on PR threads, or cleaning up review comments — even if they don't say 'pr-review-resolver' explicitly. Also trigger when the user says things like '帮我处理PR里的评论', '解决PR反馈', '把评论修掉', or similar."
---

# PR Review Resolver

Review all unresolved comment threads in a GitHub PR, judge each one into exactly one of three states — **Addressed** / **Won't Fix** / **Incorrect** — fix what needs fixing, then reply to every thread with its state and resolve the ones that should be resolved.

## Step 1 — Determine PR number and repo

Check the user's message for a PR number (e.g. `#42`, `PR 42`, `pull/42`). If none is given, derive it from the current git branch:

```bash
gh pr view --json number -q .number
```

Get the repo identity:

```bash
gh repo view --json nameWithOwner -q .nameWithOwner
# → "owner/repo"
```

## Step 2 — Fetch unresolved review threads

Use GraphQL to get all review threads where `isResolved` is false. Include the diff hunk for context.

```bash
gh api graphql -f query='
query($owner: String!, $repo: String!, $pr: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $pr) {
      title
      headRefName
      reviewThreads(first: 100) {
        nodes {
          id
          isResolved
          isOutdated
          comments(first: 10) {
            nodes {
              author { login }
              body
              path
              line
              originalLine
              diffHunk
              createdAt
            }
          }
        }
      }
    }
  }
}' -F owner=OWNER -F repo=REPO -F pr=NUMBER
```

Filter to threads where `isResolved == false`. If there are zero unresolved threads, tell the user and stop.

Keep each thread's `id` alongside your notes — Step 7 needs it to reply and to mark the thread resolved, and re-running the query later just to recover ids wastes a round trip.

## Step 3 — 判定每条评论的状态

每条行内评论最终都要落到三个状态之一。判定前先读评论指向的源文件、确认代码当前的真实状态 —— `diffHunk` 只有几行上下文，往往不足以判断评论说得对不对。

| 状态 | 含义 | 什么时候用 |
|------|------|-----------|
| **Addressed** | 问题成立，且现在已经解决 | 评论指出了真实的 bug、崩溃风险、安全问题、缺失的错误处理、竞态，或仍然存在的规范违反（强制解包、硬编码文案、缺少本地化）→ 本次改掉它。**也包括**问题已在后续 commit 修掉、或代码重构后该问题已不存在（含 `isOutdated: true` 且关注点随代码消失的情况）—— 问题确实被解决了，只是不是这次改的 |
| **Won't Fix** | 问题成立，但这次不改 | 本地开发期的依赖引用（见下）、超出本 PR 范围的既有问题、纯主观偏好且仓库没有规范支持、有意为之的权衡。纯提问 / 讨论类评论也归这里 —— 回答它，但没有代码要改 |
| **Incorrect** | 评论的判断本身不成立 | 评论误读了代码（漏看上游的 guard、早返回、参数校验、调用方已统一 catch）、基于错误的前提、或描述的行为与代码实际行为不符。**判 Incorrect 必须给得出代码依据**（文件行号，或几行关键代码）；给不出依据就不是 Incorrect，重新判 |

**本地依赖是 Won't Fix，不是 Incorrect**：评论说某个本地包 / 组件目录不在仓库里（`Components/KKCommon` 这类 `relativePath` 依赖、未提交的组件目录、嵌套 git 的包），是本地开发期的正常状态，发布前会切成远程依赖。回复时说清这一点即可。

判定原则：
- **拿不准是 Addressed 还是 Won't Fix 时，倾向于改** —— 做一个无害的改进，好过默默丢掉一个真实的关切。
- **拿不准是不是 Incorrect 时，不要判 Incorrect** —— 说评论者错了却给不出依据，比不回复更伤。降级为 Addressed（改掉）或 Won't Fix（说明理由）。
- **需要人类拍板的不要猜着打状态**（涉及架构决策、有多种合理改法、改动风险大）：在报告里记为 `⏸ 待定`，Step 6 交给用户定，定下来后再归入三态。待定的评论这一轮不回复、不 resolve。
- PR 作者自己留的评论照常判定，不因为作者身份就跳过。

## Step 4 — 修掉判为 Addressed 的问题

对每条判为 **Addressed** 且需要本次改动的评论：

1. 读改动点周围的完整上下文（不只是评论锚定的那几行）
2. 做修掉该问题所需的**最小改动**，别顺手重构
3. 确认改动没引入新问题
4. 记下改了什么，一句话说清

一次改一条。改到一半发现这个修法有歧义或风险（要动架构、有多种合理改法），停下来改判为 `⏸ 待定`，写清楚卡在哪、有哪几种选择，交给 Step 6 让用户定 —— 不要猜一个改法然后当成 Addressed 报上去。

## Step 5 — Output the report

After processing all threads, output this Markdown table. Use 简体中文 for all content except code identifiers and file paths.

```
## PR #{number} 评论处理报告

| # | 评论作者 | 文件位置 | 评论摘要 | 状态 | 处理说明 |
|---|---------|---------|---------|------|---------|
| 1 | @alice | `src/Foo.swift:42` | 强制解包存在崩溃风险 | ✅ Addressed | 将 `!` 改为 guard let 安全解包 |
| 2 | @bob   | `Package.swift:12` | 本地包 `KKCommon` 不在仓库里 | 🚫 Won't Fix | 本地开发期依赖，发布时切换为远程 |
| 3 | @carol | `src/Baz.swift:88` | 缺少错误处理 | ❌ Incorrect | 调用方 `loadData()` 已在 `Loader.swift:120` 统一 catch |
| 4 | @dave  | `src/Net.swift:31` | 建议改成串行队列 | ⏸ 待定 | 涉及并发模型选型，两种改法都成立，需你定 |
```

状态图标：
- `✅ Addressed` — 问题成立，已解决（本次改的，或先前 commit 已改）
- `🚫 Won't Fix` — 问题成立，本次不改，说明理由
- `❌ Incorrect` — 评论判断不成立，**处理说明里必须写出代码依据**（文件:行号）
- `⏸ 待定` — 不是终态，只在 Step 6 用户拍板前出现；拍板后归入上面三态之一

表格后加一行汇总：

```
共处理 N 条未解决评论：X 条 Addressed，Y 条 Won't Fix，Z 条 Incorrect，W 条待定。
```

没有待定项时省掉「W 条待定」，别写「0 条待定」。

## Step 6 — 让用户点选后续动作

提交、推送、回复评论、标记已解决都是对外可见、不好撤回的动作，所以不要自作主张，也不要问一句「要提交吗」再等用户敲一段话 —— 用 `AskUserQuestion` 把决定变成点击。

**先清掉 `⏸ 待定`（仅当报告里有）**

待定项一条一题，`multiSelect: false`，一轮最多 4 题（超过就分多轮）：

- question：`#4 @dave 建议 Net.swift:31 改成串行队列，怎么处理？`
- header：`#4 Net.swift`
- 选项写成具体的改法，每个选项的 description 说清代价，最后一项恒为不改：
  1. `改成串行队列` — 判为 Addressed
  2. `加锁保护共享状态` — 判为 Addressed
  3. `保持现状` — 判为 Won't Fix，回复里说明理由

用户定完之后回 Step 4 把选中的改法做掉，更新报告里这几行的状态，再往下走。**所有评论都有终态之后**才问下面两件事。

没有任何代码改动（一条 Addressed 都没有）时跳过提交那一问，只问评论要不要回。

**第一问（单选）：代码怎么提交**

- question：`Addressed X 条，已改动 Y 个文件，要怎么提交？`
- header：`提交`，`multiSelect: false`
- 选项：
  1. `提交并推送（推荐）`
  2. `只提交，不推送`
  3. `都不做，我自己来`

**第二问（单选）：评论怎么处理**

- question：`要按状态回复这 N 条评论吗？（Addressed X / Won't Fix Y / Incorrect Z）`
- header：`评论回复`，`multiSelect: false`
- 选项：
  1. `按状态回复并 resolve（推荐）` — Addressed 和 Won't Fix 回复后 resolve；Incorrect 只回复不 resolve，留给评论者判断
  2. `只回复，全都不 resolve`
  3. `挑选部分回复` — 下一步逐条勾选
  4. `都不做`

选「挑选部分回复」时再发起一次 `AskUserQuestion`：`multiSelect: true`，每题最多 4 个选项、每次最多 4 题，所以按报告顺序每 4 条切一题，label 用 `#1 ✅ @alice Foo.swift:42`（带上状态图标，用户一眼能看出这条是在认同还是在反驳），description 用报告里的处理说明。超过 16 条就分多轮问。

## Step 7 — 执行

**提交**：只 `git add` 你实际改过的文件，别用 `git add -A` 把工作区里无关的改动一起带上。commit message 照仓库既有风格写（`git log --oneline -10` 看一眼）。推送时如果分支没有 upstream，用 `git push -u origin HEAD`。

**回复评论**（用 Step 2 拿到的 thread `id`）：

```bash
gh api graphql -f query='
mutation($threadId: ID!, $body: String!) {
  addPullRequestReviewThreadReply(input: {pullRequestReviewThreadId: $threadId, body: $body}) {
    comment { url }
  }
}' -f threadId=THREAD_ID -f body='**Addressed** — 已改为 guard let 安全解包，见 commit abc1234。'
```

**回复正文必须以状态开头**，评论者展开线程第一眼看到的就是结论：

```
**Addressed** — {改了什么}，见 commit {sha}。

**Won't Fix** — {为什么这次不改}。

**Incorrect** — {评论的判断哪里不成立}，{代码依据：文件:行号，或几行关键代码}。
```

三个状态各自的分寸：

- **Addressed**：说改了什么，带上 commit 号，评论者能点过去看。不要复述你的分析过程。
- **Won't Fix**：只给理由，不要辩护式长篇。「本地开发期依赖，发布前切远程」「这条超出本 PR 范围，已记录到 issue #N」这种一句话就够。
- **Incorrect**：这是在告诉评论者他看错了，所以**必须给证据**，而且语气对事不对人 —— 写「`user` 在 L38 已经 guard 过，走到这里不会为 nil」，不写「你没看仔细」。给不出证据就别用这个状态，回 Step 3 重判。

**标记已解决**：

```bash
gh api graphql -f query='
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) { thread { isResolved } }
}' -f threadId=THREAD_ID
```

resolve 策略按状态走：

| 状态 | resolve？ | 为什么 |
|------|----------|--------|
| `✅ Addressed` | 是 | 问题已经解决，线程没有继续存在的必要 |
| `🚫 Won't Fix` | 是 | 决定已经做出，理由写在回复里；评论者不认可可以重开 |
| `❌ Incorrect` | **否** | 你在反驳评论者的判断，该由他看过依据后自己关。自己 resolve 等于自己判自己赢，这是最容易激化讨论的一步 |

回复用简体中文，一两句话说清结论就行 —— 评论者点开是想知道结果，不是想读一遍你的思考过程。

顺序上先提交推送、再回复，这样 Addressed 的回复里能带上真实的 commit 号。

做完在对话里简短说明：提交了什么、推了没有、各状态各回复了几条、resolve 了几条、哪几条按规则留着没 resolve。

## Edge cases

- **No unresolved threads**: Report "PR #{number} 中没有未解决的评论。" and stop.
- **`resolveReviewThread` 报权限错误**：resolve 需要仓库写权限或是 PR 作者本人。别重试，如实告诉用户哪几条没能标记，回复本身已经发出去了。
- **Outdated thread**：先确认问题在新代码里还在不在。已经不在了判 `✅ Addressed`（注明是先前 commit 改掉的）；换了位置但依然存在，就照常修掉。
- **Thread with multiple comments**：以线程里最新一条为准判定状态，早先的评论当上下文读。
- **File not found locally**：判 `⏸ 待定`，说明路径解析不了，交给用户 —— 不要凭评论正文猜代码长什么样就打状态。
- **Non-Swift files**（配置、Markdown 等）：同样三态判定，不因为不是源码就跳过。
- **同一线程之前已经回复过**：不要重复发同样的结论。状态没变就跳过，状态变了（比如上次 Won't Fix 这次改了）就回复新状态并说明变化原因。
