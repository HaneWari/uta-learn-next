# Uta Learn Next

跟着日语歌学日语：**逐字**卡啦 OK 高亮、标注汉字的假名注音、罗马音、中文翻译，以及按真实词元
（辞书形 + 词性 + JLPT + 中文释义）和句型整理的词汇卡。可以把自己下载的音频配任意歌词源，
也能一键导出 1920×1080 / 60fps 的成片。

**本项目不提供相关音频资源，请自行获取**

本项目在[utalearn](https://github.com/rafaelanobre/utalearn)基础上开发而来。

---

## 快速开始

需要 **Python 3.12+**、**Node.js 18+**，以及 PATH 里的 **ffmpeg**。

Windows 双击 **`dev.cmd`**；macOS / Linux 运行 **`./dev.sh`**。
首次运行会自动装依赖并构建前端，之后秒开。浏览器会打开 <http://localhost:8000/>。

| 命令                   | 作用                                     |
| ---------------------- | ---------------------------------------- |
| `dev.cmd` / `./dev.sh` | 需要时才构建，单进程起在 :8000           |
| `dev.cmd --rebuild`    | 强制重新构建前端                         |
| `./dev.sh --dev`       | 前端走 vite :5173 热更新，API 仍在 :8000 |

一个进程同时提供页面和 API，关掉窗口即停止。

### 免安装（解压即用）

不想装 Python / Node / ffmpeg，直接用发行包。同一个版本提供两份压缩包，按需下载：

| 压缩包 | 体积 | 导出视频 | 说明 |
| --- | --- | --- | --- |
| `UtaLearnNext-<版本>-lite.zip` | ~285 MB | 取决于本机是否装了 Chrome | 搜索歌词、生成、跟唱、词汇卡全部可用 |
| `UtaLearnNext-<版本>-full.zip` | ~600 MB | ✅ 一定可用 | 额外内置 Chromium，干净机器也能导出 |

两者解压后双击 **`启动 Uta Learn Next.cmd`** 即可。都自带 Python 运行时、ffmpeg/ffprobe
与已构建好的前端；不写注册表、不改 PATH、不需要管理员权限。

数据默认写在文件夹内的 `localdata/` 与 `exports/`（便携语义，整个文件夹可拷走）；
如果文件夹不可写（例如解压到受保护目录），会自动回退到 `%LOCALAPPDATA%\UtaLearnNext\`。

自己打包：

```bash
python tools/build_portable.py                    # 同时产出 lite 与 full 两个 zip
python tools/build_portable.py --no-full          # 只做 lite
python tools/build_portable.py --no-zip           # 只生成文件夹
python tools/build_portable.py --out D:/build     # 换构建目录（磁盘空间不够时用）
python tools/build_portable.py --zip-out D:/rel --browsers-dir D:/br   # 大文件放别的盘
```

ffmpeg 用的是 **essentials（精简）构建**：静态链接、单个约 104 MB（全量版要 218 MB），
仍包含本应用需要的 `libx264`、`aac`、常见音频解码器与 `fps/setpts/tpad` 滤镜。
只有罕见格式（wma/ape/amr 等）可能解不开，导出与跟唱不受影响。

### Docker### Docker

```bash
docker compose up --build
```

---

## 怎么用

界面分「配置」和「展示」两个标签页。

### 配置：把一首歌变成可跟唱的数据集

流程是三步：**先放音频 → 再决定歌词从哪来 → 生成**。

**第 1 步 · 上传音频**（mp3 / wav / m4a / flac，最大 200MB）。跟唱必须有音频。

**第 2 步 · 选择歌词来源**，两种方式：

- **搜索歌词**：同时查 QQ 音乐、酷狗、Lrclib。QQ 音乐和酷狗给的是**逐字时间戳**
  （每个字都有起止时间，高亮最准），Lrclib 只有行级时间，行内按音拍长度分配。
- **自定义歌词**：直接粘贴文本，每行一句，不需要时间轴，用 whisper 在你上传的音频上自动对齐。

**第 3 步 · 生成**，完成后自动跳到展示页。

### 展示：跟唱

- 空格 播放 / 暂停，← → 前后 5 秒
- 倍速 0.25×–2×，点当前倍速向左展开选择
- 右下角进度条可点击跳转
- 导航栏「设置背景」可换展示页背景（默认纸感 / 自定义图片），「导出视频」渲染成 MP4

---

## 音频与歌词版本不一致怎么办

自己下载的音频常常和搜到的歌词不是同一版：片头被剪、TV size、重制版快一点点。
手动裁剪基本对不准，因为两条时间轴差的既有**偏移**也有**缩放**。

系统会自动处理：

1. 用 whisper 在你的音频上取词级锚点
2. 把源歌词行与锚点做单调 DP 对齐
3. 用稳健回归（Theil–Sen，先剔除离群锚点）拟合 `t_你的音频 = a + b · t_源`
   - `a` 吸收偏移（剪掉的前奏）
   - `b` 吸收速度差（重制、编码差异）
   - **`b` 只在足够大时才采纳**（见下）
4. 把变换套到源的**逐字**时间戳上，并按音频时长裁剪——自动对齐到较短的那个

关键是**保留源数据源的逐字精度**，只修正整体差异；而不是把歌词当纯文本重新对齐（那样会丢掉逐字信息）。

whisper 的词起点比真实起唱平均早约 0.45 秒（实测词起点 −0.49s、词终点 −1.36s、中点 −0.90s，
所以锚定词起点最优，再用常量补偿）。这个量可用环境变量 `UTALEARN_ONSET_LEAD` 调整。

### 为什么有时会「忽略」速度差

whisper 的起唱偏差不是固定值，会沿歌曲缓慢漂移，而漂移在数学上**和真实速度差长得一模一样**，
用锚点残差无法区分：受控实验里（把 braveheart 音频剪掉前 20 秒，真值就是 `b = 1`），自由拟合跑出
`b = 0.99582`，而且它的 RMS 残差**比只用偏移的拟合还低**。照单全收会让歌曲末尾累积 0.375 秒误差。

所以这里用先验而不是残差判断：只有同时满足 `|b−1| ≥ 0.6%` 且累计漂移 `≥ 1.2 秒` 才采纳斜率，
否则退回纯偏移。代价是 0.5% 以下的真实速度差会被有意忽略（此时全曲最大误差约 0.4 秒）。

实测（`tools/check_retime.py` 可复跑）：

| 场景                          | 拟合                              | 真值                 | 最大误差     |
| ----------------------------- | --------------------------------- | -------------------- | ------------ |
| 真实音频剪掉前 20 秒          | `a = -19.97s`、`b = 1.0`，12 锚点 | a = −20、b = 1       | **0.032 秒** |
| 合成真实速度差 +1.6%          | `a = -51.45s`、`b = 1.016`        | a = −51.9、b = 1.016 | < 0.01 秒    |
| 合成真实速度差 −1.0%          | `a = -11.55s`、`b = 0.99`         | a = −12、b = 0.99    | < 0.01 秒    |
| 亚阈值速度差 0.5%（有意忽略） | `a = -12.01s`、`b = 1.0`          | a = −12、b = 0.995   | 0.41 秒      |

拟合不可靠时（锚点太少、残差过大）会自动退回「把歌词当纯文本用 whisper 重新对齐」，不会产出错乱的时间轴。
音频只覆盖歌曲一部分时，尾部的歌词行会被裁掉；偏移后落在 0 之前的行会钳到 0。

---

## 导出视频

导航栏「导出视频」把当前这首渲染成 **1920×1080 / 60fps** 的 MP4，音频直接混流，不重新编码音轨。

- 成片时长 = **音频实际时长**（不是歌词时间轴长度——两者常常差几十秒）
- 录制按播放进度结束，慢机器不会截掉尾巴
- 视频轨若比音频短，会克隆末帧补齐，最后几秒不会没画面
- **录制时间轴会重新对齐**：浏览器录出来的 WebM 并不保证覆盖真实经过的时间，
  实测一首 221 秒的歌画面被拉长约 1.4%，表现为「开头正常、越到后面字幕越晚」。
  现在用「播放开始→结束」的墙钟时长除以录制跨度得到缩放系数，`setpts` 校正后再转 60fps
- 录完会读成片进度条像素反推音画偏差，必要时自动重混一次

需要 Playwright 的 Chromium 与 ffmpeg。浏览器路径可用 `UTALEARN_CHROME` 指定，否则用
Playwright 自带的、再退到系统 Chrome。

### 校验成片音画同步

```bash
python tools/check_export_sync.py exports/xxx.mp4 --audio localdata/<歌名>/audio.mp3
```

两项独立检查：把成片音轨与源音频做互相关（能发现音轨被移动或拉伸），以及读成片里
画进每一帧的进度条、与帧位置比较（能发现画面被缩放）。

> 进度条的像素映射本身有约 0.5% 的刻度偏差，所以 `BAR_LO/BAR_HI` 是实测标定出来的；
> 单看进度条会把工具误差当成画面误差，判断「是否漂移」时以谢幕卡这类**离散事件**为准。

---

## 词汇卡与语法卡

每句歌词下方最多 4 张卡（窗口窄时减少），语法命中占一席。

- **词卡**：辞书形 / 读音 / 词性 / JLPT / 中文释义，以及「歌中 X」提示原形
- **句型卡**：句型名 / 等级 / 中文解释 / 例句

选词**优先高阶**（同句内先挑 JLPT 更高的词），但**展示顺序仍按出现顺序**，不打乱阅读节奏。
落在句型范围内的词不会重复出卡。

词典约 **34,600 条**（其中 **18,100+** 条带 JLPT 分级），语法句型 **180 条**（N2 72 / N1 15）。
释义按词性区分义项。

---

## 目录结构

```
backend/
  main.py                 FastAPI 路由：搜索 / 上传 / 构建 / 播放 / 导出 / 背景
  app/
    sources.py            QQ 音乐、酷狗、Lrclib 歌词源
    builder.py            歌词 → 数据集（时间重映射、裁剪）
    retime.py             版本不一致时的自动重对时
    fallback.py           whisper + 能量兜底对齐
    dicts.py              分词、词典/句型查询、罗马音
    export.py             Playwright 录制 + ffmpeg 混流 + 自校准
    data/                 jadict.json（词典）、grammar.json（句型）
frontend/src/
  App.tsx                 标签页、导航栏、导出与背景入口
  components/             ConfigPage / Stage / Player / LyricsDisplay / VocabCards / BackgroundModal
  hooks/                  useSongData / useSyncEngine
  furigana.ts             只标汉字的注音切分
tools/                    数据构建与回归检查（见 tools/README.md）
localdata/                用户数据：数据集与上传（不提交）
exports/                  导出的成片（不提交）
```

## 运行数据在哪

- `localdata/<歌名>/song_data.json` — 时间轴、词元、词汇卡数据
- `localdata/<歌名>/audio.mp3` — 该数据集的音频
- `localdata/_uploads/` — 上传的原始音频（可清理）
- `localdata/_ui/` — 展示页背景设置
- `exports/` — 导出的 MP4

`localdata/` 与 `exports/` 都在 `.gitignore` 里。

---

## 环境变量

| 变量                  | 默认                    | 说明                                      |
| --------------------- | ----------------------- | ----------------------------------------- |
| `DATA_DIR`            | `../localdata`          | 数据集目录                                |
| `EXPORT_DIR`          | `../exports`            | 成片输出目录                              |
| `DEFAULT_SONG`        | `braveheart`            | 首次打开时的默认曲目                      |
| `UTALEARN_ONSET_LEAD` | `0.45`                  | whisper 起唱提前量的补偿秒数，设 `0` 关闭 |
| `UTALEARN_BASE_URL`   | `http://127.0.0.1:8000` | 导出时无头浏览器访问本服务的地址          |
| `UTALEARN_CHROME`     | 自动探测                | 导出用的 Chromium 路径                    |
| `UTALEARN_DATA_DIR`   | `localdata`             | `tools/backfill_glosses.py` 的目标目录    |
| `UTALEARN_TOMOSHI_DB` | `tools/_source/…`       | 重建词典时的源数据库                      |

---

## 开发

```bash
# 后端（带热重载）
cd backend && python -m uvicorn main:app --reload --port 8000

# 前端（热更新，代理到 :8000）
cd frontend && npm run dev

# 类型检查与构建
cd frontend && npx tsc --noEmit && npm run build

# 重对时回归检查
python tools/check_retime.py
```

接口一览：`/api/sources`、`/api/search`、`/api/uploads`、`/api/build`、`/api/build-text`、
`/api/jobs/{id}`、`/api/songs`、`/api/songs/{name}`、`/api/audio/{name}`、`/api/export`、
`/api/exports`、`/api/ui/background`。

---

## 许可与署名

本项目以 **GNU General Public License v3.0** 发布，全文见 [`LICENSE`](LICENSE)。

`backend/app/qrc_des.py` 是从
[LDDC](https://github.com/chenmozhijin/LDDC)（GPL-3.0）移植的 QQ 音乐 QRC 解密实现，
它随本项目分发，因此整个项目按 GPL-3.0 授权。若你需要闭源分发，必须自行移除该文件与
QQ 音乐歌词源（酷狗走独立实现，Lrclib 无需解密）。

随仓库分发的词典数据 `backend/app/data/jadict.json` 是
[Tomoshi 日语词典开放数据层](https://github.com/tomoshi-app/tomoshi-dict-data) 的衍生作品
（CC BY-SA 4.0），其上游为 JMdict / KANJIDIC2（© Electronic Dictionary Research and
Development Group，CC BY-SA）。该数据文件同样按 **CC BY-SA 4.0** 分发，署名见上。

本项目在[utalearn](https://github.com/rafaelanobre/utalearn)基础上开发而来。
日语形态素分析使用 [fugashi](https://github.com/polm/fugashi) + UniDic。
语音识别使用 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)。

歌词内容来自 QQ 音乐、酷狗、Lrclib，仅用于个人学习，请遵守各来源的服务条款；
分发由本工具生成的、包含受版权保护歌词的数据集可能构成侵权。
