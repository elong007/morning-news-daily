# -*- coding: utf-8 -*-
"""把渲好的晨报视频传到 YouTube。

标题、简介、标签都从 public/meta.json 生成——简介里会列出当天六个板块的全部标题，
这既是给观众看的目录，也是喂给 YouTube 搜索的关键词。

首次使用（只需一次，必须你本人操作）：
  1. Google Cloud Console 建项目 → 启用 "YouTube Data API v3"
  2. 凭据 → 创建 OAuth 客户端 ID → 类型选「桌面应用」→ 下载 JSON
  3. 把文件存成 secrets/client_secret.json
  4. OAuth 同意屏幕里把自己的 Google 账号加进「测试用户」
  5. 跑一次 `python scripts/upload_youtube.py --auth-only`，
     浏览器会打开让你授权，成功后 refresh token 存进 secrets/token.json，之后就免登录了

日常：
  python scripts/upload_youtube.py out/xxx.mp4                # 默认直接公开
  python scripts/upload_youtube.py out/xxx.mp4 --privacy unlisted
  python scripts/upload_youtube.py out/xxx.mp4 --privacy private

注意：网上常说"项目没过 API 合规审核前，API 传的视频会被强制锁成 private"——
这条在本项目实测不成立（2026-08-07 请求 private，落地是 public）。
所以上传后一律回读校验实际隐私状态，不符就非零退出。
配额：上传一条消耗 1600 单位，默认每天 10000，也就是一天最多 6 条。
"""
import argparse
import json
import sys
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / "secrets"
CLIENT_SECRET = SECRETS / "client_secret.json"
TOKEN = SECRETS / "token.json"
META = ROOT / "public" / "meta.json"

MANUAL = False  # 由 --manual 置位

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    # 只为了授权后能读出频道名，确认授的是对的那个号。
    # 光有 upload 权限是查不了 channels.list(mine=True) 的。
    "https://www.googleapis.com/auth/youtube.readonly",
]
# 22 = People & Blogs，25 = News & Politics
CATEGORY_ID = "25"


