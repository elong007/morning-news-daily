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

FEEDS = json.loads((Path(__file__).parent / "feeds.json").read_text(encoding="utf-8"))["feeds"]

BOARD_META = {
    "world":   ("🌍", "国际大事"),
    "finance": ("💰", "财经要闻"),
    "tech":    ("💻", "科技动态"),
    "china":   ("🇨🇳", "中国相关"),
}

CHINA_RE = re.compile(
    r"\b(china|chinese|beijing|shanghai|shenzhen|hong ?kong|taiwan|taipei|"
    r"xi jinping|xinjiang|tibet|macau|yuan|renminbi|huawei|tiktok|bytedance|"
    r"alibaba|tencent|byd|xiaomi|deepseek|tsmc|pboc)\b", re.IGNORECASE)


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


def tg_send(text):
    payload = {"chat_id": int(TG_CHAT), "text": text,
               "parse_mode": "HTML", "disable_web_page_preview": True}
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
    order = ["world", "finance", "tech", "china"]
    first = True
    sent = 0
    for cat in order:
        cand = candidates.get(cat, [])
        if not cand:
            print(f"[warn] {cat}: no candidates, skip", file=sys.stderr)
            continue
        items = deepseek_pick(BOARD_META[cat][1], cand)
        if not items:
            print(f"[warn] {cat}: deepseek returned nothing, skip", file=sys.stderr)
            continue
        msg = build_message(cat, items, header=date_hdr if first else None)
        if len(msg) > 4000:
            msg = msg[:3990] + "…"
        if tg_send(msg):
            sent += 1
            first = False
        time.sleep(1)
    print(f"[info] done, {sent} messages sent", file=sys.stderr)
    if sent == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
