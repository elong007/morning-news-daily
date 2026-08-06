# -*- coding: utf-8 -*-
"""口播稿 -> 配音 MP3 + 词级时间戳字幕 JSON。

用 edge-tts 的 WordBoundary 事件直接拿时间戳，不跑 ASR：
  * 零成本、离线快（不用下 Whisper 模型）
  * 中文比 Whisper 转录准得多——时间戳来自合成器本身，不存在识别错误
  * 切分是真正的中文分词（"美联储" / "下不来" / "说白了"），做逐词高亮正好

edge-tts 7.x 默认是 SentenceBoundary，必须显式传 boundary="WordBoundary"。
词级 token 里不含标点，所以再拿原文对齐一次，把标点贴回词尾，供下游按句分页。

用法： python scripts/tts.py [voice] [rate]
输出：
  public/audio.mp3       配音
  public/captions.json   Remotion Caption[]  {text,startMs,endMs,timestampMs,confidence}
"""
import asyncio
import json
import sys
from pathlib import Path

import edge_tts

PUBLIC = Path(__file__).resolve().parent.parent / "public"
# zh-CN-YunjianNeural 男·新闻腔 / zh-CN-XiaoyiNeural 女·轻快 / zh-CN-YunxiNeural 男·轻松
VOICE = sys.argv[1] if len(sys.argv) > 1 else "zh-CN-YunjianNeural"
RATE = sys.argv[2] if len(sys.argv) > 2 else "+8%"

MAX_GAP = 8  # 两个词之间最多认领这么多字符的标点，超了说明对齐跑偏，放弃


async def synth(text):
    audio = bytearray()
    captions = []
    comm = edge_tts.Communicate(text, VOICE, rate=RATE, boundary="WordBoundary")
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            # offset / duration 单位是 100 纳秒
            start_ms = chunk["offset"] / 10_000
            end_ms = (chunk["offset"] + chunk["duration"]) / 10_000
            captions.append({
                "text": chunk["text"],
                "startMs": round(start_ms),
                "endMs": round(end_ms),
                "timestampMs": round((start_ms + end_ms) / 2),
                "confidence": None,
            })
    return bytes(audio), captions


def attach_punctuation(text, captions):
    """把原文里夹在词之间的标点，贴到前一个词的末尾。"""
    i = 0
    attached = 0
    for idx, cap in enumerate(captions):
        w = cap["text"]
        j = text.find(w, i)
        if j < 0:
            continue
        gap = text[i:j].strip()
        if gap and idx > 0 and len(gap) <= MAX_GAP:
            captions[idx - 1]["text"] += gap
            attached += 1
        i = j + len(w)
    tail = text[i:].strip()
    if tail and captions and len(tail) <= MAX_GAP:
        captions[-1]["text"] += tail
        attached += 1
    return attached


def main():
    script_path = PUBLIC / "script.txt"
    if not script_path.exists():
        sys.exit(f"[error] 缺少 {script_path}，先把口播稿写进去")
    text = script_path.read_text(encoding="utf-8").strip()
    if not text:
        sys.exit("[error] script.txt 是空的")

    audio, captions = asyncio.run(synth(text))
    if not captions:
        sys.exit("[error] edge-tts 没返回 WordBoundary，换个 voice 再试")
    attached = attach_punctuation(text, captions)

    (PUBLIC / "audio.mp3").write_bytes(audio)
    (PUBLIC / "captions.json").write_text(
        json.dumps(captions, ensure_ascii=False, indent=1), encoding="utf-8")

    dur = captions[-1]["endMs"] / 1000
    print(f"[done] {len(text)} 字 -> {len(captions)} 个词, 贴回 {attached} 处标点, "
          f"音频 {dur:.0f}s ({dur/60:.1f} 分钟), voice={VOICE} rate={RATE}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
