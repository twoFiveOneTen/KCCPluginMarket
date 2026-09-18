#!/usr/bin/env python3
"""按 issue 号找到对应的开发分支，输出「这个 issue 实际做了什么」的素材。

写 issue 实现说明时最容易错的一步是 diff 范围：拿 main 当基线，diff 里会混进
release 分支上别人的提交，于是实现说明里多出一堆不属于这个 issue 的东西。
所以这里按三档依次尝试确定范围，并在输出里写明用了哪一档，方便人工纠正：

  1. PR 的 base 分支（最可靠，开 PR 时就声明了基线）
  2. 候选基线里「分支独有提交最少」的那个（从哪拉的，独有的就只有自己那些提交）
  3. 分支上 commit 信息匹配 issue-N 的提交集合（分支已合并进基线时只剩这条路）

拿到范围后由调用方自己 git diff 读关键文件——哪些文件值得细读是判断问题，
脚本替不了。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter

BODY_LIMIT = 4000


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def git(*args: str) -> str:
    p = run(["git", *args])
    if p.returncode != 0:
        sys.exit(f"git 命令失败: git {' '.join(args)}\n{p.stderr.strip()}")
    return p.stdout.strip()


def git_ok(*args: str) -> bool:
    return run(["git", *args]).returncode == 0


def gh_json(args: list[str]) -> dict | list | None:
    """gh 取不到就返回 None：没网 / 没登录 / 对象不存在都不该中断整个流程。"""
    p = run(["gh", *args])
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return None


def find_branches(number: str) -> list[str]:
    """找分支名里带这个 issue 号的分支。

    用词边界匹配：issue-29 不能匹配到 issue-296，否则会拿错分支算出一份
    看起来合理、实际张冠李戴的实现说明。
    """
    refs = git(
        "for-each-ref", "--sort=-committerdate", "--format=%(refname:short)",
        "refs/heads/", "refs/remotes/",
    ).splitlines()
    pattern = re.compile(rf"(?:issue[-_]?|#){number}(?!\d)", re.I)
    hits, seen = [], set()
    for ref in refs:
        name = ref.strip()
        if not pattern.search(name):
            continue
        # 本地和远端同名分支算一个（for-each-ref 已按提交时间排序，本地的通常先到）
        key = re.sub(r"^[^/]+/", "", name) if "/" in name else name
        if key in seen:
            continue
        seen.add(key)
        hits.append(name)
    return hits


def baseline_candidates() -> list[str]:
    refs = git(
        "for-each-ref", "--sort=-refname", "--format=%(refname:short)",
        "refs/heads/release-*", "refs/remotes/*/release-*",
    ).splitlines()
    out = [r.strip() for r in refs if r.strip()]
    for name in ("main", "master", "origin/main", "origin/master"):
        if git_ok("rev-parse", "--verify", "--quiet", name):
            out.append(name)
    return out


def resolve_range(branch: str, number: str, pr_base: str | None) -> tuple[str, str, str]:
    """返回 (起点 sha, 说明, 用了哪一档)。起点是分叉点，配 branch 组成 diff 范围。"""
    if pr_base:
        for ref in (pr_base, f"origin/{pr_base}"):
            if git_ok("rev-parse", "--verify", "--quiet", ref):
                base = run(["git", "merge-base", ref, branch])
                if base.returncode == 0:
                    sha = base.stdout.strip()
                    # 分支已合并进基线时 merge-base 就是分支 tip，范围会空掉
                    if git("rev-list", "--count", f"{sha}..{branch}") != "0":
                        return sha, f"PR 的 base 分支 `{ref}`", "pr-base"

    best: tuple[int, str, str] | None = None
    for cand in baseline_candidates():
        base = run(["git", "merge-base", cand, branch])
        if base.returncode != 0:
            continue
        sha = base.stdout.strip()
        count = int(git("rev-list", "--count", f"{sha}..{branch}") or 0)
        if count == 0:  # 分支已并入这条候选，它不是分叉点
            continue
        if best is None or count < best[0]:
            best = (count, sha, cand)
    if best:
        return best[1], f"候选基线 `{best[2]}`（分支独有 {best[0]} 条提交，最少）", "merge-base"

    # 分支已经合并进所有基线：只能靠 commit 信息把这个 issue 的提交圈出来
    # 用 ([^0-9]|$) 而不是 \b：git 的 ERE 不保证支持 \b，而这里恰恰最怕 issue-29 吃进 issue-296
    shas = git("log", "--format=%H", f"--grep=issue[-_ ]?{number}([^0-9]|$)",
               "--extended-regexp", "-i", branch).splitlines()
    if shas:
        oldest = shas[-1]
        if git_ok("rev-parse", "--verify", "--quiet", f"{oldest}^"):
            return git("rev-parse", f"{oldest}^"), \
                f"commit 信息匹配 issue-{number} 的最早一条提交之前（分支似乎已合并）", "grep"
    sys.exit(
        f"无法确定 `{branch}` 的分叉点。先 `git fetch --all --prune` 再试；"
        f"仍然不行就用 --base 显式指定基线分支。"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("issue", help="issue 编号")
    parser.add_argument("--branch", help="开发分支，默认按 issue 号在分支名里搜")
    parser.add_argument("--base", help="基线分支，指定后跳过自动推断")
    parser.add_argument("--repo", help="owner/repo，跨仓库查 issue 时用")
    args = parser.parse_args()

    number = args.issue.lstrip("#")
    repo_args = ["--repo", args.repo] if args.repo else []

    branches = [args.branch] if args.branch else find_branches(number)
    if not branches:
        sys.exit(
            f"没找到分支名里带 issue-{number} 的分支。先 `git fetch --all --prune`；"
            f"分支名不含 issue 号时用 --branch 指定。"
        )
    branch = branches[0]
    if not git_ok("rev-parse", "--verify", "--quiet", branch):
        sys.exit(f"分支不存在: {branch}。`git branch -a` 看看实际叫什么，"
                 f"远端分支本地没有时先 `git fetch --all --prune`。")

    issue = gh_json(["issue", "view", number, *repo_args, "--json",
                     "number,title,body,labels,state,url,comments"])

    # 一条分支上可能开过多个 PR（分批提交、返工后重开），每个 PR 的正文都是实现说明的一部分
    prs = gh_json(["pr", "list", *repo_args, "--head", branch.split("/")[-1],
                   "--state", "all", "--json",
                   "number,title,body,state,baseRefName,url", "--limit", "10"]) or []
    pr = prs[0] if prs else None

    if args.base:
        sha = git("merge-base", args.base, branch)
        how, tier = f"命令行指定的 `{args.base}`", "explicit"
    else:
        sha, how, tier = resolve_range(branch, number, pr.get("baseRefName") if pr else None)

    rng = f"{sha}..{branch}"
    commits = git("log", "--no-merges", "--format=%h %s", rng).splitlines()
    files = [f for f in git("diff", "--name-only", rng).splitlines() if f]
    stat = git("diff", "--stat", rng).splitlines()

    out = [f"# issue #{number} 的实际改动素材", ""]
    if issue:
        out += [f"**标题**：{issue.get('title', '')}",
                f"**状态**：{issue.get('state', '')}   "
                f"**标签**：{', '.join(l['name'] for l in issue.get('labels', [])) or '无'}",
                f"**链接**：{issue.get('url', '')}", ""]
    else:
        out += ["> ⚠️ gh 取不到 issue 详情。需要代理时在命令前加 "
                "`HTTPS_PROXY=http://127.0.0.1:7890`；未登录先 `gh auth login`。", ""]

    out += [f"**开发分支**：`{branch}`", f"**分叉点**：`{sha[:12]}`（来源：{how}）",
            f"**diff 范围**：`{rng}`   提交 {len(commits)} 条   改动文件 {len(files)} 个", ""]
    if len(branches) > 1:
        out += [f"> ⚠️ 还有其他同号分支：{', '.join('`' + b + '`' for b in branches[1:])}。"
                f"用了第一个（最近提交的）；如果不对用 --branch 换。", ""]
    if tier == "grep":
        out += ["> ⚠️ 分支已合并进基线，范围是按 commit 信息圈出来的。"
                "如果这条分支上混有别的 issue 的提交，需要人工核对。", ""]

    if issue:
        body = (issue.get("body") or "").strip()
        out += ["## issue 正文（原文，逐字保留用）", "", "```markdown", body or "（空）", "```", ""]
        comments = issue.get("comments") or []
        if comments:
            out += [f"## issue 评论（{len(comments)} 条，需求常在这里被改）", ""]
            for c in comments:
                text = (c.get("body") or "").strip()[:BODY_LIMIT]
                out += [f"- **{c.get('author', {}).get('login', '?')}**："
                        f"{text.replace(chr(10), ' ')}"]
            out.append("")

    for item in prs:
        out += [f"## PR #{item['number']} — {item['title']}"
                f"（{item['state']}，base `{item['baseRefName']}`）", "", item.get("url", ""), ""]
        pr_body = (item.get("body") or "").strip()
        if pr_body:
            out += ["> " + pr_body[:BODY_LIMIT].replace("\n", "\n> "), ""]

    out += [f"## 提交（{len(commits)} 条，按时间倒序）", ""]
    out += [f"- {c}" for c in commits] or ["（无）"]
    out += ["", "## 改动文件（diffstat）", "", "```"] + stat + ["```", ""]

    dirs = Counter("/".join(f.split("/")[:3]) for f in files)
    out += ["## 改动分布（按目录，取前 12）", ""]
    out += [f"- {d or '<根目录>'}: {n} 个文件" for d, n in dirs.most_common(12)]
    out += ["", f"下一步：`git diff {rng} -- <文件>` 逐个读关键文件的最终改动。"]

    print("\n".join(out))


if __name__ == "__main__":
    main()
