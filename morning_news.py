# -*- coding: utf-8 -*-
"""每日晨报 · 云端版（GitHub Actions 上运行，海外网络直连，无需代理）

流程：抓取西方主流媒体 RSS → DeepSeek 挑选/翻译/写中文摘要 → 推送 Telegram。
四个板块：world / finance / tech / china，每板块 10 条。

需要的环境变量（GitHub Secrets）：
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DEEPSEEK_API_KEY
"""
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
CUTOFF = datetime.now(timezone.utc) - timedelta(hours=28)
MAX_PER_CAT = 28          # 每板块交给 DeepSeek 的候选上限
PICK = 10                 # 每板块最终挑选条数

DEEPSEEK_KEY = os.environ["DEEPSEEK_API_KEY"]
TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TG_CHAT = os.environ["TELEGRAM_CHAT_ID"]
# 口播稿转音频用的语音；可用 TTS_VOICE 环境变量覆盖。常用中文：
# zh-CN-XiaoyiNeural(女·轻快活泼)  zh-CN-XiaoxiaoNeural(女·温暖自然)
# zh-CN-YunxiNeural(男·轻松活泼)  zh-CN-YunjianNeural(男·新闻腔)
TTS_VOICE = os.environ.get("TTS_VOICE", "zh-CN-XiaoyiNeural")

FEEDS = json.loads((Path(__file__).parent / "feeds.json").read_text(encoding="utf-8"))["feeds"]

BOARD_META = {
    "world":   ("🌍", "国际大事"),
    "finance": ("💰", "财经要闻"),
    "crypto":  ("🪙", "数字货币"),
    "tech":    ("💻", "科技动态"),
    "ai":      ("🤖", "AI 前沿"),
    "china":   ("🇨🇳", "中国相关"),
}

CHINA_RE = re.compile(
    r"\b(china|chinese|beijing|shanghai|shenzhen|hong ?kong|taiwan|taipei|"
    r"xi jinping|xinjiang|tibet|macau|yuan|renminbi|huawei|tiktok|bytedance|"
    r"alibaba|tencent|byd|xiaomi|deepseek|tsmc|pboc)\b", re.IGNORECASE)

AI_RE = re.compile(
    r"\b(ai|a\.i\.|artificial intelligence|machine learning|deep learning|"
    r"generative|chatgpt|openai|anthropic|claude|gemini|llm|large language model|"
    r"deepmind|copilot|midjourney|stable diffusion|hugging ?face|neural network|"
    r"chatbot|agentic|gpt-?\d)\b", re.IGNORECASE)

CRYPTO_RE = re.compile(
    r"\b(crypto|cryptocurrenc(y|ies)|bitcoin|btc|ethereum|blockchain|stablecoin|"
    r"defi|coinbase|binance|ripple|xrp|solana|dogecoin|memecoin|altcoin|web3|"
    r"tether|usdt|usdc|nft)\b", re.IGNORECASE)


# ---------- 抓取 ----------
def strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()[:400]


def parse_date(s):
    if not s:
        return None
    try:
        return parsedate_to_datetime(s)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except Exception as e:
            if attempt == 2:
                print(f"[warn] fetch {url}: {e}", file=sys.stderr)
                return None
            time.sleep(2 * (attempt + 1))


def fetch_feed(feed):
    data = http_get(feed["url"])
    if not data:
        return []
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        print(f"[warn] parse {feed['name']}: {e}", file=sys.stderr)
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    raw = []
    for it in root.iter("item"):  # RSS 2.0
        raw.append((
            (it.findtext("title") or "").strip(),
            (it.findtext("link") or "").strip(),
            parse_date(it.findtext("pubDate")),
            strip_html(it.findtext("description")),
        ))
    if not raw:  # RSS 1.0 / RDF (DW)
        rss1 = "{http://purl.org/rss/1.0/}"
        dc = "{http://purl.org/dc/elements/1.1/}"
        for it in root.iter(f"{rss1}item"):
            raw.append((
                (it.findtext(f"{rss1}title") or "").strip(),
                (it.findtext(f"{rss1}link") or "").strip(),
                parse_date(it.findtext(f"{dc}date")),
                strip_html(it.findtext(f"{rss1}description")),
            ))
    if not raw:  # Atom
        for it in root.iter("{http://www.w3.org/2005/Atom}entry"):
            link_el = it.find("atom:link[@rel='alternate']", ns) or it.find("atom:link", ns)
            raw.append((
                (it.findtext("atom:title", namespaces=ns) or "").strip(),
                link_el.get("href", "") if link_el is not None else "",
                parse_date(it.findtext("atom:published", namespaces=ns)
                           or it.findtext("atom:updated", namespaces=ns)),
                strip_html(it.findtext("atom:summary", namespaces=ns) or ""),
            ))

    out = []
    for title, link, pub, desc in raw[:60]:
        if not title or not link:
            continue
        if pub is not None:
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            if pub < CUTOFF:
                continue
        out.append({"title": title, "link": clean_link(link),
                    "pubDate": pub.isoformat() if pub else "", "desc": desc})
        if len(out) >= 40:
            break
    return out


