# -*- coding: utf-8 -*-
"""算出每个板块在音频里的起始时刻，写成 public/sections.json。

数据来源是现成的两样：
  meta.json     的 sectionStarts —— DeepSeek 写稿时标出的每个板块第一句
  captions.json 的词级时间戳     —— 拼起来正好等于稿子原文（去空白后）

做法：把板块首句在稿子里的字符位置，映射到覆盖该位置的那个词，取它的 startMs。

输出 public/sections.json：
  [{"board": "国际大事", "emoji": "🌍", "startMs": 12345, "videoMs": 17345}, ...]

  startMs —— 音频内的时刻，给 NewsCrawl 用（它整个在开场卡之后的 Sequence 里，
             拿到的本来就是相对时间）
  videoMs —— 成片里的时刻 = startMs + 开场卡长度，给 YouTube 章节用

给两处用：
  * upload_youtube.py —— 生成 YouTube 章节时间轴（简介里的 "0:00 开场"）
  * NewsCrawl         —— 在对应时刻插板块卡
"""
import json
import re
import sys
from pathlib import Path

PUBLIC = Path(__file__).resolve().parent.parent / "public"

# 开场卡长度，必须和 src/NewsCrawl/Intro.tsx 里的 INTRO_FRAMES(150 帧 @30fps) 一致。
# 改了那边这里也要改，否则 YouTube 章节会整体偏移。
INTRO_MS = 5000


def squeeze(s):
    """去掉所有空白。词级 token 拼起来就是这个形态，稿子也要压成同一形态才能对位。"""
    return re.sub(r"\s+", "", s)


def build_sections():
    meta = json.loads((PUBLIC / "meta.json").read_text(encoding="utf-8"))
    captions = json.loads((PUBLIC / "captions.json").read_text(encoding="utf-8"))

    starts = meta.get("sectionStarts") or []
    if not starts:
        print("[warn] meta.json 里没有 sectionStarts，跳过", file=sys.stderr)
        return []

    emoji = {b.get("name"): b.get("emoji", "") for b in meta.get("boards", [])}
    script = squeeze(meta.get("script", ""))

    # 每个词在压缩后稿子里的起始字符位置
    offsets, pos = [], 0
    for cap in captions:
        offsets.append(pos)
        pos += len(squeeze(cap["text"]))

    def ms_at(char_pos):
        """找到覆盖这个字符位置的词，返回它的开始时间。"""
        lo, hi = 0, len(offsets) - 1
        best = 0
        while lo <= hi:
            mid = (lo + hi) // 2
            if offsets[mid] <= char_pos:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return captions[best]["startMs"]

    out = []
    for item in starts:
        board = item.get("board", "")
        key = squeeze(item.get("start", ""))
        if not key:
            continue
        idx = script.find(key)
        if idx < 0:
            print(f"[warn] 板块「{board}」的首句在稿子里找不到，跳过", file=sys.stderr)
            continue
        start_ms = ms_at(idx)
        out.append({
            "board": board,
            "emoji": emoji.get(board, ""),
            "startMs": start_ms,
            "videoMs": start_ms + INTRO_MS,
        })

    out.sort(key=lambda x: x["startMs"])
    return out


def fmt(ms):
    total = int(ms // 1000)
    return f"{total // 60}:{total % 60:02d}"


def main():
    sections = build_sections()
    (PUBLIC / "sections.json").write_text(
        json.dumps(sections, ensure_ascii=False, indent=1), encoding="utf-8")
    for s in sections:
        print(f"[info] {fmt(s['startMs']):>6}  {s['emoji']} {s['board']}", file=sys.stderr)
    print(f"[done] {len(sections)} 个板块 -> public/sections.json", file=sys.stderr)


if __name__ == "__main__":
    main()
