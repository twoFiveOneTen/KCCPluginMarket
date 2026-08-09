#!/usr/bin/env python3
"""把 review 结论作为一次批量 review 提交到 PR：一条总结 + 若干行内评论。

一次 API 调用发完所有评论，PR 作者只收到一封通知，而不是每条评论一封。

输入 findings JSON:
{
  "summary": "报告总结（Markdown）",
  "comments": [
    {"path": "src/Foo.swift", "line": 42, "body": "…"},
    {"path": "src/Bar.swift", "line": 88, "start_line": 85, "body": "…"}
  ]
}

用法:
  python3 post_review.py findings.json --dry-run   # 只校验，不发布
  python3 post_review.py findings.json             # 校验并发布
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys


def load_context(path: str | None) -> dict:
    if path is None:
        git_dir = subprocess.run(
            ["git", "rev-parse", "--absolute-git-dir"], capture_output=True, text=True
        ).stdout.strip()
        path = os.path.join(git_dir or ".", "pr-review", "context.json")
    if not os.path.exists(path):
        sys.exit(f"找不到 {path}，请先运行 pr_context.py")
    with open(path) as fh:
        return json.load(fh)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("findings", help="findings JSON 文件路径")
    ap.add_argument("--context", help="context.json 路径，缺省用 <git-dir>/pr-review/context.json")
    ap.add_argument("--dry-run", action="store_true", help="只校验并打印，不实际发布")
    args = ap.parse_args()

    ctx = load_context(args.context)
    with open(args.findings) as fh:
        findings = json.load(fh)

    valid, rejected = [], []
    for c in findings.get("comments", []):
        path, line = c.get("path"), c.get("line")
        allowed = set(ctx["files"].get(path, {}).get("commentable", []))
        if not allowed:
            rejected.append((c, f"文件 {path} 不在本次 diff 中"))
            continue
        if line not in allowed:
            near = sorted(allowed, key=lambda n: abs(n - (line or 0)))[:5]
            rejected.append((c, f"{path}:{line} 不在 diff hunk 内，最近的可评论行: {sorted(near)}"))
            continue
        item = {"path": path, "line": line, "side": "RIGHT", "body": c["body"]}
        start = c.get("start_line")
        if start and start != line:
            if start not in allowed:
                rejected.append((c, f"{path} start_line={start} 不在 diff hunk 内"))
                continue
            item["start_line"], item["start_side"] = start, "RIGHT"
        valid.append(item)

    summary = findings.get("summary", "").strip()
    if rejected:
        # 定位不到 diff 行的问题不能丢——挂不上行内评论就并进总结里，
        # 否则一条真实缺陷会在这一步被静默吞掉。
        lines = ["", "---", "", "### 以下问题无法定位到本次 diff 的行上，列在这里：", ""]
        for c, why in rejected:
            body = c["body"].replace("\n", " ")
            lines.append(f"- **{c.get('path')}:{c.get('line')}** — {body}")
            lines.append(f"  <sub>（{why}）</sub>")
        summary = (summary + "\n" + "\n".join(lines)).strip()

    if not valid and not summary:
        sys.exit("没有任何可发布的内容。")

    payload = {
        "commit_id": ctx["head_sha"],
        "event": "COMMENT",  # 只评论，不做 approve / request-changes——那是人的决定
        "body": summary,
        "comments": valid,
    }

    print(f"PR #{ctx['number']} ({ctx['repo']})")
    print(f"将发布 {len(valid)} 条行内评论" + (f"，{len(rejected)} 条并入总结" if rejected else ""))
    for c in valid:
        first = c["body"].splitlines()[0] if c["body"] else ""
        print(f"  {c['path']}:{c['line']}  {first[:120]}")
    for c, why in rejected:
        print(f"  [并入总结] {c.get('path')}:{c.get('line')}  {why}")

    if args.dry_run:
        print("\n--dry-run：未发布。")
        return

    r = subprocess.run(
        ["gh", "api", f"repos/{ctx['repo']}/pulls/{ctx['number']}/reviews", "-X", "POST", "--input", "-"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    if r.returncode:
        sys.exit(f"发布失败:\n{r.stderr.strip()}\n{r.stdout.strip()}")
    print(f"\n已发布: {json.loads(r.stdout).get('html_url')}")


if __name__ == "__main__":
    main()