def clean_link(link):
    return re.sub(r"[?&](at_medium|at_campaign|mod|utm_[a-z]+)=[^&]*", "", link).rstrip("?&")


def norm_title(t):
    return re.sub(r"[^a-z0-9一-鿿]+", "", t.lower())[:60]


def collect():
    uniq = {}
    for feeds in FEEDS.values():
        for feed in feeds:
            uniq.setdefault(feed["url"], {"name": feed["name"], "url": feed["url"]})
    with ThreadPoolExecutor(max_workers=8) as ex:
        raw_lists = list(ex.map(fetch_feed, uniq.values()))
    cache = {c["url"]: items for c, items in zip(uniq.values(), raw_lists)}

    result = {}
    for cat, feeds in FEEDS.items():
        lists = []
        for feed in feeds:
            raw = cache.get(feed["url"], []) or []
            tagged = []
            for it in raw:
                if feed.get("china_filter") and not CHINA_RE.search(it["title"] + " " + it["desc"]):
                    continue
                tagged.append(dict(it, source=feed["name"]))
                if len(tagged) >= 15:
                    break
            lists.append(tagged)
        merged, seen = [], set()
        for i in range(15):
            for lst in lists:
                if i < len(lst):
                    k = norm_title(lst[i]["title"])
                    if k and k not in seen:
                        seen.add(k)
                        merged.append(lst[i])
        result[cat] = merged[:MAX_PER_CAT]
        ok = sum(1 for f in feeds if cache.get(f["url"]))
        print(f"[info] {cat}: {len(result[cat])} candidates from {ok}/{len(feeds)} feeds", file=sys.stderr)

    # 数字货币归位：把「财经」板块里的加密货币相关条目移进「数字货币」板块，
    # 财经板块只留非币圈内容，避免重复。
    if "crypto" in result and "finance" in result:
        ck = {norm_title(x["title"]) for x in result["crypto"]}
        kept, moved = [], 0
        for it in result["finance"]:
            if CRYPTO_RE.search(it["title"] + " " + it["desc"]):
                k = norm_title(it["title"])
                if k not in ck:
                    ck.add(k)
                    result["crypto"].append(it)
                moved += 1
            else:
                kept.append(it)
        result["finance"] = kept
        result["crypto"] = result["crypto"][:MAX_PER_CAT + 8]
        print(f"[info] moved {moved} crypto items finance→crypto; finance now {len(result['finance'])}", file=sys.stderr)

    # AI 归位：把「科技」板块里的 AI 相关条目移进「AI」板块，科技板块只留非 AI，
    # 避免同一 AI 报道在两个板块重复出现（财经/国际的 AI 话题保留原板块）。
    if "ai" in result and "tech" in result:
        ai_keys = {norm_title(x["title"]) for x in result["ai"]}
        kept, moved = [], 0
        for it in result["tech"]:
            if AI_RE.search(it["title"] + " " + it["desc"]):
                k = norm_title(it["title"])
                if k not in ai_keys:
                    ai_keys.add(k)
                    result["ai"].append(it)
                moved += 1
            else:
                kept.append(it)
        result["tech"] = kept
        result["ai"] = result["ai"][:MAX_PER_CAT + 8]
        print(f"[info] moved {moved} AI items tech→ai; tech now {len(result['tech'])}", file=sys.stderr)

    if "china" in result:
        cseen = {norm_title(x["title"]) for x in result["china"]}
        for cat in result:
            if cat == "china":
                continue
            for it in result[cat]:
                k = norm_title(it["title"])
                if CHINA_RE.search(it["title"] + " " + it["desc"]) and k not in cseen:
                    cseen.add(k)
                    result["china"].append(it)
        result["china"] = result["china"][:MAX_PER_CAT + 8]
    return result


