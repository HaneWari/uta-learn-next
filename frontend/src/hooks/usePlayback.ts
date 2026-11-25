import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import type { Segment } from "../types";

export const SPEEDS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2] as const;

/**
 * Playback state that more than one component needs: speed, single-line loop
 * and shadowing (跟读). The audio element stays the source of truth for the
 * playhead; everything here is derived from it.
 *
 * Kept out of `Player` because the keyboard shortcuts, the lyric list and the
 * loop indicator all have to agree, and passing six callbacks down through the
 * stage got unmanageable.
 */
export function usePlayback(
  audioRef: RefObject<HTMLAudioElement | null>,
  segments: Segment[],
) {
  const [rate, setRateState] = useState(1);
  const [loopSegment, setLoopSegment] = useState<Segment | null>(null);
  const [shadow, setShadow] = useState(false);
  const shadowTimer = useRef<number | null>(null);

  const setRate = useCallback(
    (value: number) => {
      const a = audioRef.current;
      setRateState(value);
      if (a) a.playbackRate = value;
    },
    [audioRef],
  );

  const stepRate = useCallback(
    (dir: 1 | -1) => {
      // read the current speed from the element: it is updated synchronously
      // by `setRate`, so stepping twice in a row from a shortcut works even
      // before React has re-rendered with the new state
      const current = audioRef.current?.playbackRate ?? 1;
      const at = SPEEDS.indexOf(current as (typeof SPEEDS)[number]);
      const next = SPEEDS[Math.min(SPEEDS.length - 1, Math.max(0, at + dir))];
      setRate(next);
    },
    [audioRef, setRate],
  );

  /** Play one line, then jump back to its start and keep going. */
  const toggleLoop = useCallback(
    (segment: Segment | null) => {
      setLoopSegment((prev) => (prev && segment && prev.id === segment.id ? null : segment));
    },
    [],
  );

  // The loop itself: check on timeupdate rather than in the rAF loop, so it
  // keeps working while the stage is paused and resumed.
  useEffect(() => {
    const a = audioRef.current;
    if (!a || !loopSegment) return;
    const onTime = () => {
      if (a.currentTime > loopSegment.end - 0.05) {
        a.currentTime = Math.max(0, loopSegment.start);
        void a.play();
      }
    };
    a.addEventListener("timeupdate", onTime);
    return () => a.removeEventListener("timeupdate", onTime);
  }, [audioRef, loopSegment]);

  /**
   * 跟读: pause at the end of each line for a beat, then wait for the user.
   * The pause length scales with the line so a long line gets more thinking
   * time; `Enter` (or a click) resumes.
   */
  useEffect(() => {
    const a = audioRef.current;
    if (!a || !shadow) return;
    const onTime = () => {
      if (shadowTimer.current !== null) return;
      const near = segments.find(
        (s) => Math.abs(a.currentTime - s.end) < 0.25 && a.currentTime >= s.end - 0.3,
      );
      if (!near) return;
      a.pause();
      const wait = Math.min(6, Math.max(1.2, (near.end - near.start) * 1.2));
      shadowTimer.current = window.setTimeout(() => {
        shadowTimer.current = null;
        a.currentTime = near.end + 0.01;
        void a.play();
      }, wait * 1000);
    };
    a.addEventListener("timeupdate", onTime);
    return () => {
      a.removeEventListener("timeupdate", onTime);
      if (shadowTimer.current !== null) {
        window.clearTimeout(shadowTimer.current);
        shadowTimer.current = null;
      }
    };
  }, [audioRef, shadow, segments]);

  return {
    rate,
    setRate,
    stepRate,
    loopSegment,
    toggleLoop,
    shadow,
    toggleShadow: () => setShadow((v) => !v),
  };
}
