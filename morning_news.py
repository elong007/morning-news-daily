# -*- coding: utf-8 -*-
"""每日晨报 · 云端版（GitHub Actions 上运行，海外网络直连，无需代理）

流程：抓取西方主流媒体 RSS → DeepSeek 挑选/翻译/写中文摘要 → 推送 Telegram。
四个板块：world / finance / tech / china，每板块 10 条。

需要的环境变量（GitHub Secrets）：
  必填：TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DEEPSEEK_API_KEY
  选填：MINIMAX_API_KEY, MINIMAX_GROUP_ID, MINIMAX_VOICE_ID（配齐则口播用克隆音色，
        否则自动回落到免费的 Edge TTS）
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
# DRY_RUN=1 时只生成不推送（重跑不会给 Telegram 刷屏），此时两个 TG 变量可缺省
DRY_RUN = os.environ.get("DRY_RUN", "") == "1"
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "") if DRY_RUN else os.environ["TELEGRAM_BOT_TOKEN"]
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "0") if DRY_RUN else os.environ["TELEGRAM_CHAT_ID"]
# 口播稿转音频用的语音和语速。改法：仓库 Settings → Secrets and variables →
# Actions → Variables 里加 TTS_VOICE / TTS_RATE，不用改代码也不用重新 commit。常用中文音色：
# zh-CN-YunjianNeural(男·新闻腔，默认)  zh-CN-YunxiNeural(男·轻松活泼)
# zh-CN-XiaoyiNeural(女·轻快活泼)      zh-CN-XiaoxiaoNeural(女·温暖自然)
# 用 `or` 而不是 get 的默认值：workflow 里 vars 没设时传进来的是空字符串，
# 那种情况下 get 会返回 ""，拿空音色去调 edge-tts 会直接报错。
TTS_VOICE = os.environ.get("TTS_VOICE") or "zh-CN-YunjianNeural"
# 语速，如 "+8%" / "-5%" / "+0%"
TTS_RATE = os.environ.get("TTS_RATE") or "+0%"
# MiniMax 克隆音色（三项配齐才启用，缺任一项就走 Edge TTS）
MM_KEY = os.environ.get("MINIMAX_API_KEY", "")
MM_GROUP = os.environ.get("MINIMAX_GROUP_ID", "")
MM_VOICE = os.environ.get("MINIMAX_VOICE_ID", "")
MM_MODEL = os.environ.get("MINIMAX_MODEL", "speech-02-hd")
MM_HOST = os.environ.get("MINIMAX_HOST", "https://api.minimax.chat")

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


# ---------- 行情数据 ----------
YAHOO_QUOTES = [
    ("上证指数", "000001.SS", "point"),
    ("恒生指数", "^HSI", "point"),
    ("纳斯达克", "^IXIC", "point"),
    ("美元/人民币", "CNY=X", "fx"),
]


def _yahoo_quote(symbol):
    import urllib.parse
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           + urllib.parse.quote(symbol) + "?interval=1d&range=1d")
    data = http_get(url)
    if not data:
        return None
    try:
        m = json.loads(data)["chart"]["result"][0]["meta"]
        price = m.get("regularMarketPrice")
        prev = m.get("chartPreviousClose") or m.get("previousClose")
        if price is None:
            return None
        chg = (price - prev) / prev * 100 if prev else None
        return price, chg
    except Exception as e:
        print(f"[warn] yahoo {symbol}: {e}", file=sys.stderr)
        return None


def _coingecko():
    data = http_get("https://api.coingecko.com/api/v3/simple/price"
                    "?ids=bitcoin,ethereum&vs_currencies=usd&include_24hr_change=true")
    if not data:
        return {}
    try:
        j = json.loads(data)
        return {
            "比特币": (j["bitcoin"]["usd"], j["bitcoin"].get("usd_24h_change")),
            "以太币": (j["ethereum"]["usd"], j["ethereum"].get("usd_24h_change")),
        }
    except Exception as e:
        print(f"[warn] coingecko: {e}", file=sys.stderr)
        return {}


def us_market_closed():
    """判断美股今天是否休市（周末 / 假日）。返回 (closed, 最近交易日 'YYYY-MM-DD')。

    做法：读纳斯达克行情元数据里的 regularMarketTime，换算成交易所当地日期，
    和交易所当地的"今天"比。不一致就说明今天没开过盘。
    用响应里自带的 gmtoffset 换算，所以不需要时区数据库，夏令时也自动正确。

    注意：Yahoo 会按 IP 封禁，本机调用一律 403，只能在 Actions 里验证。
    """
    data = http_get("https://query1.finance.yahoo.com/v8/finance/chart/"
                    "%5EIXIC?interval=1d&range=1d")
    if not data:
        return False, ""
    try:
        m = json.loads(data)["chart"]["result"][0]["meta"]
        last = m.get("regularMarketTime")
        offset = m.get("gmtoffset")
        if not last or offset is None:
            return False, ""
        delta = timedelta(seconds=offset)
        ex_today = (datetime.now(timezone.utc) + delta).date()
        ex_last = (datetime.fromtimestamp(last, timezone.utc) + delta).date()
        return ex_last != ex_today, ex_last.isoformat()
    except Exception as e:
        print(f"[warn] us market session: {e}", file=sys.stderr)
        return False, ""


def fetch_market():
    """返回 [(label, price, chg_pct, kind), ...]，kind ∈ point/fx/crypto。"""
    rows = []
    for label, sym, kind in YAHOO_QUOTES:
        q = _yahoo_quote(sym)
        if q:
            rows.append((label, q[0], q[1], kind))
    cg = _coingecko()
    for label in ("比特币", "以太币"):
        if label in cg:
            rows.append((label, cg[label][0], cg[label][1], "crypto"))
    print(f"[info] market: {len(rows)}/6 quotes", file=sys.stderr)
    return rows


def _fmt_price(v, kind):
    if kind == "fx":
        return f"{v:.4f}"
    if kind == "crypto":
        return f"${v:,.0f}" if v >= 1000 else f"${v:,.2f}"
    return f"{v:,.2f}"


def market_block_html(rows):
    if not rows:
        return ""
    lines = ["📊 <b>今日市场速览</b>"]
    for label, price, chg, kind in rows:
        chg_s = f"  {'▲' if chg >= 0 else '▼'}{abs(chg):.2f}%" if chg is not None else ""
        lines.append(f"{label} {_fmt_price(price, kind)}{chg_s}")
    return "\n".join(lines)


def market_text_plain(rows, us_closed=False, last_session=""):
    if not rows:
        return ""
    segs = []
    if us_closed:
        # 放在最前面，主播必须先说清楚"美股今天没开"，否则听众会以为这是当日盘中数据
        note = "美股今日休市"
        if last_session:
            note += f"，以下美股数据为{last_session}收盘"
        segs.append(note)
    for label, price, chg, kind in rows:
        val = _fmt_price(price, kind).replace("$", "")
        seg = f"{label}{val}"
        if kind == "point":
            seg += "点"
        elif kind == "crypto":
            seg += "美元"
        if chg is not None:
            seg += f"，{'上涨' if chg >= 0 else '下跌'}{abs(chg):.2f}%"
        segs.append(seg)
    return "；".join(segs) + "。"


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
def deepseek_broadcast(picked, date_str, market_text=""):
    """picked: [(cat, [items...]), ...]，items 已翻译好。
    返回 (script, section_starts)：script 为口播稿正文；
    section_starts 为 [{"board": 板块名, "start": 该板块起始句}]（后续做章节/字幕定位用）。"""
    boards = []
    for cat, items in picked:
        boards.append({
            "板块": BOARD_META[cat][1],
            "新闻": [{"标题": it.get("zh_title", ""), "摘要": it.get("zh_summary", ""),
                     "来源": it.get("source", "")} for it in items],
        })
    market_clause = (
        "在财经板块，先用一两句自然口语化地播报下面提供的'今日市场行情'——"
        "依次带出各指数点位与涨跌幅、美元兑人民币汇率、比特币与以太币价格，数字必须准确、不要编造；"
        "如果行情数据开头写了'美股今日休市'，必须先把这句说出来（比如'美股今天休市'），"
        "再播其余数字，不许略过；"
        if market_text else "")
    sys_prompt = (
        "你是一位在电台做早间新闻的主播，正在给自己写今天上节目要念的稿子。"
        "记住：你写的是'说出来的话'，不是'写下来的文章'。"
        "根据给定的、已翻译成中文的新闻，撰写一篇连贯、适合朗读的中文口播稿。\n"

        "【一、口语化硬要求——这部分最重要，逐条照做】\n"
        "1. 句子要短。平均每句不超过25个字，超过就拆成两句。绝不写从句套从句的长句。\n"
        "2. 禁用这些书面连接词：值得注意的是、与此同时、此外、据悉、另一方面、综上所述、"
        "引发广泛关注、表示、指出、认为、随着、在……背景下。"
        "改用口语说法：不过、结果、而且、说白了、也就是说、这事儿、问题在于、有意思的是、简单讲。\n"
        "3. 先给结论再补背景。不要写'在通胀持续走高的背景下，美联储宣布了加息'，"
        "要写'美联储又加息了。原因是通胀一直下不来。'\n"
        "4. 数字按标准中文出版用法：确切的数值用阿拉伯数字——日期（2026年8月6日）、"
        "百分比（3.5%、下跌2%）、精确数量（28人）、指数点位（3878.43点）都用阿拉伯数字和%符号；"
        "金额用阿拉伯数字加中文单位（1.2万亿美元、64000美元、7.2元），不要用$￥这类货币符号；"
        "只有概数和习惯用语才用中文（如'一两句''十几年''好几个''成千上万''三三两两'）。\n"
        "5. 生僻的英文缩写和外文机构名翻成中文说法；AI、GDP、iPhone 这类已经进入日常口语的可以保留。\n"
        "6. 允许少量自然口气词（那么、咱们、你看、嗯），但全篇不超过八处，多了就腻。\n"
        "7. 不要排比句、不要对仗、不要成语堆砌——这些一念出来就是念稿子的味道。\n"
        "8. 人名机构名第一次出现给全称，后面用简称，像真人说话那样。\n"

        "【二、结构要求】\n"
        "1. 开头三句是固定格式，必须一字不改、按这个顺序、各自单独成句：\n"
        "   第一句：'将世界讲给你听。'\n"
        f"   第二句：'今天是{date_str}。'\n"
        "   第三句：'大家好，欢迎收听世界要闻。'\n"
        "   问候语一律用'大家好'。不许用'早上好''早安''各位听众早上好'这类跟时段绑定的说法——"
        "节目什么时候被听到不一定。也不要自我介绍、不要出现'我是你们的主播'之类的话。"
        "不许把日期挪到问候语里面去，也不许改写成别的说法。\n"
        "2. 按给定板块顺序播报，每个板块用像真人转话题那样的过渡语引入"
        "（如'先看看国际上出了什么事'、'行，钱这块儿'、'数字货币这边'、'科技圈'、"
        "'AI 那边'、'最后说说跟咱们有关的'）。\n"
        "3. 按重要性分配篇幅：重大新闻展开2-3句讲清楚，次要新闻一句带过，同类的合并着说，"
        "不重要的可以不播。来源自然融进句子里（如'路透社说'、'金融时报那边报道'）。\n"
        + market_clause +
        "4. 段落之间空一行；结尾用生活化的一两句收尾，别用'我们明天再见'这种播音腔；"
        "并把'你想了解什么新闻，欢迎告诉我。'作为全文最后一句。\n"

        "【三、格式禁令】\n"
        "篇幅按新闻的数量和重要性灵活把握，重要的多讲、次要的少讲，不设字数上限。"
        "口播稿正文里不要出现编号、网址链接、Markdown符号（*#等）、括号备注；"
        "除阿拉伯数字和百分号外，其余标点一律用中文全角，不要英文标点"
        "（此禁令针对 script 正文，不针对下面的 JSON 结构本身）。\n"

        "【四、输出格式】\n"
        "只返回一个 JSON 对象，不要代码块标记、不要多余说明：\n"
        "{\"script\": \"完整口播稿正文，含开场广告语、问候、各板块过渡语、结尾\", "
        "\"section_starts\": [{\"board\": \"板块名\", \"start\": \"该板块的第一句话（即过渡语那一句），"
        "必须与 script 里的原句一字不差\"}]}。"
        "section_starts 按播报顺序列出每一个实际播报到的板块，board 用给定的板块名称，"
        "start 必须能在 script 里原样找到。"
    )
    user_prompt = "新闻内容（JSON，按此顺序播报）：\n" + json.dumps(boards, ensure_ascii=False)
    if market_text:
        user_prompt += "\n\n今日市场行情（财经板块请播报这些数字）：\n" + market_text
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "system", "content": sys_prompt},
                     {"role": "user", "content": user_prompt}],
        "temperature": 0.7,   # 口语稿需要一点随机性，太低会写得整齐但呆板
        "max_tokens": 8000,
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
            with urllib.request.urlopen(req, timeout=180) as resp:
                out = json.loads(resp.read())
            obj = json.loads(out["choices"][0]["message"]["content"])
            script = (obj.get("script") or "").strip()
            starts = [s for s in (obj.get("section_starts") or [])
                      if isinstance(s, dict) and s.get("start")]
            return script, starts
        except Exception as e:
            print(f"[warn] deepseek broadcast attempt {attempt}: {e}", file=sys.stderr)
            if attempt == 2:
                return "", []
            time.sleep(5)


def hanzi_count(s):
    return len(re.findall(r"[一-鿿]", s))


def deepseek_compress(text, lo=1500, hi=1800):
    """口播稿超字数时压缩一次，保持轻松口吻、开场/过渡/结尾结构不变。"""
    sys_prompt = (
        f"下面是一篇中文新闻口播稿，但偏长。请精简改写，使全文汉字数落在 {lo} 到 {hi} 之间"
        "（宁短勿长）。保留轻松亲切的口吻、板块过渡和结尾；优先压缩次要新闻、"
        "合并同类内容，重要新闻保留；财经板块的行情数字（指数点位、涨跌幅、汇率、币价）必须保留。"
        "【关键】开头三句原样保留、一字不改：'将世界讲给你听。'、'今天是……。'、"
        "'大家好，欢迎收听世界要闻。'，不许删改，也不许把'大家好'改成'早上好'。"
        "压缩时不许把口语改回书面语：句子仍要短（每句不超过25字），"
        "不许用'值得注意的是、与此同时、此外、据悉、随着、在……背景下'这类词。"
        "数字沿用原文写法：确切数值保持阿拉伯数字（2026年8月6日、3.5%、3878.43点、1.2万亿美元），"
        "概数才用中文（'十几年''好几个'），不要把阿拉伯数字改回中文读法。"
        "删内容，不是把内容塞进更长的句子里。"
        "不要编号/链接/Markdown符号，用中文全角标点。"
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


def deepseek_review(text):
    """合规审核：检查口播稿是否有违反中国法律法规/社会主义核心价值观的内容。
    返回 (compliant: bool, issues: str, revised: str)。不合规时 revised 为中性化改写后的合规版。"""
    sys_prompt = (
        "你是一位专业的中文新闻内容合规审核编辑。请审核下面这篇新闻口播稿，判断是否存在"
        "违反中华人民共和国法律法规、或不符合社会主义核心价值观的内容，例如："
        "违反新闻宣传纪律的政治敏感或倾向性表述、对国家主权和领土完整（含台湾、香港、"
        "西藏、新疆等）的错误表述、涉及民族宗教的不当内容、攻击国家制度或领导人、"
        "淫秽暴力恐怖、虚假谣言、违背公序良俗等。"
        "处理原则：在尽量保留新闻事实与信息量的前提下，把有问题的表述改写为客观、中性、"
        "符合中国大陆表述规范的说法（例如立场性形容词改中性、敏感定性改为事实陈述）；"
        "确实无法合规的整条可删去。"
        "只返回 JSON：{\"compliant\": true 或 false, "
        "\"issues\": \"简述发现的问题，没有则留空\", "
        "\"revised\": \"合规版口播稿全文；若原文本就合规则原样返回全文\"}。"
    )
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "system", "content": sys_prompt},
                     {"role": "user", "content": text}],
        "temperature": 0.2,
        "max_tokens": 8000,
        "response_format": {"type": "json_object"},
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
        obj = json.loads(out["choices"][0]["message"]["content"])
        return bool(obj.get("compliant", True)), obj.get("issues", ""), obj.get("revised", "")
    except Exception as e:
        print(f"[warn] deepseek review: {e}", file=sys.stderr)
        return True, "", text  # 审核失败不阻断，放行原文


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
def minimax_tts(text, path):
    """用 MiniMax T2A v2 + 克隆音色合成 MP3。未配置或失败返回 False。"""
    if not (MM_KEY and MM_VOICE):
        return False
    url = f"{MM_HOST}/v1/t2a_v2" + (f"?GroupId={MM_GROUP}" if MM_GROUP else "")
    body = {
        "model": MM_MODEL,
        "text": text,
        "stream": False,
        "language_boost": "Chinese",
        "voice_setting": {"voice_id": MM_VOICE, "speed": 1.0, "vol": 1.0, "pitch": 0},
        "audio_setting": {"sample_rate": 32000, "bitrate": 128000,
                          "format": "mp3", "channel": 1},
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {MM_KEY}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"[warn] minimax tts request failed: {e}", file=sys.stderr)
        return False
    audio_hex = (data.get("data") or {}).get("audio", "")
    if data.get("base_resp", {}).get("status_code") != 0 or not audio_hex:
        print(f"[warn] minimax tts: {str(data.get('base_resp'))[:200]}", file=sys.stderr)
        return False
    Path(path).write_bytes(bytes.fromhex(audio_hex))
    return True


def tts_generate(text, path):
    """口播稿合成 MP3：优先 MiniMax 克隆音色，失败回落 Edge TTS（免费无 key）。"""
    if minimax_tts(text, path):
        print("[info] tts via minimax clone voice", file=sys.stderr)
        return
    import asyncio
    import edge_tts

    async def _run():
        await edge_tts.Communicate(text, TTS_VOICE, rate=TTS_RATE).save(path)
    asyncio.run(_run())
    print(f"[info] tts via edge-tts, voice={TTS_VOICE} rate={TTS_RATE}", file=sys.stderr)


def tg_send_audio(path, title, caption):
    if DRY_RUN:
        print(f"[dry-run] skip sendAudio ({path})", file=sys.stderr)
        return True
    import requests
    with open(path, "rb") as f:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendAudio",
            data={"chat_id": TG_CHAT, "title": title,
                  "performer": "世界要闻", "caption": caption},
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


def build_message(cat, items, header=None, extra=None):
    emoji, name = BOARD_META[cat]
    lines = []
    if header:
        lines.append(header + "\n")
    lines.append(f"{emoji} <b>{name}</b>\n")
    if extra:
        lines.append(extra)
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
    if DRY_RUN:
        print(f"[dry-run] skip sendMessage ({len(text)} chars)", file=sys.stderr)
        return True
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


def write_archive(script, picked, date_str, today, section_starts=None):
    """把口播稿落盘到 archive/，供下游（字幕视频等）取用。

    archive/YYYY-MM-DD.txt   纯文本口播稿
    archive/YYYY-MM-DD.json  稿子 + 各板块标题 + 各板块起始句，便于程序消费
    archive/latest.txt|json  永远指向最新一期
    """
    d = Path(__file__).parent / "archive"
    d.mkdir(exist_ok=True)
    stamp = today.strftime("%Y-%m-%d")
    meta = {
        "date": stamp,
        "dateStr": date_str,
        "hanzi": hanzi_count(script),
        "script": script,
        "sectionStarts": section_starts or [],
        "boards": [
            {"name": BOARD_META[cat][1],
             "emoji": BOARD_META[cat][0],
             "headlines": [it.get("zh_title", "") for it in items]}
            for cat, items in picked
        ],
    }
    for name in (stamp, "latest"):
        (d / f"{name}.txt").write_text(script, encoding="utf-8")
        (d / f"{name}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[info] archived -> archive/{stamp}.txt", file=sys.stderr)


def main():
    today = datetime.now(timezone.utc) + timedelta(hours=8)  # 北京时间
    date_hdr = f"🗞 <b>世界要闻 · {today.year}年{today.month}月{today.day}日</b>"

    candidates = collect()
    market_rows = fetch_market()
    us_closed, last_session = us_market_closed()
    print(f"[info] us market closed today: {us_closed} (last session {last_session})",
          file=sys.stderr)
    market_html = market_block_html(market_rows)
    market_txt = market_text_plain(market_rows, us_closed, last_session)
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
        extra = market_html if cat == "finance" else None
        msg = build_message(cat, items, header=date_hdr if first else None, extra=extra)
        if len(msg) > 4000:
            msg = msg[:3990] + "…"
        if tg_send(msg):
            sent += 1
            first = False
        time.sleep(1)

    # 额外推送：完整版新闻口播稿
    if picked:
        date_str = f"{today.year}年{today.month}月{today.day}日"
        script, section_starts = deepseek_broadcast(picked, date_str, market_text=market_txt)
        if section_starts:
            preview = " | ".join(f"{s.get('board', '?')}:{s.get('start', '')[:16]}"
                                 for s in section_starts)
            print(f"[info] section starts: {preview}", file=sys.stderr)
        if script:  # 合规审核：违反法律法规/社会主义核心价值观则中性化改写
            compliant, issues, revised = deepseek_review(script)
            if not compliant and revised:
                print(f"[info] compliance: adjusted -> {issues[:120]}", file=sys.stderr)
                script = revised
            else:
                print("[info] compliance: OK", file=sys.stderr)
        if script:  # 不再限制字数上限，篇幅由内容重要性决定
            print(f"[info] broadcast final: {hanzi_count(script)} hanzi", file=sys.stderr)
            write_archive(script, picked, date_str, today, section_starts)
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
                cap = f"📻 世界要闻 · {date_str} · 语音版"
                if tg_send_audio(audio_path, f"世界要闻 {date_str}", cap):
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
