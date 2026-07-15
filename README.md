# 每日晨报 · 云端版

每天北京时间 08:00 在 GitHub Actions（海外服务器，直连无需代理）上自动运行：

1. 抓取西方主流媒体 RSS（NYT / Guardian / WSJ / BBC / Reuters / Economist / Politico / DW / Spiegel / Japan Times / Nikkei / CNA / Straits Times / FT / MarketWatch / CNBC / TechCrunch / The Verge / Ars Technica / Wired）
2. 交给 DeepSeek 挑选、翻译、写中文摘要
3. 分 4 条消息推送到 Telegram

四个板块：🌍 国际大事 / 💰 财经要闻 / 💻 科技动态 / 🇨🇳 中国相关，每板块 10 条。

## 配置

信源在 [`feeds.json`](feeds.json)，随时增删。

需要在仓库 **Settings → Secrets and variables → Actions** 配置 3 个 Secret：

| Secret | 说明 |
|--------|------|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | 接收消息的 chat id |
| `DEEPSEEK_API_KEY` | DeepSeek API key（https://platform.deepseek.com） |

## 手动触发

Actions 页面 → 「每日晨报」→ Run workflow。

## 修改推送时间

改 [`.github/workflows/daily.yml`](.github/workflows/daily.yml) 里的 cron（UTC 时间，北京时间 = UTC + 8）。