# ---------- DeepSeek 挑选+翻译 ----------
def deepseek_pick(cat_name, candidates):
    numbered = [
        {"i": i, "title": c["title"], "source": c["source"],
         "desc": c["desc"][:220], "link": c["link"]}
        for i, c in enumerate(candidates)
    ]
    sys_prompt = (
        "你是一位资深中文新闻编辑。给你一批英文新闻候选，请挑选最重要、最有信息量的 "
        f"{PICK} 条，翻译成中文。规则："
        "①优先重大新闻（政策、冲突、市场变动、重要公司/产品动态），"
        "跳过购物指南、促销折扣、消费测评（Best/Deals/Review类）、软文和标题党；"
        "②同一事件只保留一条；③来源尽量多样，不要单一媒体占比过高；"
        "④中文标题信达雅，摘要1-2句、基于原文提炼、不要编造细节。"
        "只返回 JSON：{\"items\":[{\"zh_title\":\"..\",\"zh_summary\":\"..\",\"source\":\"..\",\"link\":\"..\"}]}，"
        f"最多 {PICK} 条，source 和 link 必须原样复制候选里的值。"
    )
    user_prompt = f"板块：{cat_name}\n候选新闻（JSON）：\n{json.dumps(numbered, ensure_ascii=False)}"
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "system", "content": sys_prompt},
                     {"role": "user", "content": user_prompt}],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {DEEPSEEK_KEY}"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                out = json.loads(resp.read())
            content = out["choices"][0]["message"]["content"]
            items = json.loads(content).get("items", [])
            return items[:PICK]
        except Exception as e:
            print(f"[warn] deepseek {cat_name} attempt {attempt}: {e}", file=sys.stderr)
            if attempt == 2:
                return []
            time.sleep(5)


