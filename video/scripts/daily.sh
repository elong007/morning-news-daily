#!/usr/bin/env bash
# 每日全自动：拉稿 → 配音 → 渲染 → 压缩 → 上传 YouTube
#
# 手动跑：  bash scripts/daily.sh
# 上传公开：bash scripts/daily.sh public
#
# 挂 Windows 计划任务（每天 12:30）：
# 云端 cron 写的是 00:00 UTC（北京 08:00），但 GitHub 对定时任务的延迟稳定在 3~3.5 小时，
# 实测最近两周都落在北京时间 11:15~11:45。12:30 起跑留足余量，再靠下面的重试兜底。
#   程序:   C:\Program Files\Git\bin\bash.exe
#   参数:   -lc "cd /c/Users/dujob/news-reel && bash scripts/daily.sh >> out/daily.log 2>&1"
#   勾上「错过计划开始时间后尽快启动任务」，关机错过的那天开机后会自动补上。
#
# 默认传成 private，确认没问题再手动改公开——别让没人看过的片子直接上线。
set -euo pipefail

cd "$(dirname "$0")/.."

PRIVACY="${1:-private}"
TODAY="$(date +%F)"
MASTER="out/morning-news-crawl-${TODAY}.mp4"
WEB="out/morning-news-crawl-${TODAY}-web.mp4"

log() { echo "[$(date +%T)] $*"; }

# ---- 拉稿。云端定时任务延迟波动很大，所以重试兜底，最多等两小时 ----
RETRIES=8
INTERVAL=900
log "拉当天口播稿"
for attempt in $(seq 1 $RETRIES); do
  python scripts/fetch_script.py
  GOT="$(python -c "import json;print(json.load(open('public/meta.json',encoding='utf-8'))['date'])")"
  if [ "$GOT" = "$TODAY" ]; then
    break
  fi
  if [ "$attempt" = "$RETRIES" ]; then
    # 拿到的还是旧稿子，说明云端今天没跑成。直接退出——
    # 否则会拿昨天的新闻再渲一条、再传一条重复的上去。
    echo "[error] 归档里最新的是 $GOT，不是今天（$TODAY）。云端晨报可能没跑成，停在这里。" >&2
    exit 1
  fi
  log "归档还停在 $GOT，$((INTERVAL / 60)) 分钟后重试（第 $attempt/$RETRIES 次）"
  sleep "$INTERVAL"
done

# ---- 已经渲过就别重复干 10 分钟的活 ----
if [ -f "$WEB" ]; then
  log "$WEB 已存在，跳过配音和渲染"
else
  log "合成配音 + 词级时间戳"
  python scripts/tts.py

  log "渲染（约 10 分钟）"
  npx remotion render NewsCrawl "$MASTER" --props=props.json

  log "压投放版"
  ffmpeg -v error -i "$MASTER" -c:v libx264 -crf 27 -preset slow \
    -pix_fmt yuv420p -c:a aac -b:a 128k -movflags +faststart -y "$WEB"
fi

log "上传 YouTube（$PRIVACY）"
python scripts/upload_youtube.py "$WEB" --privacy "$PRIVACY"

log "完成"
