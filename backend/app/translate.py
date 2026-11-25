"""Offline ja-zh translation via a bundled opus-mt model.

The model lives in `models/translate-ja-zh/` next to the app (a CTranslate2
conversion of Helsinki-NLP/opus-mt-ja-zh, int8) and ships as its own
version-independent extension pack — same contract as `whisper-small`.
Translation only ever runs inside a build job (never on the config page), so
a missing pack surfaces as a clear, actionable error at generation time.

Tokenisation is plain SentencePiece (`source.spm` / `target.spm`), so the pack
needs only `sentencepiece` on top of `ctranslate2` — no `transformers`.
"""
from __future__ import annotations

import threading
from pathlib import Path

MODEL_DIRNAME = "translate-ja-zh"

_translator = None
_sp_source = None
_sp_target = None


def _model_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "models" / MODEL_DIRNAME


def installed() -> bool:
    return (_model_dir() / "model.bin").is_file()


def _missing_msg() -> str:
    return (
        "未找到中文翻译模型。请把翻译扩展包解压到应用目录，得到 "
        f"models/{MODEL_DIRNAME}/model.bin 后重启，或在自定义歌词页取消勾选「开启中文翻译」。"
    )


_LOAD_LOCK = threading.Lock()


def _load():
    global _translator, _sp_source, _sp_target
    if _translator is not None:
        return _translator, _sp_source, _sp_target
    # Two builds can finish at once (a retry plus the original). Without the
    # lock both loaded a 200 MB model and one was thrown away — the kind of
    # waste that turns into an OOM on a small laptop.
    with _LOAD_LOCK:
        if _translator is not None:
            return _translator, _sp_source, _sp_target
        root = _model_dir()
        if not installed():
            raise RuntimeError(_missing_msg())
        from ctranslate2 import Translator
        from sentencepiece import SentencePieceProcessor

        _translator = Translator(str(root), device="cpu", compute_type="int8")
        _sp_source = SentencePieceProcessor(model_file=str(root / "source.spm"))
        _sp_target = SentencePieceProcessor(model_file=str(root / "target.spm"))
    return _translator, _sp_source, _sp_target


def translate_lines(lines: list[str]) -> list[str]:
    """Translate a batch of lyric lines; one zh string per input line."""
    if not lines:
        return []
    translator, sp_src, sp_tgt = _load()
    # CTranslate2 expects SentencePiece *pieces* (the leading "▁"), not ids
    # and the Marian decoder needs a trailing </s> on the source or it never
    # stops cleanly — the HF tokenizer appends it implicitly, we must too.
    src = [sp_src.encode(line, out_type=str) + ["</s>"] for line in lines]
    out = translator.translate_batch(src, beam_size=4, max_decoding_length=256)
    return [sp_tgt.decode(hyp.hypotheses[0]).strip() for hyp in out]