# ---------- 口播稿 ----------
def deepseek_broadcast(picked, date_str):
    """picked: [(cat, [items...]), ...]，items 已翻译好。返回一整篇可朗读的中文口播稿纯文本。"""
    boards = []
    for cat, items in picked:
        boards.append({
            "板块": BOARD_META[cat][1],
            "新闻": [{"标题": it.get("zh_title", ""), "摘要": it.get("zh_summary", ""),
                     "来源": it.get("source", "")} for it in items],
        })
    sys_prompt = (
        "你是一位风格轻松亲切的早间新闻主播。根据给定的、已翻译成中文的新闻，撰写一篇连贯、"
        "适合朗读的中文新闻口播稿。要求："
        f"①开场用轻松的问候语，自然带出今天是{date_str}，欢迎收听每日新闻晨报；"
        "②按给定板块顺序播报，每个板块用自然口语化的过渡语引入（如'先看看国际上发生了什么'、"
        "'再来聊聊财经'、'数字货币这边'、'科技圈'、'AI方面'、'最后说说和中国有关的'）；"
        "③根据新闻重要性分配篇幅：重大新闻展开2-3句讲清楚，次要新闻一句带过、或把同类的合并着说，"
        "不重要的可以略过不播；来源自然融入（如'据路透社报道'、'《金融时报》说'）；"
        "④全文严格控制在1500到1800个汉字之间（宁短勿长，务必不超过1800字），"
        "语气轻松自然、像朋友聊天，不要严肃的播音腔；"
        "⑤绝对不要出现编号、网址链接、Markdown符号（*#等）、括号备注；用中文全角标点；"
        "⑥段落之间空一行；⑦结尾用轻松的话收尾并预告明天再会。"
        "直接输出口播稿正文，不要任何前后说明。"
    )
    user_prompt = "新闻内容（JSON，按此顺序播报）：\n" + json.dumps(boards, ensure_ascii=False)
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "system", "content": sys_prompt},
                     {"role": "user", "content": user_prompt}],
        "temperature": 0.5,
        "max_tokens": 8000,
        "stream": False,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {DEEPSEEK_KEY}"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                out = json.loads(resp.read())
            return out["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"[warn] deepseek broadcast attempt {attempt}: {e}", file=sys.stderr)
            if attempt == 2:
                return ""
            time.sleep(5)


def hanzi_count(s):
    return len(re.findall(r"[一-鿿]", s))


def deepseek_compress(text, lo=1500, hi=1800):
    """口播稿超字数时压缩一次，保持轻松口吻、开场/过渡/结尾结构不变。"""
    sys_prompt = (
        f"下面是一篇中文新闻口播稿，但偏长。请精简改写，使全文汉字数落在 {lo} 到 {hi} 之间"
        "（宁短勿长）。保留轻松亲切的口吻、开场问候、板块过渡和结尾；优先压缩次要新闻、"
        "合并同类内容，重要新闻保留。不要编号/链接/Markdown符号，用中文全角标点。"
        "直接输出精简后的正文。"
    )
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "system", "content": sys_prompt},
                     {"role": "user", "content": text}],
        "temperature": 0.4,
        "max_tokens": 8000,
        "stream": False,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {DEEPSEEK_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            out = json.loads(resp.read())
        return out["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[warn] deepseek compress: {e}", file=sys.stderr)
        return text


def split_for_telegram(text, limit=3800):
    """按段落把长文切成不超过 limit 的块，尽量不断句。"""
    paras = [p for p in text.split("\n\n") if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if len(cur) + len(p) + 2 <= limit:
            cur = (cur + "\n\n" + p) if cur else p
        else:
            if cur:
                chunks.append(cur)
            if len(p) <= limit:
                cur = p
            else:  # 单段超长，按句号硬切
                cur = ""
                for sent in re.split(r"(?<=[。！？])", p):
                    if len(cur) + len(sent) <= limit:
                        cur += sent
                    else:
                        if cur:
                            chunks.append(cur)
                        cur = sent
    if cur:
        chunks.append(cur)
    return chunks


# ---------- 语音合成 ----------
def tts_generate(text, path):
    """用 Edge TTS 把口播稿合成为 MP3（免费、无需 key）。"""
    import asyncio
    import edge_tts

    async def _run():
        await edge_tts.Communicate(text, TTS_VOICE).save(path)
    asyncio.run(_run())


def tg_send_audio(path, title, caption):
    import requests
    with open(path, "rb") as f:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendAudio",
            data={"chat_id": TG_CHAT, "title": title,
                  "performer": "每日晨报", "caption": caption},
            files={"audio": ("morning_brief.mp3", f, "audio/mpeg")},
            timeout=180,
        )
    ok = r.ok and r.json().get("ok")
    if not ok:
        print(f"[error] sendAudio: {r.text[:200]}", file=sys.stderr)
    return ok


# ---------- Telegram ----------
def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_message(cat, items, header=None):
    emoji, name = BOARD_META[cat]
    lines = []
    if header:
        lines.append(header + "\n")
    lines.append(f"{emoji} <b>{name}</b>\n")
    for n, it in enumerate(items, 1):
        title = esc(it.get("zh_title", "").strip())
        summary = esc(it.get("zh_summary", "").strip())
        source = esc(it.get("source", "").strip())
        link = it.get("link", "").strip()
        block = f"<b>{n}. {title}</b>\n{summary}"
        if link:
            block += f'\n🔗 <a href="{esc(link)}">{source} · 阅读原文</a>'
        lines.append(block)
    return "\n\n".join(lines)


def tg_send(text, parse_mode="HTML"):
    payload = {"chat_id": int(TG_CHAT), "text": text,
               "disable_web_page_preview": True}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", data=body,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        r = json.loads(resp.read())
    if not r.get("ok"):
        print(f"[error] telegram: {r}", file=sys.stderr)
    return r.get("ok", False)


def main():
    today = datetime.now(timezone.utc) + timedelta(hours=8)  # 北京时间
    date_hdr = f"🗞 <b>每日晨报 · {today.year}年{today.month}月{today.day}日</b>"

    candidates = collect()
    order = ["world", "finance", "crypto", "tech", "ai", "china"]
    first = True
    sent = 0
    picked = []  # [(cat, items)]，供口播稿使用
    for cat in order:
        cand = candidates.get(cat, [])
        if not cand:
            print(f"[warn] {cat}: no candidates, skip", file=sys.stderr)
            continue
        items = deepseek_pick(BOARD_META[cat][1], cand)
        if not items:
            print(f"[warn] {cat}: deepseek returned nothing, skip", file=sys.stderr)
            continue
        picked.append((cat, items))
        msg = build_message(cat, items, header=date_hdr if first else None)
        if len(msg) > 4000:
            msg = msg[:3990] + "…"
        if tg_send(msg):
            sent += 1
            first = False
        time.sleep(1)

    # 额外推送：完整版新闻口播稿
    if picked:
        date_str = f"{today.year}年{today.month}月{today.day}日"
        script = deepseek_broadcast(picked, date_str)
        if script and hanzi_count(script) > 1850:  # 超字数则压缩一次
            hz0 = hanzi_count(script)
            compressed = deepseek_compress(script)
            if compressed and hanzi_count(compressed) < hz0:
                print(f"[info] compressed {hz0} -> {hanzi_count(compressed)} hanzi", file=sys.stderr)
                script = compressed
        if script:
            print(f"[info] broadcast final: {hanzi_count(script)} hanzi", file=sys.stderr)
            chunks = split_for_telegram(script)
            for i, chunk in enumerate(chunks):
                head = "📻 <b>今日新闻口播稿</b>（可直接朗读）\n\n" if i == 0 else ""
                if tg_send(head + esc(chunk)):
                    sent += 1
                time.sleep(1)
            print(f"[info] broadcast: {len(script)} chars in {len(chunks)} msgs", file=sys.stderr)

            # 语音版：把口播稿合成 MP3 发送（失败不影响整体）
            try:
                audio_path = "morning_brief.mp3"
                tts_generate(script, audio_path)
                cap = f"📻 每日新闻晨报 · {date_str} · 语音版"
                if tg_send_audio(audio_path, f"每日新闻晨报 {date_str}", cap):
                    sent += 1
                    print("[info] audio sent", file=sys.stderr)
            except Exception as e:
                print(f"[warn] TTS/audio failed: {e}", file=sys.stderr)
        else:
            print("[warn] broadcast script empty, skipped", file=sys.stderr)

    print(f"[info] done, {sent} messages sent", file=sys.stderr)
    if sent == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
