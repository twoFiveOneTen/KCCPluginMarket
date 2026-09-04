---
name: issue-implementer
description: "Pulls a specified GitHub issue (body plus every comment, since requirements are usually refined in the comments), works out an implementation plan, waits for the user to approve it, then implements the change end to end — branch, code, build/test/lint self-check, commit in the repo's own message format, push, and open a PR back to the issue. Use this skill whenever the user points at an issue number or issue URL and wants it built: 'implement issue 289', '把 issue-289 做了', '按 issue 里说的改', '帮我实现这个 issue', '#42 这个需求你来做', 'go work on that github issue', or when they paste an issue link and ask for the code. Also trigger when the user says the requirement/备注/详情 is written in a GitHub issue rather than in chat. Do NOT use for reviewing an existing PR (use pr-reviewer) or for handling review comments left on a PR (use pr-review-resolver)."
---

# Issue Implementer

把一个 GitHub issue 从「一段文字」变成「一个可以合的 PR」。

这个流程里最容易翻车的两处，值得先说清楚：

**需求往往不在正文里。** issue 正文常常只是一句话的起点，真正的验收条件、边界情况、以及「后来又想了想改成 X」都躺在评论里。只读正文就动手，做出来的东西大概率不是用户现在要的。所以第一步就把评论全拉下来，并且以**最新的表述为准**。

**规范要从仓库里读，不要从记忆里编。** 分支名、提交信息格式、构建/测试命令、代码风格，每个仓库都不一样。照搬别的项目的习惯会让 PR 在 review 时被打回一堆格式问题。仓库自己会告诉你规矩——`CLAUDE.md`、`git log`、lint 配置都在那儿。

## Step 1 — 拉取 issue

```bash
gh issue view <编号> --json number,title,body,labels,state,url,comments
```

用户给的可能是编号、`#289`、或者完整 URL（URL 里带 owner/repo，需要加 `--repo owner/repo`）。没给编号就问，不要猜。

如果 `gh` 报 TLS / 连接超时之类的网络错误，多半是它不读系统代理，在同一条命令前面加上代理再试：

```bash
HTTPS_PROXY=http://127.0.0.1:7890 gh issue view <编号> --json number,title,body,labels,state,url,comments
```

其他常见中断情况，直接停下来告诉用户而不是绕过去：
- `gh` 未登录 → 提示 `gh auth login`
- issue 已 closed → 说明状态，问是否仍要实现
- issue 正文和评论都没有可执行的需求（只有一句「这个有问题」）→ 把已知信息列出来，问清楚再动手

读完之后，在心里把需求收敛成一句话：**改完之后，什么行为会和现在不一样。** 说不出这句话，就是还没读懂，回去重读评论。

## Step 2 — 摸清这个仓库的规矩

在写任何代码前先花两分钟搞清楚这些，后面每一步都要用：

1. **读 `CLAUDE.md`**（仓库根目录，以及改动涉及目录下的）——分支策略、提交格式、构建命令、测试命令、lint 命令、代码风格约束通常都写在这里。这是最权威的来源。
2. **`git log --oneline -20`** ——看真实的提交信息长什么样。文档写的和实际用的不一致时，以 log 为准，因为那是团队真在用的。
3. **`git fetch --all --prune && git branch -a`** ——看分支命名惯例，以及**有没有 `release-*` 这类发布分支**。这决定 Step 4 从哪儿拉分支、Step 6 往哪儿提 PR，是最值得先看清的一件事。
4. 有 `.swiftlint.yml` / `.eslintrc` / `ruff.toml` 之类的配置，记下对应的检查命令，Step 5 要跑。

CLAUDE.md 里如果写了「编码请遵守 docs 目录下的规范文档」这类指引，按它去读对应文档——那些文档往往包含这个项目踩过的坑，比你从零推断可靠得多。

## Step 3 — 出方案，等确认

这一步是整个流程的价值所在：让用户在你写完几百行之前，就发现你理解错了。

给用户一段简短的方案，包含四块：

```
## issue-<N>：<标题>
**分支**：从 <基线分支> 拉 <新分支名>，PR 提回 <基线分支>
**需求理解**：<一到三句话，说清改完之后什么行为不一样>
**改动方案**：<要动哪些文件 / 新增什么，每条一句话说清为什么>
**验证方式**：<怎么证明它真的生效——跑哪个测试、怎么手动验>
**风险与取舍**：<有歧义的地方、你做的假设、影响到的其他调用方>
```

方案要基于**真实读过的代码**，不是基于文件名的猜测。动手前先找到要改的那几个文件读一遍，确认改动点确实在那儿，以及有没有别的调用方会被波及——写完再发现改错地方，返工成本比现在读一遍高得多。

需求里有歧义时，不要沉默地挑一种实现。把歧义连同你倾向的选项一起摆出来，让用户一句话就能拍板。

**等用户确认后再进入 Step 4。** 用户说「按这个做」「可以」「go」之类即可继续；用户改了方案就按改后的来。

## Step 4 — 建分支并实现

### 从哪个分支拉

