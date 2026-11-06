import { useState, useEffect, useRef, useMemo } from "react";
import type { SongData } from "../types";

interface FlatKana {
  segmentId: number;
  wordIndex: number;
  charIndex: number;
  start: number;
  end: number;
}

export interface SyncState {
  /** kana currently sounding (null during gaps / between lines) */
  activeSegmentId: number | null;
  activeWordIndex: number | null;
  activeKanaIndex: number | null;
  /** last kana that finished sounding — keeps the line lit through gaps */
  sungSegmentId: number | null;
  sungWordIndex: number | null;
  sungKanaIndex: number | null;
  /** segment shown on the stage — rolls to the next line once the
   *  current one has fully finished */
  displayIndex: number;
  /** true during the closing seconds, when the stage bows out */
  outro: boolean;
}

const INITIAL: SyncState = {
  activeSegmentId: null,
  activeWordIndex: null,
  activeKanaIndex: null,
  sungSegmentId: null,
  sungWordIndex: null,
  sungKanaIndex: null,
  displayIndex: 0,
  outro: false,
};

/** rightmost index whose `key` is <= time */
function search<T>(items: T[], time: number, key: (item: T) => number): number {
  let lo = 0;
  let hi = items.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >>> 1;
    if (key(items[mid]) <= time) {
      found = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return found;
}

export function useSyncEngine(
  songData: SongData | null,
  audioRef: React.RefObject<HTMLAudioElement | null>,
) {
  const [syncState, setSyncState] = useState<SyncState>(INITIAL);
  const rafRef = useRef<number>(0);
  const lastRef = useRef<SyncState>(INITIAL);
  const lastTimeRef = useRef<number>(-1);
  // the position the stage is following: the audio playhead when there is one,
  // otherwise the synthetic clock. Kept in a ref so reading it per frame does
  // not trigger React renders.
  const clockRef = useRef<number>(0);

  // Flatten every kana of every word into one timeline.
  const flatKana = useMemo<FlatKana[]>(() => {
    if (!songData) return [];
    const out: FlatKana[] = [];
    for (const seg of songData.segments) {
      for (let wi = 0; wi < seg.words.length; wi++) {
        const w = seg.words[wi];
        if (w.chars && w.chars.length) {
          for (let ci = 0; ci < w.chars.length; ci++) {
            const c = w.chars[ci];
            out.push({
              segmentId: seg.id,
              wordIndex: wi,
              charIndex: ci,
              start: c.start,
              end: c.end,
            });
          }
        } else {
          out.push({
            segmentId: seg.id,
            wordIndex: wi,
            charIndex: 0,
            start: w.start,
            end: w.end,
          });
        }
      }
    }
    out.sort((a, b) => a.start - b.start);
    return out;
  }, [songData]);

  useEffect(() => {
    if (!flatKana.length || !songData) return;
    const segments = songData.segments;
    const totalDur = songData.meta.duration_seconds || segments[segments.length - 1]?.end || 0;
    const virt = { t: 0, last: performance.now() };

    function tick() {
      const audio = audioRef.current;
      const real = audio && isFinite(audio.duration) && audio.duration > 0;

      if (real) {
        const time = audio.currentTime;
        clockRef.current = time;
        // Recompute whenever the playhead moved — playback, seeking or
        // scrubbing while paused. Skip the work when nothing changed.
        if (time !== lastTimeRef.current) {
          lastTimeRef.current = time;
          sync(time, audio.duration || 0);
        }
      } else if (totalDur > 0) {
        // No audio file: run a synthetic clock so the stage still performs.
        const now = performance.now();
        const dt = Math.min(0.1, (now - virt.last) / 1000);
        virt.last = now;
        virt.t = (virt.t + dt) % totalDur;
        clockRef.current = virt.t;
        sync(virt.t, totalDur);
      }

      rafRef.current = requestAnimationFrame(tick);
    }

    function sync(time: number, total: number) {
        // word being sung right now
        const at = search(flatKana, time, (k) => k.start);
        // last kana that already finished
        const done = search(flatKana, time, (k) => k.end);

        let segId: number | null = null;
        let wordIdx: number | null = null;
        let kanaIdx: number | null = null;

        if (at >= 0) {
          const fk = flatKana[at];
          if (time < fk.end) {
            segId = fk.segmentId;
            wordIdx = fk.wordIndex;
            kanaIdx = fk.charIndex;
          }
        }

        let sungSeg: number | null = null;
        let sungWord: number | null = null;
        let sungKana: number | null = null;
        if (done >= 0) {
          const fk = flatKana[done];
          sungSeg = fk.segmentId;
          sungWord = fk.wordIndex;
          sungKana = fk.charIndex;
        }

        // stage follows the last started kana, rolling over when the
        // current line has fully finished
        let disp = 0;
        if (at >= 0) {
          disp = flatKana[at].segmentId;
          const segEnd = segments[disp]?.end;
          if (segEnd != null && time > segEnd) {
            disp = Math.min(disp + 1, segments.length - 1);
          }
        }

        // The curtain must never cover a lyric line. Basing it on the total
        // duration is wrong when the last line sits inside the tail: an 84s
        // cut whose final line starts at 78s would hide that line completely.
        // Start the bow-out only after the last line has been sung.
        const lastLineEnd = segments.length
          ? segments[segments.length - 1].end
          : 0;
        const outro = total > 0 && lastLineEnd > 0 && time > lastLineEnd - 0.4;

        const last = lastRef.current;
        if (
          segId !== last.activeSegmentId ||
          wordIdx !== last.activeWordIndex ||
          kanaIdx !== last.activeKanaIndex ||
          sungSeg !== last.sungSegmentId ||
          sungWord !== last.sungWordIndex ||
          sungKana !== last.sungKanaIndex ||
          disp !== last.displayIndex ||
          outro !== last.outro
        ) {
          lastRef.current = {
            activeSegmentId: segId,
            activeWordIndex: wordIdx,
            activeKanaIndex: kanaIdx,
            sungSegmentId: sungSeg,
            sungWordIndex: sungWord,
            sungKanaIndex: sungKana,
            displayIndex: disp,
            outro,
          };
          setSyncState(lastRef.current);
        }
    }

    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [flatKana, audioRef, songData]);

  return { syncState, clockRef };
}
