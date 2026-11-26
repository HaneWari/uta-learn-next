"""Render `frontend/public/favicon.svg` into `tools/assets/app.ico`.

The favicon is the app's only real mark — the same 唄-in-a-circle the browser
tab shows — so the launcher's icon has to come from that file rather than a
second drawing that would drift away from it. One source, every size Windows
asks for (16 → 256 px).

Run after editing the favicon: `python tools/make_icon.py`
Requires `cairosvg` and Pillow (both dev-only; the build only reads the .ico).
"""
from __future__ import annotations

import io
from pathlib import Path

import cairosvg
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "frontend" / "public" / "favicon.svg"
OUT = ROOT / "tools" / "assets" / "app.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(size: int) -> Image.Image:
    png = cairosvg.svg2png(url=str(SVG), output_width=size, output_height=size)
    return Image.open(io.BytesIO(png)).convert("RGBA")


def main() -> int:
    if not SVG.exists():
        raise SystemExit(f"缺少图标源文件 {SVG}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames = [render(s) for s in SIZES]
    # Pillow writes only the largest frame unless the rest are appended
    frames[-1].save(OUT, format="ICO", sizes=[(s, s) for s in SIZES],
                    append_images=frames[:-1])
    print(f"已生成 {OUT} ({OUT.stat().st_size / 1024:.0f} KB, {len(SIZES)} 个尺寸)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