**从哪拉，就往哪合。** 基线和 PR 目标必须是同一个分支——从 `main` 拉出来却往 `release-0.22.01` 提 PR，diff 里就会混进 release 独有的提交，review 时满屏是别人的改动，也很容易在合并时炸出假冲突。

仓库存在 `release-*` 发布分支时（Step 2 已经查过），走这套三级流：

```
main ──> release-x.x.x ──> dev-YYYYMMDD-issue-N
         (从 main 拉)        (从 release 拉)
                                  │
                                  └── PR ──> release-x.x.x（回到它的基线）
```

- **dev 分支从 release 分支拉**，不从 `main` 拉。
- release 分支本身从 `main` 拉，发版后再合回 `main`——这一步通常不属于本次 issue 的范围，除非目标 release 分支还不存在，那要先问用户是否需要新建，别自作主张开一条发布分支。
- 有多个 `release-*` 时取版本号最大的那个作为基线，并在 Step 3 的方案里写明选了哪一条，让用户能一眼纠正。

拉之前先把基线同步到远端最新，否则会基于陈旧的 release 开发，PR 里带出一堆不属于你的提交：

```bash
git fetch origin
git switch -c dev-20260904-issue-289 origin/release-0.22.01
```

仓库里没有 `release-*` 分支时，基线就是默认分支（`main` / `master`），PR 也提回它。

### 分支命名

按 Step 2 摸到的惯例。常见形式：

| 仓库惯例 | 分支名示例 |
|---|---|
| `dev-YYYYMMDD-issue-N` | `dev-20260904-issue-289` |
| `feature/<描述>` | `feature/dark-mode-toggle` |
| `issue-N-<描述>` | `issue-289-fix-crash` |

看不出惯例就用 `issue-<N>-<简短英文描述>`，并在最后的汇报里说明你用了什么命名。

不要在 `main` / `master` / release 分支上直接改。如果当前工作区有未提交的改动，先停下来问用户怎么处理——替别人 stash 或丢弃改动是不可逆的。

### 实现

实现时遵守这个仓库自己的风格：命名、分层、错误处理、日志、本地化，都照周边同类文件的既有写法来。仓库里已经有的工具方法、组件、常量，优先复用而不是重写一份——重复造已存在的轮子是 review 时最常被挑出的问题。

改动范围严格对齐 issue。顺手看到的其他问题记下来，在最后的汇报里提一句，但不要塞进这个 PR——混着无关改动的 PR 很难 review，也很难回滚。

## Step 5 — 自检

提交之前，按 Step 2 记下的命令依次跑：

1. **构建** ——编译不过的 PR 是在浪费所有人的时间
2. **测试** ——跑现有测试确认没弄坏别的东西；issue 是修 bug 的话，补一个能复现这个 bug 的用例（没有这个用例，就没有任何东西能阻止它复发）
3. **lint** ——按仓库配置跑

失败就修，修完重跑。跑不动（缺环境、缺依赖、需要真机）就如实说明哪一项没验证成功以及为什么，**不要谎报通过**——一个「测试通过」的假消息，比一个诚实的「测试没跑起来」危险得多。

## Step 6 — 提交、推送、开 PR

提交信息用这个仓库的格式。从 `git log` 里看到什么就用什么，例如：

- `issue-289 修复列表滚动时的偶现崩溃`
- `feat(auth): implement JWT-based authentication`
- `fix: prevent nil deref in MemoryListCell (#289)`

改动分散在多个逻辑单元时，拆成多个提交比堆成一个更好 review。

**推送和开 PR 之前，先给用户一份摘要等确认**——PR 是对外可见的，一旦开出去就有人会收到通知。摘要包含：分支名、提交信息、改了哪些文件、自检结果。用户确认后：

```bash
git push -u origin <分支名>
gh pr create --base <基线分支> --title "issue-<N> <标题>" --body "..."
```

`--base` 就是 Step 4 拉分支时用的那条基线——有 `release-*` 时是那条 release 分支，没有才是默认分支。**不要图省事写 `main`**：dev 直接提给 `main` 会绕过发布分支的集成验证，且 PR diff 会包含 release 上已有而 main 上还没有的全部改动。

PR 正文里写上 `Closes #<N>`（或仓库惯用的关联写法），这样 PR 合并时 issue 会自动关闭，省掉一次手动收尾。

## Step 7 — 汇报

用简体中文给一份简短总结：

```
## issue-<N> 实现完成
**分支**：<分支名>
**PR**：<链接>
**改动**：<每个文件一行，说清改了什么>
**自检**：构建 ✅ / 测试 ✅ 42 passed / lint ✅（未通过的如实写明原因）
**未覆盖**：<issue 里没做的部分及原因，没有就写「无」>
**顺带发现**：<过程中看到的、不属于本次范围的问题，没有就省略>
```

「未覆盖」这一栏别省。issue 里有一条你判断不该做、或者做不了的，明说出来让用户决定，比悄悄跳过强——用户以为全做完了却发现漏了一半，是最伤信任的一种交付。
