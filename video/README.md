# news-reel · 每日晨报字幕视频

把 [morning-news-daily](https://github.com/elong007/morning-news-daily) 每天生成的中文口播稿，
渲染成竖屏（1080×1920）字幕视频——字幕本身就是主视觉，不需要素材库。

改自 Remotion 官方模板 [template-tiktok](https://github.com/remotion-dev/template-tiktok)，
但 Whisper 转录整条换掉了，中文分页也是重写的（原因见下）。

## 两个版本

| composition | 样子 |
|---|---|
| **NewsCrawl**（默认） | 星战片头式：星空里整块文字持续飞向深处，配开场卡和收尾卡 |
| NewsReel | 一句一屏：螺旋推进入场，重点词放大 |

## 一键出片

```bash
npm run prepare-content && npm run render
```

拆开就是三步：

| 命令 | 干什么 |
|---|---|
| `npm run fetch` | 从晨报仓库 `archive/latest.json` 拉当天口播稿 → `public/script.txt` + `props.json` |
| `npm run tts` | edge-tts 合成配音，同时拿词级时间戳 → `public/audio.mp3` + `public/captions.json` |
| `npm run render` | 渲 NewsCrawl → `out/news-crawl.mp4`（`render:reel` 渲另一版） |

拉某一天：`python scripts/fetch_script.py 2026-08-05`

调音色和语速：`python scripts/tts.py zh-CN-XiaoyiNeural +0%`
（`zh-CN-YunjianNeural` 男·新闻腔，默认；`zh-CN-XiaoyiNeural` 女·轻快；`zh-CN-YunxiNeural` 男·轻松）

改样式：`npm run dev` 开 Remotion Studio，边看边改。

## 三个和原模板不一样的地方

**1. 不跑 Whisper，时间戳直接来自 TTS。**
原模板是「现成视频 → Whisper.cpp 转录 → 词级时间戳」。这里音频本来就是我们自己合成的，
所以用 edge-tts 的 `WordBoundary` 事件直接取时间戳：零成本、不用下模型，
而且不存在 ASR 识别错误——时间戳来自合成器本身，天然精确。

两个坑：
- edge-tts 7.x 默认是 `SentenceBoundary`，必须显式传 `boundary="WordBoundary"`。
- 词级 token **不含标点**。所以合成后拿原文再对齐一次，把标点贴回词尾
  （`scripts/tts.py` 的 `attach_punctuation`），下游才能按句分页。

**2. 自己写了中文分页。**
Remotion 的 `createTikTokStyleCaptions` 是靠「单词前面的空格」判断断句的，
中文没有空格，整篇稿子会被压成一页。`src/lib/pages.ts` 改成按中文标点分页：
`。！？；` 必断，`，、：` 攒够字数才断，另有字数和时长两道上限兜底。

**3. 重点词按「整词」放大，不按 token。**
TTS 的分词会把数字切碎（`二零二六年` → `二零二`/`六`/`年`），照 token 放大只会放大第一截。
`markEmphasis` 先把相邻数字 token 连成一段、再吃掉后面的量词，整段一起放大；
渲染时这一组包在 `nowrap` 里，否则换行会把「年」甩到下一行。
重点词来源是当天 60 条新闻标题切出的候选词 + 中文数字/量词，每页最多放大一处
（不限的话约 40% 的词都会命中，等于没放大）。

## NewsCrawl 的关键点

**滚动不能匀速。** 星战原版是定速播放，但这里要跟着语音走：`crawlOffset` 找到当前时刻落在哪一行、
行内进度多少，算出 `(行号 + 进度) × 行高`。这样念得快的地方滚得快，停顿时字幕也停，
正在念的那行永远停在透视原点 `ORIGIN_Y`（那里不变形、最清楚）。匀速滚几十秒后就和语音脱节了。

**星星位置必须是确定性的。** Remotion 每帧独立求值，`Math.random()` 会让星星逐帧乱跳，
所以用 `sin(n * 12.9898)` 按序号生成。闪烁的相位和速度也各自不同，否则整片星星会一起呼吸。

**渐变金字不能加 text-shadow。** 金色是靠 `background-clip: text` + 透明填充裁出来的，
这种状态下 text-shadow 会糊成一团光斑。所以发光只给纯色的当前词用。

调观感的旋钮都在 `src/NewsCrawl/index.tsx` 顶部：`TILT` 后仰角、`PERSPECTIVE` 透视强度、
`ORIGIN_Y` 当前行高度、`LINE_H` 行距、`TAIL_DRIFT` 念完后飘远的速度。

## 结构

```
scripts/fetch_script.py        从 GitHub 归档拉口播稿
scripts/tts.py                 配音 + 词级时间戳
src/lib/pages.ts               中文分页 + 重点整词识别
src/NewsCrawl/index.tsx        序幕 / 正片 / 收尾三段，镜头呼吸、暗角、进度细线
src/NewsCrawl/CrawlLine.tsx    一行字：渐变金 + 当前词转亮白发光 + 重点词放大
src/NewsCrawl/StarField.tsx    确定性星空
src/NewsCrawl/Intro.tsx        开场卡
src/NewsCrawl/Outro.tsx        收尾卡
src/NewsReel/                  另一版：一句一屏，螺旋推进
public/                        script.txt / audio.mp3 / captions.json / 字体
```

## 传 YouTube

一次性授权（必须本人操作）：详细步骤见 **[docs/youtube-oauth.md](docs/youtube-oauth.md)**，简版：

1. Google Cloud Console 建项目 → 启用 **YouTube Data API v3**
2. OAuth 同意屏幕：User Type 选外部，把自己加进「测试用户」，
   **并把发布状态改成「生产」**——留在「测试」的话 refresh token 只有 7 天寿命，日更每周会断
3. 凭据 → 创建 OAuth 客户端 ID → 类型选**桌面应用** → 下载 JSON 存成 `secrets/client_secret.json`
4. `python scripts/upload_youtube.py --auth-only` — 浏览器弹出授权，
   完成后会打印授权到的频道名，核对一下别授错号。
   之后 refresh token 存在 `secrets/token.json`，往后免登录

日常一条龙（拉稿 → 配音 → 渲染 → 压缩 → 上传）：

```bash
bash scripts/daily.sh
```

标题、简介、标签都从 `public/meta.json` 生成，简介里会自动列出当天六个板块的 60 条标题。

**默认传成 private。** 确认没问题再手动改公开，或者 `bash scripts/daily.sh public`。

三个限制先知道：

- 项目通过 Google 的 API 合规审核前，**用 API 上传的视频会被强制锁成 private**，
  得去后台手动改公开。要长期直接发公开，需要申请 audit。
- 上传一条消耗 **1600** 单位配额，默认每天 10000，也就是一天最多 6 条。
- 6 分钟的片子**不算 Shorts**（Shorts 上限 3 分钟）。想走 Shorts 流量得按板块切成 6 条短的。

`secrets/` 已经在 `.gitignore` 里，别把 token 提交上去。

## 上游依赖

口播稿由晨报仓库的 GitHub Actions 每天 08:00（北京时间）生成并 commit 到 `archive/`。
手动补一期：Actions → 每日晨报 → Run workflow，勾上 `dry_run` 就不会重复推 Telegram。
