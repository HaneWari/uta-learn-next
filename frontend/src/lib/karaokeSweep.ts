import type { KanaChar, WordTiming } from "../types";
import { rubyGroups } from "../furigana";

/**
 * 卡拉OK扫字的几何模型。
 *
 * 参考 Lin-K Lyrics(karaoke-studio)的 `wipe.py` / `scanline.py`:整行只有
 * **一条**向前推进的锋面,而不是每个字各自填充。已唱区域由锋面横坐标裁剪,
 * 所以字与字之间、词与词之间都是一次连续扫过 —— 这是“像真卡拉OK”和
 * “每个字轮流变色”的关键差别。
 *
 * 这里只做与像素无关的时间→字序映射;真实横坐标由组件量出每个字形的盒子
 * 后再换算,因此字体、字号、注音都不会让锋面错位。
 */

export interface SweepGlyph {
  ch: string;
  start: number;
  end: number;
}

export interface SweepGroup {
  /** 注音;没有读音的假名组为空 */
  reading?: string;
  /** 该组在整行字形数组里的范围 [from, to) */
  from: number;
  to: number;
}

export interface SweepWord {
  groups: SweepGroup[];
}

/** 缺 `chars` 的旧数据集:按字数均分整个词的时长。 */
function charsWithTimes(word: WordTiming): KanaChar[] {
  if (word.chars?.length) return word.chars;
  const chars = [...(word.text ?? "")];
  const n = Math.max(chars.length, 1);
  const span = Math.max(0, word.end - word.start) / n;
  return chars.map((ch, i) => ({
    ch,
    start: word.start + i * span,
    end: word.start + (i + 1) * span,
  }));
}

/**
 * 个别旧数据集带 `chars` 但每个字的时间都是 0(只有词级时间)。
 * 直接使用会让整句在 0 秒瞬间“唱完”,看起来像没有高亮,所以这类字
 * 也按字均分词的时间。
 */
function normaliseTimes(chars: KanaChar[], word: WordTiming): KanaChar[] {
  const hasTiming = chars.some((c) => c.end > c.start);
  if (hasTiming) return chars;
  const span = Math.max(0, word.end - word.start) / Math.max(chars.length, 1);
  return chars.map((c, i) => ({
    ch: c.ch,
    start: word.start + i * span,
    end: word.start + (i + 1) * span,
  }));
}

export function buildLine(words: WordTiming[]): {
  words: SweepWord[];
  glyphs: SweepGlyph[];
} {
  const glyphs: SweepGlyph[] = [];
  const out: SweepWord[] = [];
  for (const word of words) {
    const chars = normaliseTimes(charsWithTimes(word), word);
    // 交给 `rubyGroups` 做“只有汉字带读音”的切分,时间随字形一起走
    const groups = rubyGroups({ text: word.text, kana: word.kana, chars });
    const built: SweepGroup[] = [];
    for (const group of groups) {
      const from = glyphs.length;
      for (const ch of group.chars) {
        glyphs.push({ ch: ch.ch, start: ch.start, end: ch.end });
      }
      built.push({ reading: group.reading, from, to: glyphs.length });
    }
    out.push({ groups: built });
  }
  return { words: out, glyphs };
}

/**
 * 当前时间落在哪个字形 / 哪段间隙里。
 *
 * `gap` 为真时表示已经唱完 `index` 这个字、还没到下一个字;`frac` 是这段
 * 间隙的进度,组件据此把锋面从上一字的右沿平移下一字的左沿,避免视觉上
 * 的“跳格”。
 */
export interface SweepPos {
  index: number;
  frac: number;
  gap: boolean;
}

export function sweepAt(glyphs: SweepGlyph[], t: number): SweepPos {
  if (!glyphs.length) return { index: 0, frac: 0, gap: false };
  if (t <= glyphs[0].start) return { index: 0, frac: 0, gap: false };
  for (let i = 0; i < glyphs.length; i += 1) {
    const g = glyphs[i];
    if (t < g.start) {
      const prev = glyphs[i - 1];
      const a = prev.end;
      const b = g.start;
      const frac = b > a ? Math.min(1, Math.max(0, (t - a) / (b - a))) : 1;
      return { index: i - 1, frac, gap: true };
    }
    if (t < g.end) {
      const span = Math.max(0.001, g.end - g.start);
      return {
        index: i,
        frac: Math.min(1, Math.max(0, (t - g.start) / span)),
        gap: false,
      };
    }
  }
  return { index: glyphs.length - 1, frac: 1, gap: false };
}
