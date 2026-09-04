---
name: pr-review-resolver
description: "Fetches all unresolved review comments from a GitHub PR, determines whether each one points to a real code problem, fixes genuine issues directly in the codebase, outputs a Markdown table report, then asks the user via multiple-choice whether to commit and push the fixes, reply to each review thread, and mark those threads resolved. Use this skill whenever the user mentions reviewing PR comments, resolving review feedback, handling code review suggestions, acting on PR threads, or cleaning up review comments — even if they don't say 'pr-review-resolver' explicitly. Also trigger when the user says things like '帮我处理PR里的评论', '解决PR反馈', '把评论修掉', or similar."
---

# PR Review Resolver

Review all unresolved comment threads in a GitHub PR, decide which ones represent real problems, fix the real ones, and produce a clear summary table.

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

## Step 3 — Analyze each unresolved thread

For every unresolved thread, read the actual source file to understand current code state:

```bash
# Read the file at the relevant path
```

Then make a judgment call: **is this a real problem that still exists?**

### Count as a real problem if:
- The comment points to an actual bug, crash risk, logic error, or security issue
- The comment flags a rule violation that still exists (e.g. forced unwrap when the project forbids it, missing localization, hardcoded strings)
- The comment identifies missing error handling, a race condition, or incorrect behavior

### Count as ignorable if:
- The thread is `isOutdated: true` (code has changed and the concern no longer applies)
- The comment is a question or discussion point with no required action
- The code the comment refers to has already been fixed in a later commit
- The comment is purely subjective preference with no objective standard (e.g. "I prefer X" with no project rule backing it)
- The comment was from the PR author themselves
- The concern was already addressed in a subsequent commit visible in the diff
- The comment flags a missing/local dependency or package reference (e.g. a local SwiftPM package like `Components/KKCommon`, an untracked local component directory, or a `relativePath` dependency that isn't in the checkout). During local development the project may reference dependencies locally and switch them to remote later — ignore these as expected for the dev phase, do NOT mark them as `需确认`

When in doubt, lean toward fixing rather than ignoring — it's better to make a harmless improvement than to silently discard a real concern.

## Step 4 — Fix real problems

For each thread judged as a real problem:

1. Read the full file context around the flagged lines
2. Make the minimal targeted fix that addresses the comment's concern
3. Verify the fix doesn't introduce new issues
4. Note what you changed (one clear sentence)

Apply fixes one at a time. If a fix is ambiguous or risky (e.g. architectural change, requires clarification), mark it as `需确认` in the report and describe what's needed instead of guessing.

## Step 5 — Output the report

After processing all threads, output this Markdown table. Use 简体中文 for all content except code identifiers and file paths.

```
## PR #{number} 评论处理报告

| # | 评论作者 | 文件位置 | 评论摘要 | 结果 | 处理说明 |
|---|---------|---------|---------|------|---------|
| 1 | @alice | `src/Foo.swift:42` | 强制解包存在崩溃风险 | ✅ 已修复 | 将 `!` 改为 guard let，添加安全解包 |
| 2 | @bob   | `src/Bar.swift:17` | 建议重命名变量 | ⏭ 已忽略 | 仅为命名偏好，无项目规范要求 |
| 3 | @carol | `src/Baz.swift:88` | 缺少错误处理 | ⚠️ 需确认 | 涉及架构决策，需与作者确认处理方式 |
```

Result icons:
- `✅ 已修复` — problem was real, fix applied
- `⏭ 已忽略` — not a real problem, no action taken  
- `⚠️ 需确认` — real concern but fix requires human decision

After the table, add a one-line summary:

```
共处理 N 条未解决评论：X 条已修复，Y 条已忽略，Z 条需确认。
```

## Step 6 — 让用户点选后续动作

提交、推送、回复评论、标记已解决都是对外可见、不好撤回的动作，所以不要自作主张，也不要问一句「要提交吗」再等用户敲一段话 —— 用一次 `AskUserQuestion` 把两件事一起问掉，用户点两下就完事。

没有任何改动（全部是「已忽略」）时跳过提交那一问，只问评论要不要回。

**第一问（单选）：代码怎么提交**

- question：`已修复 X 处代码，要怎么提交？`
- header：`提交`，`multiSelect: false`
- 选项：
  1. `提交并推送（推荐）`
  2. `只提交，不推送`
  3. `都不做，我自己来`

**第二问（单选）：评论怎么处理**

- question：`要回复这 N 条评论并标记为已解决吗？`
- header：`评论回复`，`multiSelect: false`
- 选项：
  1. `回复并标记已解决（推荐）` — 已修复的回复改动说明并 resolve；已忽略/需确认的只回复原因，是否 resolve 留给评论者
  2. `只回复，不标记已解决`
  3. `挑选部分回复` — 下一步逐条勾选
  4. `都不做`

选「挑选部分回复」时再发起一次 `AskUserQuestion`：`multiSelect: true`，每题最多 4 个选项、每次最多 4 题，所以按报告顺序每 4 条切一题，label 用 `#1 @alice Foo.swift:42`，description 用报告里的处理说明。超过 16 条就分多轮问。

## Step 7 — 执行

**提交**：只 `git add` 你实际改过的文件，别用 `git add -A` 把工作区里无关的改动一起带上。commit message 照仓库既有风格写（`git log --oneline -10` 看一眼）。推送时如果分支没有 upstream，用 `git push -u origin HEAD`。

**回复评论**（用 Step 2 拿到的 thread `id`）：

```bash
gh api graphql -f query='
mutation($threadId: ID!, $body: String!) {
  addPullRequestReviewThreadReply(input: {pullRequestReviewThreadId: $threadId, body: $body}) {
    comment { url }
  }
}' -f threadId=THREAD_ID -f body='已按建议改为 guard let 安全解包，见 commit abc1234。'
```

**标记已解决**：

```bash
gh api graphql -f query='
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) { thread { isResolved } }
}' -f threadId=THREAD_ID
```

回复内容用简体中文，一两句说清**改了什么**或**为什么没改**就够了 —— 评论者点开是想知道结论，不是想读一遍你的思考过程。

顺序上先提交推送、再回复，这样回复里可以带上 commit 号，评论者能直接点过去看改动。

做完在对话里简短说明：提交了什么、推了没有、回复了几条、resolve 了几条。

## Edge cases

- **No unresolved threads**: Report "PR #{number} 中没有未解决的评论。" and stop.
- **`resolveReviewThread` 报权限错误**：resolve 需要仓库写权限或是 PR 作者本人。别重试，如实告诉用户哪几条没能标记，回复本身已经发出去了。
- **Outdated thread**: Treat as ignorable — the code it referenced no longer exists at that location.
- **Thread with multiple comments**: Focus on the most recent comment in the thread; earlier comments are context.
- **File not found locally**: Mark as `⚠️ 需确认` with note that the file path couldn't be resolved.
- **Non-Swift files** (config, Markdown, etc.): Apply the same logic — fix if it's a real issue, ignore if not.
- **Local dependency / package reference issues**: Comments about a local package or component dir missing from the repo checkout (e.g. `Components/KKCommon` referenced via local `relativePath`, an untracked component folder, or a nested-git package not committed) are expected during local development — the components are switched to remote dependencies before release. Treat these as `⏭ 已忽略` and note "本地开发期依赖,发布时改为远程".
