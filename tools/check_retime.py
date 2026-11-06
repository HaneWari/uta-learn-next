"""Synthetic check for retime: does it predict the right times?

Asserts prediction accuracy rather than parameter identity, since a sub-threshold
slope is deliberately ignored (see MIN_SLOPE / MIN_DRIFT in retime.py).
"""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
import app.retime as rt  # noqa: E402

LINES = [
    "夜明けの風が窓を叩いて", "君の声だけが遠くなる", "忘れないと決めたのに",
    "季節はまた巡ってくる", "駅のホームに立つ影法師", "切符の端に書いた名前",
    "笑い声がまだ残ってる", "写真の中の幼い二人", "いつか会えると信じてた",
    "約束だけが増えていく", "雨上がりの空を見上げて", "虹の向こうに君がいた",
    "手を振る背中が小さくなる", "ありがとうと言えなかった", "今さら遅いと知ってても",
    "この歌だけは届けたい", "夜空に浮かぶ月のように", "静かに君を照らしたい",
    "もう一度だけ会いたいと", "願い続けた夜があった",
]
starts = [10.0 + 8.7 * i for i in range(len(LINES))]


def build(a, b, noise=0.0, outliers=()):
    """Return (parsed, wsegs) for a source whose true mapping is a + b*t."""
    lines = [{"start": t, "units": [(ch, t, t + 0.2) for ch in text]}
             for t, text in zip(starts, LINES)]
    wsegs = []
    for i, (t, text) in enumerate(zip(starts, LINES)):
        y = a + b * t + (noise * (1 if i % 2 else -1))
        if i in outliers:
            y += 7.0
        wsegs.append({"start": y, "end": y + 2.0, "text": text,
                      "words": [{"w": text, "s": y, "e": y + 2.0}]})
    return SimpleNamespace(lines=lines), wsegs


ok_all = True
print("ONSET_LEAD =", rt.ONSET_LEAD,
      "| MIN_SLOPE =", rt.MIN_SLOPE, "| MIN_DRIFT =", rt.MIN_DRIFT)

# (label, kwargs, true a, true b, max allowed prediction error, want slope kept)
cases = [
    ("完整音频 (真 a=-30 b=1)", dict(a=-30.0, b=1.0), -30.0, 1.0, 0.10, False),
    ("剪掉前 20s (真 a=-20 b=1)", dict(a=-20.0, b=1.0), -20.0, 1.0, 0.10, False),
    ("真实速度差 +1.6% (真 a=-51.9 b=1.016)", dict(a=-51.9, b=1.016), -51.9, 1.016, 0.10, True),
    ("真实速度差 -1.0% (真 a=-12 b=0.99)", dict(a=-12.0, b=0.99), -12.0, 0.99, 0.10, True),
    ("±0.6s 噪声 + 真 b=1", dict(a=-12.0, b=1.0, noise=0.6), -12.0, 1.0, 0.70, False),
    ("3 个离群锚点 (真 a=-30 b=1)", dict(a=-30.0, b=1.0, outliers={3, 9, 15}), -30.0, 1.0, 0.10, False),
    # 亚阈值斜率（0.5%，漂移 0.83s < MIN_DRIFT）会被有意忽略：最多漂移 0.83s
    ("亚阈值斜率 0.5% 被忽略 (真 a=-12 b=0.995)",
     dict(a=-12.0, b=0.995), -12.0, 0.995, 1.30, False),
]

for label, kw, ta, tb, tol, want_slope in cases:
    parsed, wsegs = build(**kw)
    r = rt.fit(parsed, wsegs)
    if r is None:
        print(f"FAIL  {label}: fit returned None")
        ok_all = False
        continue
    # prediction error at every source line, against the true mapping
    errs = [(r["a"] + r["b"] * t) - (ta + tb * t + rt.ONSET_LEAD) for t in starts]
    mx = max(abs(e) for e in errs)
    kept_slope = abs(r["b"] - 1.0) > 1e-9
    good = mx <= tol and kept_slope == want_slope and r["ok"]
    ok_all &= good
    print(f"\n{'PASS' if good else 'FAIL'}  {label}")
    print(f"      a={r['a']:+.3f} b={r['b']:.5f} 斜率{'保留' if kept_slope else '忽略'}"
          f" (期望{'保留' if want_slope else '忽略'})")
    print(f"      最大预测误差 {mx:.3f}s (允许 {tol:.2f})  锚点 {r['anchors']}"
          f"  残差 {r['residual']:.3f}s  ok={r['ok']}")
    print(f"      {rt.describe(r)}")

parsed, wsegs = build(a=-30.0, b=1.0)
print("\n拒绝路径:")
print("  仅 3 行 ->", rt.fit(SimpleNamespace(lines=parsed.lines[:3]), wsegs[:3]))
print("  斜率越界 b=1.6 ->", rt.fit(*build(a=-30.0, b=1.6)))

print("\nALL PASS" if ok_all else "\nSOME FAILED")
