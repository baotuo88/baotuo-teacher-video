# baotuo-teacher-video · 宝拓讲解视频

把一个主题或一份素材，做成「手绘会动」的讲解视频的 Web 应用：导演（大模型）写分镜，你确认后自动写口播、配音、逐页画画面、机器质检 + 看图审片、渲染成片。一条 Docker 命令部署。

基于 [liangdabiao/whiteboard-teacher-video](https://github.com/liangdabiao/whiteboard-teacher-video) 的思路和 [Frametell](https://github.com/sitor-ai/frametell) 渲染引擎：画面是代码逐笔画出来的（rough.js），不是生图，所以零生图成本、可重渲、可精修。

## 功能

- **五步流水线**：素材 → 分镜（需你确认）→ 口播 → 配音 → 画面 → 成片，每步都能手动改、让模型按意见改、或重来；也可以「一键成片」
- **素材**：粘贴文字、上传 txt / md / pdf / html、读取网页或 GitHub 仓库（README）、上传截图图片（导演会把图原样放进合适的页）
- **41 种风格**：白板、黑板、书卷、暖色插画、科技深色，以及引擎自带的蓝图、霓虹、水彩、浮世绘、像素、3D 等；29 份样片可一键打开
- **配音**：Edge 朗读（免费，无需 Key）、任何 OpenAI 兼容的语音接口（硅基流动 CosyVoice、OpenAI 等）、逐句上传或浏览器里直接录音；按句缓存，改一句只重配一句
- **画面**：每页由模型写绘图代码 → 浏览器里机器检查（出界、压字幕、重叠、字太小、运行出错）→ 视觉模型看截图审片 → 退回修改，最多 N 轮；单页可按一句话修改、重画、手改代码
- **预览**：引擎自带播放器嵌在页面里（带声音、可拖动、幻灯片模式），和成片同一套代码
- **成片**：分段并行渲染 + 缓存（改一页只重渲那一段），有字幕 / 无字幕两版，SRT 字幕、口播稿、各平台发布文案（B 站、YouTube、抖音、视频号、小红书，自动带章节时间戳）
- **其他**：背景音乐（讲话时自动压低）、封面页、项目导出 / 导入 zip、访问密码、模型用量统计
- **模型**：Anthropic 接口或任意 OpenAI 兼容接口（DeepSeek、通义、Kimi、GLM、OpenRouter、各类中转）；不依赖工具调用，纯文本输入输出

## 部署到其他电脑（用现成镜像，推荐）

每次推送到 `main`，GitHub Actions 会自动构建镜像（amd64 + arm64：x86 服务器、Intel 和 Apple Silicon Mac 都能用），发布到 `ghcr.io/<GitHub 用户名>/baotuo-teacher-video`。目标机器只需要装 Docker，不用源码、不用构建：

```bash
mkdir baotuo-teacher-video && cd baotuo-teacher-video
# 从仓库下载 deploy/ 里的两个文件
curl -fLO https://raw.githubusercontent.com/<用户名>/baotuo-teacher-video/main/deploy/docker-compose.yml
curl -fL https://raw.githubusercontent.com/<用户名>/baotuo-teacher-video/main/deploy/.env.example -o .env
# 编辑 .env：IMAGE 改成你的用户名，设置 APP_PASSWORD
docker compose pull && docker compose up -d
```

更新到新版本：同一目录里再执行 `docker compose pull && docker compose up -d`，数据都在 `./data`，不受影响。想固定版本就把 `IMAGE` 写成 `…:1.0.0`（给仓库打 `v1.0.0` 标签即生成）。

- **仓库是私有的**：镜像默认也是私有，目标机器先 `docker login ghcr.io`（用户名 + 一个有 `read:packages` 权限的 Token）。公开仓库可以在 GitHub 的 Packages 页面把镜像设为 Public，免登录拉取
- **国内拉 ghcr.io 慢**：在仓库 Settings → Secrets and variables → Actions 里配置阿里云容器镜像服务（变量 `ACR_IMAGE`，密钥 `ACR_USERNAME` / `ACR_PASSWORD`，说明在 `.github/workflows/docker.yml` 开头），之后每次构建会同时推一份到阿里云，`.env` 里的 `IMAGE` 换成阿里云地址即可
- **完全离线**：在一台能用的机器上 `docker save baotuo-teacher-video:latest | gzip > btv.tar.gz`，拷过去 `docker load < btv.tar.gz`

## 从源码构建（Docker）

```bash
git clone <this repo> baotuo-teacher-video && cd baotuo-teacher-video
cp .env.example .env          # 至少设置 APP_PASSWORD；国内构建把镜像源那几行取消注释
docker compose up -d --build
```

打开 `http://<服务器>:8000`，在「设置」里填大模型的接口地址、Key 和模型名，点「测试连接」，然后新建视频。

数据（项目、配音、成片、设置）都在 `./data`，备份这个目录即可。

### 国内网络

`.env.example` 末尾有一组镜像源（daocloud 镜像、清华 apt / pypi、npmmirror），取消注释即可。

渲染引擎在构建时从 GitHub 拉取（固定版本）。GitHub 慢的话，先在宿主机上拉好再构建，构建时会直接用：

```bash
scripts/fetch-engine.sh vendor     # 或：FRAMETELL_SRC=/path/to/frametell scripts/fetch-engine.sh vendor
docker compose build
```

### 资源

一个 Chrome 大约占 1 核 CPU、400MB 内存。默认渲染 3 路并行、质检 2 路并行，在「设置 → 制作」里按机器调。实测 4 核 8G：1 分钟的片子 30fps 渲染约 2–3 分钟；改一页后重渲约 1 分钟。

带纹理滤镜的风格（黑板粉笔颗粒、水彩等）每帧更费 CPU：实测同一台机器上黑板风比白板风慢约 3 倍。3D 风格（宇宙、地球、微观、微缩城市、爆炸图）用 WebGL，容器里没有 GPU 时走软件渲染，会更慢。

## 配置

| 环境变量 | 说明 |
|---|---|
| `APP_PASSWORD` | 访问密码。不设置则不需要登录，**只在可信内网这样用** |
| `PORT` | 对外端口，默认 8000 |
| `LLM_PROVIDER` / `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` / `LLM_AUTH` | 模型的默认配置（设置页保存后以设置页为准） |
| `TTS_API_KEY` | OpenAI 兼容语音接口的 Key |
| `APP_SECRET` | 签名会话用的密钥，不设则自动生成在 `data/.secret` |

模型选择：画面代码对模型要求较高，强模型（Claude、GPT、通义 Max 等）一次通过率高、修改轮数少。模型不能看图时，在设置里关掉「模型能看图」，只靠机器检查。

一条 30 秒、3 页的片子实测约 14 次模型调用、13 万 tokens（其中大部分是可缓存的系统提示词）。

## 本地开发

需要 Node ≥ 22.19、Python ≥ 3.10、Chrome、ffmpeg。

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
(mkdir -p vendor/deps && cp engine/package*.json vendor/deps/ && cd vendor/deps && npm ci --ignore-scripts)
scripts/fetch-engine.sh vendor
scripts/dev-server.sh                     # 后端 :8765，数据在 /tmp/btv-data
cd frontend && npm install && npm run dev # 前端 :5173，代理到后端
```

## 结构

```
backend/app/
  main.py            FastAPI：API、项目文件、沙箱预览、前端
  plan.py            分镜、口播（模型输出 JSON，服务端写文件并检查、退回修改）
  draw.py            画面：写代码 → check.mjs（lint + 截图）→ 视觉审片 → 修改
  produce.py         配音、渲染、发布文案、一键成片
  voice.py           Edge / OpenAI 兼容 TTS、自录、voice.js
  film.py            script.js 的 META（风格、配音、组件、音乐）由服务端统一维护
  prompts.py         读取 Frametell 的导演 / 画师 / 审片提示词与风格语法卡，加上本应用的「无工具」约定
  llm.py             Anthropic / OpenAI 兼容两种接口，流式、重试、用量统计
  jobs.py            后台任务（每个项目同一时间一个），日志
frontend/src/        React 界面
engine/package.json  引擎需要的浏览器库和字体（引擎本身由 scripts/fetch-engine.sh 获取）
```

一个视频就是 `data/projects/<id>/` 下的一个 Frametell 工程目录（`script.js`、`pages/pNN.js`、`voice.js`、`audio/`、`out/`），可以导出后用 Frametell 或 whiteboard-teacher-video 的脚本继续处理。

## 安全说明

- 页面代码是模型写的 JavaScript：渲染和质检在容器里的无头 Chromium 中运行（`--no-sandbox`，容器是隔离边界）；浏览器里的预览放在不同源的沙箱 iframe 中，拿不到应用的 Cookie 和接口
- 设置里的 API Key 保存在 `data/settings.json`（权限 600），接口返回时只显示首尾几位
- 对公网开放时务必设置 `APP_PASSWORD`，最好再在前面加一层 HTTPS 反向代理（浏览器里录音也需要 HTTPS 或 localhost）

## 许可

本项目以 **AGPL-3.0** 发布（见 `LICENSE`）：它在运行时使用 Frametell 引擎和提示词（AGPL-3.0-only，Sitor Team），流水线逻辑也参考了 Frametell 的 director。用它做出来的视频不受 AGPL 约束；但如果你修改本项目并作为网络服务提供给他人使用，需要向这些用户提供修改后的源码。

- Frametell · Sitor Team · AGPL-3.0-only · https://github.com/sitor-ai/frametell
- whiteboard-teacher-video · liangdabiao · MIT（Edge 新域名的做法、示例片《相对论入门》，见 `backend/examples/NOTICE.md`）
- 字体：霞鹜文楷 LXGW WenKai（SIL OFL-1.1）
