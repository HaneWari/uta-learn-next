# tools — 数据构建与回归检查

这些脚本只在你需要**重新生成** `backend/app/data/` 里的词典/语法数据、或想验证对齐算法时才运行。
日常使用不需要它们，仓库里已包含生成好的结果。

所有脚本都从**仓库根目录**运行，路径自动解析，不依赖当前工作目录。

```bash
python tools/build_dict.py          # 重新生成 jadict.json
python tools/build_grammar.py       # 重新生成 grammar.json
python tools/backfill_glosses.py    # 给已有数据集补释义（默认演练，加 --apply 才写）
python tools/check_retime.py        # 重对时拟合的合成回归检查
```

## 词典数据源

`build_dict.py` 需要 Tomoshi 日语词典开放数据层（约 620 MB 的 SQLite）。
它**不在仓库里**，需要时自己下载：

```bash
# 1. 下载（86 MB 压缩包）
curl -L -o tools/_source/dict.db.zst \
  https://github.com/tomoshi-app/tomoshi-dict-data/releases/download/v2026-09-02/tomoshi-dict-open.db.zst

# 2. 解压（需要 zstandard：python -m pip install zstandard）
python -c "import zstandard,sys; \
f=open('tools/_source/dict.db.zst','rb'); o=open('tools/_source/tomoshi-dict-open.db','wb'); \
zstandard.ZstdDecompressor().copy_stream(f,o); o.close(); f.close()"

# 3. 生成
python tools/build_dict.py
```

也可以用 `UTALEARN_TOMOSHI_DB` 指向别处的数据库文件。

**许可与署名**：词典数据来自 [Tomoshi](https://github.com/tomoshi-app/tomoshi-dict-data)
（CC BY-SA 4.0），其上游为 JMdict / KANJIDIC2（© Electronic Dictionary Research and
Development Group，CC BY-SA）。`jadict.json` 是这些数据的衍生作品，同样按 CC BY-SA 4.0 分发。
`jadict.hand.json` 是项目自己整理、逐条校对过的条目，构建时优先级高于自动生成结果。

## 语法数据

`build_grammar.py` 不依赖外部数据：句型清单直接写在脚本里，只向
`backend/app/data/grammar.json` 追加尚不存在的 id，可安全重复运行。

## 回归检查

`check_retime.py` 用合成锚点验证 `backend/app/retime.py` 的拟合行为，覆盖：

- 真 `b = 1`（剪掉片头）必须还原成纯偏移
- 真速度差 ±1.0% / ±1.6% 必须保留斜率
- 亚阈值速度差（0.5%）被**有意**忽略
- ±0.6s 锚点噪声、3 个离群锚点
- 锚点不足 / 斜率越界时拒绝拟合

期望输出结尾是 `ALL PASS`。
