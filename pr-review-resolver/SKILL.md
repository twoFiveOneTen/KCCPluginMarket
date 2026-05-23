---
name: pr-review-resolver
description: "Fetches all unresolved review comments from a GitHub PR, determines whether each one points to a real code problem, fixes genuine issues directly in the codebase, and outputs a Markdown table report. Use this skill whenever the user mentions reviewing PR comments, resolving review feedback, handling code review suggestions, acting on PR threads, or cleaning up review comments — even if they don't say 'pr-review-resolver' explicitly. Also trigger when the user says things like '帮我处理PR里的评论', '解决PR反馈', '把评论修掉', or similar."
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

## Edge cases

- **No unresolved threads**: Report "PR #{number} 中没有未解决的评论。" and stop.
- **Outdated thread**: Treat as ignorable — the code it referenced no longer exists at that location.
- **Thread with multiple comments**: Focus on the most recent comment in the thread; earlier comments are context.
- **File not found locally**: Mark as `⚠️ 需确认` with note that the file path couldn't be resolved.
- **Non-Swift files** (config, Markdown, etc.): Apply the same logic — fix if it's a real issue, ignore if not.
