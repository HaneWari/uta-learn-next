"""User settings: one `settings.json` next to the data.

Settings are read on every use rather than cached at import time. The old
proxy probe cached its answer for the life of the process, so switching a
proxy on (or installing Clash) required restarting the app — and a machine
that started with a dead proxy stayed broken forever.

Unknown keys are preserved: a newer build may have written settings an older
build does not know about, and a downgrade must not silently delete them.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from app.paths import DATA_DIR

SETTINGS_FILE = DATA_DIR / "settings.json"
_LOCK = threading.Lock()

DEFAULTS: dict[str, Any] = {
    # 常规
    "update_check": True,
    "telemetry": True,
    "confirm_close": True,
    # 显示
    "particle_reading": "pron",      # pron | literal
    "long_vowel": "ou",              # ou | macron | oo
    "theme": "system",               # system | light | dark
    "reduce_motion": False,
    "ui_font": "m",                  # s | m | l : 界面字号
    "page_zoom": 1.0,                # 0.8 - 1.5 : 整页缩放
    "play_style": "default",         # default | karaoke : 播放页样式
    "karaoke_color": "red",          # red | coral | blue | green : 卡拉OK字幕主色
    "karaoke_custom_colors": False,  # 用下面的两只颜色替代主题预设
    "karaoke_before_color": "#FFFFFF",
    "karaoke_after_color": "#FF2020",
    "karaoke_before_stroke_color": "#000000",
    "karaoke_after_stroke_color": "#FFFFFF",
    "karaoke_stroke_width": 2,       # 1080p 基准的描边宽度
    "karaoke_glow": True,            # 走字后的外发光
    "karaoke_scanline_enabled": True,
    "karaoke_scanline_color": "#FFFFFF",
    "karaoke_scanline_width": 16,    # 1080p 基准的高光带宽
    "karaoke_font": "gothic",        # gothic | mincho | rounded
    "default_layers": {
        "furigana": True,
        "romaji": True,
        "translation": True,
        "next_line": True,
        "cards": True,
    },
    # 歌词
    "jlpt_max": 0,                   # 0 = 不过滤
    # 网络
    "proxy_mode": "auto",            # auto | system | manual | off
    "proxy_url": "",
    # 导出
    "export_preset": "landscape",    # landscape | portrait | 4k
    "export_pages": 3,
    # 匿名统计
    "install_id": "",
    "telemetry_last_day": "",
}


def _read() -> dict:
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def load() -> dict:
    """Defaults overlaid with whatever the user saved (unknown keys kept)."""
    merged = dict(DEFAULTS)
    saved = _read()
    for key, value in saved.items():
        if key == "default_layers" and isinstance(value, dict):
            merged[key] = {**DEFAULTS["default_layers"], **value}
        else:
            merged[key] = value
    return merged


def get(key: str, fallback: Any = None) -> Any:
    return load().get(key, DEFAULTS.get(key, fallback))


def save(patch: dict) -> dict:
    """Merge `patch` into the stored settings and return the result."""
    with _LOCK:
        current = _read()
        for key, value in patch.items():
            if key == "default_layers" and isinstance(value, dict):
                layers = current.get("default_layers")
                current["default_layers"] = {
                    **(layers if isinstance(layers, dict) else {}),
                    **value,
                }
            else:
                current[key] = value
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, SETTINGS_FILE)
    return load()


def reset() -> dict:
    SETTINGS_FILE.unlink(missing_ok=True)
    return load()


def data_dir() -> Path:
    return DATA_DIR
