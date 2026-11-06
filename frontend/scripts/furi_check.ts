import { rubyGroups } from "../src/furigana";

const cases: [string, string][] = [
  ["逃げ", "にげ"],
  ["溶けて", "とけて"],
  ["あきらめる", "あきらめる"],
  ["コト", "こと"],
  ["一瞬", "いっしゅん"],
  ["二人", "ふたり"],
  ["空", "そら"],
  ["広がる", "ひろがる"],
  ["全て", "すべて"],
  ["分かった", "わかった"],
  ["東京", "とうきょう"],
  ["大人", "おとな"],
  ["話し合い", "はなしあい"],
  ["打ち合わせ", "うちあわせ"],
  ["食べ物", "たべもの"],
  ["見つける", "みつける"],
  ["今日", "きょう"],
  ["一人", "ひとり"],
  ["誰", "だれ"],
  ["姿", "すがた"],
];

for (const [text, kana] of cases) {
  const chars = [...text].map((ch) => ({ ch, start: 0, end: 0 }));
  const groups = rubyGroups({ text, kana, chars });
  const shown = groups
    .map(
      (g) =>
        `${g.reading ? g.reading + "/" : ""}${g.chars.map((c) => c.ch).join("")}`,
    )
    .join(" ");
  console.log(`${text.padEnd(8)} ${kana.padEnd(8)} → ${shown}`);
}
