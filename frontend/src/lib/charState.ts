import type { SyncState } from "../hooks/useSyncEngine";

/**
 * 高亮单位是字,不是词 —— 与 LDDC 的 `LyricsWord(start, end, text)` 模型一致:
 * 每个字形都有自己的起止时间,所以扫色可以跟着长音逐字推进。
 *
 * 默认样式和卡拉OK样式必须共用这一份判断,否则同一句在两种排版下会停在
 * 不同的字上。
 */
export type CharState = "sung" | "active" | "upcoming";

export function charState(
  syncState: SyncState,
  segmentId: number,
  wordIndex: number,
  charIndex: number,
): CharState {
  if (
    syncState.activeSegmentId === segmentId &&
    syncState.activeWordIndex === wordIndex &&
    syncState.activeKanaIndex === charIndex
  ) {
    return "active";
  }
  // anything already finished stays lit, so the line never flickers back
  if (syncState.sungSegmentId === segmentId && syncState.sungWordIndex !== null) {
    const sw = syncState.sungWordIndex;
    const sc = syncState.sungKanaIndex ?? -1;
    if (wordIndex < sw) return "sung";
    if (wordIndex === sw && charIndex <= sc) return "sung";
  }
  return "upcoming";
}
