import type { WordTiming } from "../types";
import { rubyGroups } from "../furigana";

/** Furigana sits above a kanji run only; kana runs reserve the same height. */
export function RubySurface({
  word,
  renderChar,
  showFurigana = true,
}: {
  word: WordTiming;
  renderChar: (ch: string, index: number) => React.ReactNode;
  /** the 注音 layer can be switched off per song; the glyphs stay put */
  showFurigana?: boolean;
}) {
  // The glyph offset of each ruby group, computed without a mutable counter —
  // the compiler rejects a variable reassigned during render because children
  // callbacks are deferred. Groups are tiny, so the quadratic prefix sum is
  // irrelevant next to the clarity of staying immutable.
  const groups = rubyGroups(word);
  const offsets = groups.map((_, i) =>
    groups.slice(0, i).reduce((n, g) => n + g.chars.length, 0),
  );
  return (
    <span className={`surface${showFurigana ? "" : " no-furi"}`}>
      {groups.map((group, gi) => (
        <span className="ruby-group" key={gi}>
          <span className={`furi${group.reading && showFurigana ? "" : " blank"}`}>
            {group.reading ?? ""}
          </span>
          <span className="ruby-chars">
            {group.chars.map((c, k) => renderChar(c.ch, offsets[gi] + k))}
          </span>
        </span>
      ))}
    </span>
  );
}
