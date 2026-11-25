# 第三方组件与许可

Uta Learn Next 以 **GPL-3.0** 发布。下面列出随发行包分发的第三方组件及其许可。
如果你重新分发本项目的构建产物,需要一并保留这些声明。

---

## 随核心包分发

| 组件 | 版本 | 许可 | 用途 |
| --- | --- | --- | --- |
| Python | 3.13 | PSF License | 嵌入式运行时 |
| FastAPI / Starlette / Uvicorn | 见 `backend/requirements.lock` | MIT / BSD-3-Clause | HTTP 服务 |
| pydantic | 见 lock | MIT | 请求校验 |
| httpx / httpcore / h2 | 见 lock | BSD-3-Clause | 歌词源、扩展包下载 |
| numpy | 见 lock | BSD-3-Clause | 音频与信号处理 |
| Pillow | 见 lock | HPND | 导出帧校准 |
| fugashi + UniDic-lite | 见 lock | MIT / BSD | 日语形态素分析 |
| ctranslate2 | 见 lock | MIT | 语音识别与翻译推理 |
| faster-whisper | 见 lock | MIT | 切片转写 |
| tokenizers / huggingface_hub | 见 lock | Apache-2.0 | 模型加载 |
| av (PyAV) | 见 lock | BSD-3-Clause | 音频解码 |
| sentencepiece | 见 lock | Apache-2.0 | 翻译模型分词 |
| playwright | 见 lock | Apache-2.0 | 驱动无头浏览器渲染 |
| pywebview / pythonnet | 见 lock | BSD-3-Clause / MIT | 桌面窗口 |
| ffmpeg(essentials 静态构建) | 见 `BUILD_INFO.json` | **GPL-3.0**(含 libx264) | 音频探测、视频合成 |
| ffprobe | 同上 | GPL-3.0 | 时长探测 |
| React / React DOM | 见 `frontend/package.json` | MIT | 前端 |
| Vite / TypeScript / ESLint | 见 lock | MIT | 构建工具(不进发行包) |

ffmpeg 的静态构建来自 <https://www.gyan.dev/ffmpeg/builds/>,对应源码可从
<https://ffmpeg.org/download.html> 获取;GPL 要求再分发时提供对应源码的获取方式,
本项目通过上述链接满足。

---

## 扩展包(可选,单独下载)

### `UtaLearnNext-custom-lyrics.zip`

| 组件 | 许可 | 用途 |
| --- | --- | --- |
| Systran/faster-whisper-small | MIT | 日语语音识别 |
| Helsinki-NLP/opus-mt-ja-zh(int8 CT2 转换) | **CC-BY-4.0** | 日→中翻译 |

opus-mt-ja-zh 采用 CC-BY-4.0,要求署名。再分发该扩展包时请保留以上署名与许可链接。

### `UtaLearnNext-chromium.zip`

| 组件 | 许可 |
| --- | --- |
| Chromium(Playwright 构建) | BSD-3-Clause 及若干第三方许可,见包内 `LICENSE` |

---

## 数据文件

| 文件 | 来源 | 许可 |
| --- | --- | --- |
| `backend/app/data/jadict.json` | [Tomoshi 日语词典开放数据层](https://github.com/tomoshi-app/tomoshi-dict-data),上游为 JMdict / KANJIDIC2 | **CC BY-SA 4.0** |
| `backend/app/data/grammar.json` | 本项目整理 | 同本项目 |
| `backend/app/qrc_des.py` | 移植自 [LDDC](https://github.com/chenmozhijin/LDDC) | GPL-3.0 |

JMdict / KANJIDIC2 © Electronic Dictionary Research and Development Group,
按 CC BY-SA 许可使用。

---

## 歌词内容

歌词由 QQ 音乐、酷狗、Lrclib 提供,仅用于个人学习。分发由本工具生成的、
包含受版权保护歌词的数据集可能构成侵权 —— 这一点与软件许可无关,请自行判断。
