#!/usr/bin/env python3
"""一次性收集 review 一个 GitHub PR 所需的全部上下文。

产出:
  <git-dir>/pr-review/context.json  - PR 元信息、每个文件可评论的行号、已有评论
  <git-dir>/pr-review/pr.diff       - 完整 diff，供 agent 用 Read 工具阅读

用法:
  python3 pr_context.py            # 当前分支对应的 PR
  python3 pr_context.py 42         # 指定 PR 号
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def gh(args: list[str], check: bool = True) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f"gh {' '.join(args)} 失败:\n{r.stderr.strip()}")
    return r.stdout


def gh_json_lines(path: str) -> list[dict]:
    """分页拉取一个返回数组的 API，逐行解析（兼容较老版本的 gh）。"""
    out = gh(["api", path, "--paginate", "--jq", ".[]"], check=False)
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def parse_diff(diff: str) -> dict:
    """解析统一 diff，得到每个文件在 RIGHT 侧可被评论的行号。

    GitHub 只允许把行内评论挂在 diff hunk 内出现过的行上（新增行和上下文行都行）。
    挂到 hunk 之外的行会直接被 API 以 422 拒绝，所以先把合法行集合算出来。
    """
    files: dict[str, dict] = {}
    path: str | None = None
    newline = 0
    in_hunk = False

    for raw in diff.splitlines():
        if raw.startswith("diff --git"):
            path, in_hunk = None, False
            continue

        m = HUNK.match(raw)
        if m:
            newline, in_hunk = int(m.group(1)), True
            continue

        if not in_hunk:
            # 文件头部分：+++ b/path 给出新文件路径；/dev/null 表示这是删除的文件
            if raw.startswith("+++ "):
                p = raw[4:].strip()
                path = None if p == "/dev/null" else (p[2:] if p.startswith("b/") else p)
                if path:
                    files.setdefault(path, {"added": [], "commentable": []})
            continue

        if path is None:
            continue

        f = files[path]
        if raw.startswith("+"):
            f["added"].append(newline)
            f["commentable"].append(newline)
            newline += 1
        elif raw.startswith("-") or raw.startswith("\\"):
            pass  # 删除行不占新文件行号；"\ No newline at end of file" 同理
        else:
            f["commentable"].append(newline)
            newline += 1

    return files


def compress(nums: list[int]) -> str:
    """把行号列表压成 "3-8,12,20-25"，避免打印几千个数字刷屏。"""
    if not nums:
        return "-"
    nums = sorted(set(nums))
    parts, start, prev = [], nums[0], nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        parts.append(f"{start}-{prev}" if start != prev else str(start))
        start = prev = n
    parts.append(f"{start}-{prev}" if start != prev else str(start))
    return ",".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pr", nargs="?", help="PR 号，缺省时使用当前分支关联的 PR")
    args = ap.parse_args()

    fields = "number,title,url,headRefName,baseRefName,headRefOid,author,isDraft,additions,deletions"
    view = ["pr", "view", "--json", fields]
    if args.pr:
        view.insert(2, args.pr)
    pr = json.loads(gh(view))
    repo = json.loads(gh(["repo", "view", "--json", "nameWithOwner"]))["nameWithOwner"]
    num = pr["number"]

    diff = gh(["pr", "diff", str(num)])
    files = parse_diff(diff)

    base = f"repos/{repo}/pulls/{num}"
    inline = [
        {
            "author": (c.get("user") or {}).get("login"),
            "path": c.get("path"),
            # position 为 null 说明这条评论已经 outdated（它锚定的那段代码被后续提交改掉了）
            "line": c.get("line") or c.get("original_line"),
            "outdated": c.get("position") is None,
            "is_reply": c.get("in_reply_to_id") is not None,
            "body": (c.get("body") or "").strip(),
            "url": c.get("html_url"),
        }
        for c in gh_json_lines(f"{base}/comments")
    ]
    review_bodies = [
        {"author": (r.get("user") or {}).get("login"), "state": r.get("state"), "body": (r.get("body") or "").strip()}
        for r in gh_json_lines(f"{base}/reviews")
        if (r.get("body") or "").strip()
    ]

    git_dir = subprocess.run(
        ["git", "rev-parse", "--absolute-git-dir"], capture_output=True, text=True
    ).stdout.strip()
    out_dir = os.path.join(git_dir or ".", "pr-review")
    os.makedirs(out_dir, exist_ok=True)
    ctx_path = os.path.join(out_dir, "context.json")
    diff_path = os.path.join(out_dir, "pr.diff")

    ctx = {
        "repo": repo,
        "number": num,
        "title": pr["title"],
        "url": pr["url"],
        "head_sha": pr["headRefOid"],
        "head_ref": pr["headRefName"],
        "base_ref": pr["baseRefName"],
        "author": (pr.get("author") or {}).get("login"),
        "is_draft": pr.get("isDraft"),
        "additions": pr.get("additions"),
        "deletions": pr.get("deletions"),
        "files": files,
        "existing_comments": inline,
        "review_bodies": review_bodies,
    }
    with open(ctx_path, "w") as fh:
        json.dump(ctx, fh, ensure_ascii=False, indent=2)
    with open(diff_path, "w") as fh:
        fh.write(diff)

    print(f"PR #{num} {pr['title']}")
    print(f"仓库: {repo}   分支: {pr['headRefName']} → {pr['baseRefName']}")
    print(f"作者: @{(pr.get('author') or {}).get('login')}   草稿: {pr.get('isDraft')}")
    print(f"改动: {len(files)} 个文件, +{pr.get('additions')} −{pr.get('deletions')}")
    print(f"{pr['url']}\n")

    print("可评论行（只有这些行能挂行内评论）:")
    for p, f in files.items():
        print(f"  {p}\n    新增: {compress(f['added'])}\n    可评论: {compress(f['commentable'])}")

    print(f"\n已有行内评论: {len(inline)} 条")
    for c in inline:
        flags = "".join(["[已过期]" if c["outdated"] else "", "[回复]" if c["is_reply"] else ""])
        body = c["body"].replace("\n", " ")
        print(f"  @{c['author']} {c['path']}:{c['line']} {flags}")
        print(f"    {body[:300]}{'…' if len(body) > 300 else ''}")

    if review_bodies:
        print(f"\n已有 review 总结: {len(review_bodies)} 条")
        for r in review_bodies:
            body = r["body"].replace("\n", " ")
            print(f"  @{r['author']} ({r['state']}): {body[:300]}{'…' if len(body) > 300 else ''}")

    print(f"\ncontext.json → {ctx_path}")
    print(f"diff → {diff_path}")


if __name__ == "__main__":
    main()
