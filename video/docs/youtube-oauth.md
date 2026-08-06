# YouTube 上传授权（一次性）

目标：让本机脚本能以你的身份往你的频道传视频，且之后免登录。
全程只需做一次，大约十分钟。

> 这一步必须你本人操作——要用你的 Google 账号登录并点同意。

## 先搞清楚：这里有两个账号，可以不是同一个

| 角色 | 干什么 | 要求 |
|---|---|---|
| **项目账号** | 在 Cloud Console 建项目、发 `client_secret.json` | 任意能访问 Cloud Console 的 Google 账号 |
| **频道账号** | 第 5 步授权时登录的那个，视频传到它名下 | 必须拥有你要发片的 YouTube 频道 |

两者相同最省事。**但如果你的主账号被限制、进不了 Cloud Console，就用另一个账号建项目，
授权时仍然登录主账号**——视频照样进主账号的频道。凭据和频道本来就是解耦的。

走这条路时务必注意第 3 步的**测试用户**：名单里要加的是**频道账号**的邮箱，不是项目账号的。

---

## 第 0 步：确认频道存在

先用你打算发片的那个 Google 账号登录 [youtube.com](https://www.youtube.com)，
确认**已经建过频道**。只有 Google 账号、没建频道的话，后面上传会直接失败。

如果频道是「品牌账号」（Brand Account），记住它挂在哪个 Google 账号下面，
第 5 步授权时要选对。

---

## 第 1 步：建 Google Cloud 项目

打开 [console.cloud.google.com](https://console.cloud.google.com)，
顶部项目下拉框 → **新建项目** → 名字随便，比如 `morning-news`。
建完记得在下拉框里切到这个项目。

## 第 2 步：启用 YouTube Data API v3

左侧菜单 **API 和服务 → 库**，搜 `YouTube Data API v3`，点进去 **启用**。

没启用的话，后面调用会报 `403 accessNotConfigured`。

## 第 3 步：配置 OAuth 同意屏幕

左侧 **API 和服务 → OAuth 同意屏幕**
（新版控制台里这块被挪到了 **Google Auth Platform → 品牌/受众群体**，内容一样）。

- **User Type** 选 **外部（External）**。个人 Gmail 只有这个选项；
  只有 Google Workspace 账号才能选「内部」。
- 应用名称：随便填，比如 `morning-news-uploader`。这个名字会出现在授权页面上。
- 用户支持邮箱、开发者联系邮箱：填你自己的邮箱。
- 「范围 / Scopes」这一步**可以直接跳过**，脚本运行时会自己申请。
- **测试用户（Test users）：把你自己的 Gmail 加进去。**
  这一步漏了，授权时会直接被拒，报 `Error 403: access_denied`。

### ⚠️ 发布状态要改成「生产」，否则每 7 天要重新授权一次

同意屏幕页面上有个**发布状态**，默认是 **测试（Testing）**。

**测试状态下签发的 refresh token 只有 7 天有效期。** 对日更自动化来说这是致命的——
每周会毫无征兆地断一次，跑批任务开始报 `invalid_grant`。

所以点 **发布应用 / PUBLISH APP**，把状态改成 **生产（In production）**。

它会提示需要验证（verification）。**不做验证也能用**：不提交验证的话，
授权页面会显示「Google 未验证此应用」的警告（第 5 步教你怎么过），
用户数上限 100 人——你自己一个人用完全够。但 token 不再 7 天过期。

## 第 4 步：创建 OAuth 客户端 ID

左侧 **API 和服务 → 凭据 → 创建凭据 → OAuth 客户端 ID**。

- **应用类型必须选「桌面应用」（Desktop app）。**
  选成「Web 应用」的话，脚本用的本地回环端口对不上，授权会失败。
- 名字随便填，创建后点**下载 JSON**。

下载下来的文件名长这样：`client_secret_1234-abc.apps.googleusercontent.com.json`。
**重命名并放到指定位置**：

```
C:\Users\dujob\news-reel\secrets\client_secret.json
```

`secrets/` 目录不存在就自己建。这个目录已经写进 `.gitignore`，不会进版本库。

## 第 5 步：跑一次授权

```bash
cd ~/news-reel && python scripts/upload_youtube.py --auth-only
```

会发生这些事：

1. 脚本在本机起一个临时服务器接 OAuth 回调，并自动打开浏览器
   （Windows 可能弹防火墙提示，允许即可——只监听本地回环）
2. 选账号：**选那个拥有你要发片频道的账号**。品牌账号的话选对应的那个
3. 看到「Google 尚未验证此应用」的警告 →
   点左下角**高级 / Advanced** → **转至 xxx（不安全）/ Go to xxx (unsafe)**
   （这是你自己建的应用，不做验证就一定会有这个提示，正常）
4. 授予「管理你的 YouTube 视频」权限 → 继续
5. 浏览器显示授权完成，可以关掉

终端会打印：

```
[done] 授权成功，token 已存到 .../secrets/token.json
[info] 视频会传到频道：你的频道名（UCxxxxxxxx）
```

**核对这个频道名。** 授错号了就删掉 `secrets/token.json` 重跑，重新选账号。

---

## 之后

`secrets/token.json` 里存着 refresh token，脚本会自动续期，不用再登录。

```bash
# 单独传一个文件（默认 private）
python scripts/upload_youtube.py out/xxx-web.mp4

# 全流程：拉稿 → 配音 → 渲染 → 压缩 → 上传
bash scripts/daily.sh
```

## 三个限制

**上传的视频会被强制锁成 private。**
Google 规定：项目通过 API 合规审核（audit）前，用 API 传上去的视频一律私享，
在 YouTube 后台手动改公开即可。想让 `--privacy public` 真正生效，
得去申请 audit（同意屏幕页面有入口，人工审核，要等）。

**配额**：每天 10000 单位，上传一条消耗 1600，也就是一天最多 6 条。日更够用。

**6 分钟的片子不算 Shorts**（Shorts 上限 3 分钟），走的是普通竖屏视频分发。

## 出问题时

| 报错 | 原因 |
|---|---|
| `access_denied` | 第 3 步没把自己加进测试用户；或应用还在测试状态但账号不在名单里 |
| `invalid_grant` | token 过期。多半是发布状态还停在「测试」（7 天限制），照第 3 步改成生产后重新授权 |
| `403 accessNotConfigured` | 第 2 步没启用 YouTube Data API v3 |
| `403 quotaExceeded` | 今天配额用完了，等次日太平洋时间 0 点重置 |
| 提示账号下没有频道 | 用了没建频道的账号授权，删掉 `token.json` 换号重来 |
| `redirect_uri_mismatch` | 第 4 步应用类型选错了，必须是「桌面应用」 |
