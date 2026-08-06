# -*- coding: utf-8 -*-
"""把晨报的口播稿取到 public/。

口播稿由本仓库的 GitHub Actions 每天生成并 commit 进 archive/：
  archive/YYYY-MM-DD.txt / .json   当天
  archive/latest.txt   / .json     最新一期

取法有两条路，自动选：
  1. 本仓库里就有 archive/（在 Actions 里跑、或本地克隆了整个仓库）→ 直接读文件
  2. 否则回落到 GitHub API（本地只有 video/ 这个子目录时）

用法：
  python scripts/fetch_script.py            # 最新一期
  python scripts/fetch_script.py 2026-08-05 # 指定某天
"""
import base64
import json
import subprocess
import sys
from pathlib import Path

REPO = "elong007/morning-news-daily"
PUBLIC = Path(__file__).resolve().parent.parent / "public"
# video/ 的上一级就是仓库根，archive/ 在那儿
LOCAL_ARCHIVE = Path(__file__).resolve().parent.parent.parent / "archive"


def gh_file(path):
    out = subprocess.run(
        ["gh", "api", f"repos/{REPO}/contents/{path}", "-q", ".content"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.exit(f"[error] 取不到 {path}：{out.stderr.strip()[:200]}")
    return base64.b64decode(out.stdout.strip()).decode("utf-8")


def read_meta(which):
    local = LOCAL_ARCHIVE / f"{which}.json"
    if local.exists():
        print(f"[info] 读本地 {local}", file=sys.stderr)
        return json.loads(local.read_text(encoding="utf-8"))
    print("[info] 本地没有 archive/，回落 GitHub API", file=sys.stderr)
    return json.loads(gh_file(f"archive/{which}.json"))


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "latest"
    meta = read_meta(which)

    PUBLIC.mkdir(parents=True, exist_ok=True)
    (PUBLIC / "script.txt").write_text(meta["script"], encoding="utf-8")
    (PUBLIC / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # 渲染时用 --props 传进去，标题栏的日期跟着稿子走
    (PUBLIC.parent / "props.json").write_text(json.dumps({
        "audioFile": "audio.mp3",
        "captionsFile": "captions.json",
        "dateStr": meta["dateStr"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    boards = "、".join(b["name"] for b in meta["boards"])
    print(f"[done] {meta['dateStr']} · {meta['hanzi']} 汉字 · {boards} "
          f"-> public/script.txt", file=sys.stderr)


if __name__ == "__main__":
    main()
