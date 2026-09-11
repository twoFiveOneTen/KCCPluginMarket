#!/usr/bin/env python3
"""收集 release 分支相对基线分支（main/master）的改动，按 issue 归并后打印。

给写 App Store 更新说明用：把散落的 commit 收拢到 issue 维度，带上 issue 的
标题、标签和正文，这样判断「这算不算一个用户看得见的新功能」才有依据。
gh 取不到 issue 时自动降级为只看 commit，不会中断。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter

ISSUE_RE = re.compile(r"(?:issue[-_ ]?|#)(\d+)", re.I)
CLOSES_RE = re.compile(r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", re.I)
BODY_LIMIT = 600


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def git(*args: str) -> str:
    p = run(["git", *args])
    if p.returncode != 0:
        sys.exit(f"git 命令失败: git {' '.join(args)}\n{p.stderr.strip()}")
    return p.stdout.strip()


def pick_release(explicit: str | None) -> str:
    if explicit:
        return explicit
    current = git("rev-parse", "--abbrev-ref", "HEAD")
    if current.startswith("release-"):
        return current
    refs = git(
        "for-each-ref", "--sort=-committerdate", "--format=%(refname:short)",
        "refs/heads/release-*", "refs/remotes/*/release-*",
    ).splitlines()
    if refs:
        return refs[0].strip()
    sys.exit("没找到 release- 开头的分支，用 --release 指定要发布的分支")


def pick_base(explicit: str | None) -> str:
    if explicit:
        return explicit
    for candidate in ("main", "master", "origin/main", "origin/master"):
        if run(["git", "rev-parse", "--verify", "--quiet", candidate]).returncode == 0:
            return candidate
    sys.exit("没找到 main/master 基线分支，用 --base 指定")


def fetch_issue(number: str) -> dict | None:
    p = run(["gh", "issue", "view", number, "--json", "number,title,labels,body,url"])
    if p.returncode != 0:
        return None
    try:
        data = json.loads(p.stdout)
    except json.JSONDecodeError:
        return None
    body = (data.get("body") or "").strip()
    return {
        "title": data.get("title", ""),
        "labels": [label["name"] for label in data.get("labels", [])],
        "body": body[:BODY_LIMIT] + ("……（正文已截断）" if len(body) > BODY_LIMIT else ""),
        # commit 里写的 #N 常常是 PR 号；gh issue view 对 PR 也会返回内容，
        # 不点破的话会被当成一个独立的新功能重复计一条
        "kind": "PR" if "/pull/" in data.get("url", "") else "issue",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", help="要发布的分支，默认取当前 release-* 分支或最近更新的那个")
    parser.add_argument("--base", help="基线分支，默认 main/master")
    parser.add_argument("--no-issues", action="store_true", help="跳过 gh，只看 commit")
    args = parser.parse_args()

    release = pick_release(args.release)
    base = pick_base(args.base)
    if run(["git", "rev-parse", "--verify", "--quiet", release]).returncode != 0:
        sys.exit(f"分支不存在: {release}")

    raw = git("log", "--no-merges", "--format=%h%x1f%s", f"{base}..{release}")
    commits = [line.split("\x1f", 1) for line in raw.splitlines() if "\x1f" in line]
    if not commits:
        sys.exit(f"{base}..{release} 之间没有提交，确认分支是否正确、是否需要先 git fetch")

    # 按 issue 归并；一条 commit 提到多个 issue 就都归进去，宁可重复也别漏
    grouped: dict[str, list[str]] = {}
    orphans: list[str] = []
    for sha, subject in commits:
        numbers = ISSUE_RE.findall(subject)
        if numbers:
            for number in numbers:
                grouped.setdefault(number, []).append(f"{sha} {subject}")
        else:
            orphans.append(f"{sha} {subject}")

    issues = {}
    gh_failed = []
    if not args.no_issues:
        for number in sorted(grouped, key=int, reverse=True):
            info = fetch_issue(number)
            if info:
                issues[number] = info
            else:
                gh_failed.append(number)

    # PR 号大多躺在 merge commit 里，被 --no-merges 滤掉了；漏进来的是有人手写
    # 「处理 PR #297 评审意见」这类提交。它和自己实现的 issue 会各占一节、提交重复列两遍，
    # 所以认 Closes/Fixes #N 把 PR 正文并到那个 issue 下当实现说明。没关联 issue 的 PR 才独立成节。
    for number in [n for n, i in issues.items() if i["kind"] == "PR"]:
        targets = [n for n in CLOSES_RE.findall(issues[number]["body"]) if n in issues]
        if not targets:
            continue
        for target in targets:
            issues[target].setdefault("prs", []).append((number, issues[number]["body"]))
            for commit in grouped.get(number, []):
                if commit not in grouped[target]:
                    grouped[target].append(commit)
        del issues[number]
        grouped.pop(number, None)

    version = re.search(r"(\d+(?:\.\d+)+)", release)
    files = git("diff", "--name-only", f"{base}...{release}").splitlines()
    dirs = Counter("/".join(f.split("/")[:3]) for f in files if f)

    out = [
        f"# 发布说明素材：{version.group(1) if version else release}",
        "",
        f"发布分支：`{release}`   基线：`{base}`   提交：{len(commits)} 条（已排除 merge）",
        f"关联 issue：{len(grouped)} 个   改动文件：{len(files)} 个",
        "",
    ]

    if gh_failed:
        out += [
            f"> ⚠️ 以下 issue 用 gh 取不到，只能凭 commit 判断：{', '.join('#' + n for n in gh_failed)}",
            "> GitHub 需要走代理时，在命令前加 `HTTPS_PROXY=http://127.0.0.1:7890`；"
            "未登录则先 `gh auth login`。",
            "",
        ]

    for number in sorted(grouped, key=int, reverse=True):
        info = issues.get(number)
        if info:
            labels = f"  [{', '.join(info['labels'])}]" if info["labels"] else ""
            out.append(f"## {info['kind']} #{number} — {info['title']}{labels}")
            if info["kind"] == "PR":
                out.append("（这是 PR 不是 issue：正文是某个 issue 的实现说明，"
                           "合并到对应 issue 理解，别单独算一条）")
            if info["body"]:
                out += ["", "> " + info["body"].replace("\n", "\n> ")]
        else:
            out.append(f"## issue #{number} — （详情不可用）")
        for pr_number, pr_body in (info or {}).get("prs", []):
            out += ["", f"实现说明（PR #{pr_number}）：", "", "> " + pr_body.replace("\n", "\n> ")]
        out += ["", f"相关提交（{len(grouped[number])}）："]
        out += [f"- {c}" for c in grouped[number]]
        out.append("")

    if orphans:
        out += [f"## 未关联 issue 的提交（{len(orphans)}）", ""]
        out += [f"- {c}" for c in orphans]
        out.append("")

    out += ["## 改动分布（按目录，取前 12）", ""]
    out += [f"- {d or '<根目录>'}: {n} 个文件" for d, n in dirs.most_common(12)]

    print("\n".join(out))


if __name__ == "__main__":
    main()