def get_credentials():
    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            sys.exit(
                f"[error] token 已失效：{e}\n"
                "        最常见的原因：OAuth 同意屏幕的发布状态还停在「测试」——\n"
                "        测试状态签发的 refresh token 只有 7 天寿命。\n"
                "        去 Google Auth Platform 把状态改成「生产」，然后：\n"
                f"          del {TOKEN}\n"
                "          python scripts/upload_youtube.py --auth-only"
            )
    else:
        if not CLIENT_SECRET.exists():
            sys.exit(
                f"[error] 缺少 {CLIENT_SECRET}\n"
                "        去 Google Cloud Console 建「桌面应用」类型的 OAuth 客户端 ID，"
                "下载 JSON 放到这个路径（详见本文件顶部注释）"
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
        # 会在本机起一个临时服务器接 OAuth 回调，并打开浏览器让你点同意。
        # manual=True 时不自动开浏览器，只把 URL 打出来——浏览器同时登着多个 Google 账号时，
        # Google 自己拼的切号跳转会丢参数、报泛化 400，贴进无痕窗口就能绕开。
        if MANUAL:
            print(
                "\n把下面这个链接贴进【无痕窗口】，并且只登录你要发片的那个账号：\n",
                file=sys.stderr,
            )
            creds = flow.run_local_server(port=0, open_browser=False)
        else:
            creds = flow.run_local_server(port=0)

    SECRETS.mkdir(exist_ok=True)
    TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return creds


def show_channel(creds):
    """打印授权到的频道，确认没授错号（多个 Google 账号 / 品牌账号时很容易搞错）。"""
    try:
        youtube = build("youtube", "v3", credentials=creds)
        items = youtube.channels().list(part="snippet", mine=True).execute().get("items", [])
    except HttpError as e:
        print(f"[warn] 读不到频道信息：{e}", file=sys.stderr)
        return
    if not items:
        print(
            "[warn] 这个账号名下没有 YouTube 频道，上传会失败。"
            "先去 youtube.com 建一个频道，或者换个账号重新授权"
            f"（删掉 {TOKEN} 再跑一次）",
            file=sys.stderr,
        )
        return
    ch = items[0]
    print(
        f"[info] 视频会传到频道：{ch['snippet']['title']}（{ch['id']}）\n"
        f"       不是想要的频道就删掉 {TOKEN}，重新授权时选对账号",
        file=sys.stderr,
    )


def fmt_ts(ms):
    """YouTube 章节的时间戳格式：短于一小时用 m:ss，否则 h:mm:ss。"""
    total = int(ms // 1000)
    h, m, s = total // 3600, total % 3600 // 60, total % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def load_chapters():
    """读 sections.py 算好的板块时间轴。没有就返回空，简介照常生成。"""
    path = ROOT / "public" / "sections.json"
    if not path.exists():
        print("[warn] 没有 sections.json，简介里不会有章节。先跑 scripts/sections.py",
              file=sys.stderr)
        return []
    try:
        chapters = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[warn] sections.json 读不了：{e}", file=sys.stderr)
        return []
    # 第一段必须晚于 0:00（0:00 留给"开场"），且各段间隔不能小于 10 秒，否则 YouTube 整块不认
    out = []
    last = 0
    for c in chapters:
        if c.get("videoMs", 0) - last >= 10_000:
            out.append(c)
            last = c["videoMs"]
    return out


def build_metadata():
    """标题/简介/标签都由当天的 meta.json 生成。"""
    if not META.exists():
        sys.exit(f"[error] 缺少 {META}，先跑 npm run fetch")
    meta = json.loads(META.read_text(encoding="utf-8"))

    date_str = meta.get("dateStr", "")
    boards = meta.get("boards", [])

    title = f"世界要闻 · {date_str}｜国际 财经 科技 AI 全球要闻速览"

    lines = [
        f"{date_str} 全球要闻速览。",
        "",
        "内容取自 NYT / Guardian / WSJ / BBC / Reuters / Economist / Bloomberg 等西方主流媒体当日报道，"
        "经 AI 筛选、翻译、整理成中文播报。",
    ]

    # YouTube 章节：简介里出现「时间戳 空格 标题」的连续列表就会变成进度条分段。
    # 规则：必须从 0:00 起、至少 3 段、每段不短于 10 秒，否则整块不生效。
    chapters = load_chapters()
    if len(chapters) >= 2:
        lines += ["", "—— 章节 ——", "0:00 开场"]
        for c in chapters:
            lines.append(f"{fmt_ts(c['videoMs'])} {c['emoji']} {c['board']}".strip())

    lines += ["", "—— 本期目录 ——"]
    for board in boards:
        lines.append("")
        lines.append(f"【{board.get('emoji', '')} {board.get('name', '')}】")
        for headline in board.get("headlines", []):
            lines.append(f"· {headline}")
    lines += [
        "",
        "每天早上更新。",
        "",
        "#世界要闻 #国际新闻 #财经 #科技 #AI",
    ]
    description = "\n".join(lines)
    # YouTube 简介上限 5000 字符
    if len(description) > 4900:
        description = description[:4900] + "\n…"

    tags = ["世界要闻", "国际新闻", "财经新闻", "科技新闻", "AI", "新闻速览", "早报"]
    tags += [b.get("name", "") for b in boards if b.get("name")]

    return title, description, tags


def upload(video_path: Path, privacy: str):
    title, description, tags = build_metadata()

    print(f"[info] 标题：{title}", file=sys.stderr)
    print(f"[info] 简介 {len(description)} 字符，{len(tags)} 个标签", file=sys.stderr)
    print(f"[info] 隐私：{privacy}", file=sys.stderr)
    print(f"[info] 文件：{video_path} ({video_path.stat().st_size / 1e6:.0f} MB)", file=sys.stderr)

    youtube = build("youtube", "v3", credentials=get_credentials())
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": CATEGORY_ID,
            "defaultLanguage": "zh-CN",
            "defaultAudioLanguage": "zh-CN",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    # 分块续传：大文件断了能接着传
    media = MediaFileUpload(str(video_path), chunksize=8 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        try:
            status, response = request.next_chunk()
        except HttpError as e:
            sys.exit(f"[error] 上传失败：{e}")
        if status:
            print(f"[info] 已上传 {int(status.progress() * 100)}%", file=sys.stderr)

    video_id = response["id"]
    print(f"[done] https://youtu.be/{video_id}", file=sys.stderr)

    # 回读校验：实测发现 YouTube 不一定采纳请求里的 privacyStatus
    # （2026-08-07 明确请求 private，落地却是 public）。
    # 不校验的话，接进自动流水线就是每天的片子直接公开、没有审核窗口。
    actual = response.get("status", {}).get("privacyStatus")
    try:
        got = youtube.videos().list(part="status", id=video_id).execute()["items"][0]
        actual = got["status"]["privacyStatus"]
    except (HttpError, IndexError, KeyError) as e:
        print(f"[warn] 回读隐私状态失败：{e}", file=sys.stderr)

    if actual != privacy:
        print(
            f"\n[error] 隐私状态不符！请求 {privacy}，实际 {actual}。\n"
            f"        视频已经以 {actual} 状态挂在频道上了。\n"
            f"        upload 权限改不了已有视频，只能去 YouTube Studio 手动改：\n"
            f"        https://studio.youtube.com/video/{video_id}/edit\n"
            f"        另外查一下 Studio → 设置 → 上传默认设置 → 可见性。",
            file=sys.stderr,
        )
        return video_id, False

    print(f"[info] 隐私状态已确认：{actual}", file=sys.stderr)
    return video_id, True


def main():
    parser = argparse.ArgumentParser(description="上传晨报视频到 YouTube")
    parser.add_argument("video", nargs="?", help="视频文件路径")
    parser.add_argument(
        "--privacy",
        default="public",
        choices=["public", "unlisted", "private"],
        help="默认 public。想先自己审一眼再放出去就传 unlisted 或 private",
    )
    parser.add_argument(
        "--auth-only", action="store_true", help="只走一次授权，拿到 token 就退出"
    )
    parser.add_argument(
        "--manual",
        action="store_true",
        help="不自动开浏览器，只打印授权链接，方便贴进无痕窗口（多账号登录时用）",
    )
    args = parser.parse_args()

    global MANUAL
    MANUAL = args.manual

    if args.auth_only:
        creds = get_credentials()
        print(f"[done] 授权成功，token 已存到 {TOKEN}", file=sys.stderr)
        show_channel(creds)
        return

    if not args.video:
        parser.error("要传的视频路径没给")
    video_path = Path(args.video)
    if not video_path.exists():
        sys.exit(f"[error] 找不到 {video_path}")

    _, privacy_ok = upload(video_path, args.privacy)
    # 隐私状态不符要让调用方知道——CI 里这一步失败会触发 Telegram 告警
    if not privacy_ok:
        sys.exit(2)


if __name__ == "__main__":
    main()
