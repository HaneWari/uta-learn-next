import { useEffect, useState } from "react";
import { api } from "../api";
import type { VocabEntry } from "../types";

/**
 * The personal word book: every saved word across songs, newest first.
 *
 * Deliberately not a second flashcard app — no SRS, no quiz. It exists so a
 * word noticed mid-song can be found again, with the line it came from, and
 * jumped back to.
 */
export function VocabBook({
  onClose,
  onPlaySong,
}: {
  onClose: () => void;
  onPlaySong?: (song: string, at: number) => void;
}) {
  const [items, setItems] = useState<VocabEntry[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [query, setQuery] = useState("");
  const [songFilter, setSongFilter] = useState<string>("");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      const data = await api.vocab();
      setItems(data.items);
      setCounts(data.counts);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const shown = items.filter((i) => {
    if (songFilter && i.song !== songFilter) return false;
    if (!query.trim()) return true;
    const q = query.trim().toLowerCase();
    return [i.text, i.kana, i.romaji, i.zh, i.line]
      .join(" ")
      .toLowerCase()
      .includes(q);
  });

  async function drop(entry: VocabEntry) {
    try {
      await api.removeVocab(entry);
      setItems((prev) =>
        prev.filter(
          (i) =>
            !(
              i.song === entry.song &&
              i.segment_id === entry.segment_id &&
              i.text === entry.text
            ),
        ),
      );
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="bgmask" role="dialog" aria-modal="true" aria-label="生词本">
      <div className="bgmodal bookmodal">
        <header className="bghead">
          <h2>生词本</h2>
          <button className="bgclose" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </header>

        <div className="book-tools">
          <input
            className="setinput"
            placeholder="搜索单词 / 读音 / 释义 / 歌词"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <select
            className="setselect"
            value={songFilter}
            onChange={(e) => setSongFilter(e.target.value)}
          >
            <option value="">全部歌曲（{items.length}）</option>
            {Object.entries(counts).map(([song, n]) => (
              <option key={song} value={song}>
                {song}（{n}）
              </option>
            ))}
          </select>
        </div>

        {err && <p className="setnote">{err}</p>}
        {loading && <p className="sethint">载入中…</p>}
        {!loading && !shown.length && (
          <p className="sethint">
            还没有生词。播放时点一下歌词里的词，就能把它加进来。
          </p>
        )}

        <div className="book-list">
          {shown.map((item) => (
            <article
              className="book-item"
              key={`${item.song}-${item.segment_id}-${item.text}`}
            >
              <header className="book-head">
                <span className="book-word">{item.text}</span>
                {item.kana && <span className="book-kana">{item.kana}</span>}
                {item.jlpt && <span className="wordpop-tag">{item.jlpt}</span>}
                <span className="book-song">{item.song_title || item.song}</span>
              </header>
              {item.romaji && <span className="book-romaji">{item.romaji}</span>}
              <p className="book-zh">
                {item.pos && <span className="wordpop-pos">{item.pos}</span>}
                {item.zh}
              </p>
              {item.line && <p className="book-line">{item.line}</p>}
              <div className="book-actions">
                {onPlaySong && (
                  <button
                    className="btn"
                    type="button"
                    onClick={() => {
                      onPlaySong(item.song, item.at);
                      onClose();
                    }}
                  >
                    回到这一句
                  </button>
                )}
                <button
                  className="btn"
                  type="button"
                  onClick={() => void drop(item)}
                >
                  删除
                </button>
              </div>
            </article>
          ))}
        </div>
      </div>
    </div>
  );
}
