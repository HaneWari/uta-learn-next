import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useCallback } from "react";
import type { GrammarHit, Segment, WordTiming } from "../types";
import {
  computeCardBudget,
  computeCards,
  EXTRA_BASE,
  normGrammar,
  normOverride,
  reorderPreview,
} from "../lib/cards";
import type { CardData } from "../lib/cards";
import { useSettings } from "../lib/settings";
import { pushUndo } from "../lib/saveQueue";
import { displayRomaji } from "../lib/romaji";
import { GrammarCard, VocabCard } from "./VocabCard";
import { editToWord, grammarToEdit, wordToEdit } from "./cardEdit";
import type { GrammarEdit, VocabEdit } from "./cardEdit";

/** How many vocabulary cards the current window can carry. */
function useCardBudget() {
  const [budget, setBudget] = useState(() => computeCardBudget(window.innerWidth));

  useEffect(() => {
    const onResize = () => setBudget(computeCardBudget(window.innerWidth));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  return budget;
}

/** Context menu state for delete / add. */
interface MenuState {
  x: number;
  y: number;
  target: CardData | null; // null = clicked empty space → "add card"
}

/**
 * Cards for the line on stage: real dictionary words (lemma + reading + POS +
 * Chinese gloss + JLPT) plus any grammar pattern the line contains.
 *
 * Auto-picks are only a draft — every card can be fixed in place. Edits are
 * persisted into the dataset so the exporter renders the corrected cards.
 */
export function VocabCards({
  segment,
  onPatch,
  hidden = false,
  onToggleHidden,
  transHidden = false,
  onToggleTrans,
  song,
  layers,
  onToggleLayer,
}: {
  segment: Segment | null;
  /** needed by the undo stack so Ctrl+Z only reverts this song's edits */
  song?: string;
  onPatch?: (patch: {
    vocab_override?: Segment["vocab_override"];
    grammar_extra?: Segment["grammar_extra"];
  }) => Segment | undefined;
  /** whole-song toggle: collapse the row to a slim bar (still right-clickable) */
  hidden?: boolean;
  onToggleHidden?: () => void;
  /** whole-song toggle for the lyric gloss — shown in the same ctx menu */
  transHidden?: boolean;
  onToggleTrans?: () => void;
  /** per-song presentation layers, toggled from the same menu */
  layers?: { furigana: boolean; romaji: boolean; next_line: boolean };
  onToggleLayer?: (key: "furigana" | "romaji" | "next_line") => void;
}) {
  const budget = useCardBudget();
  const [settings] = useSettings();
  const [menu, setMenu] = useState<MenuState | null>(null);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [draft, setDraft] = useState<VocabEdit | GrammarEdit | null>(null);
  // freeze the row while a card is being edited so a field change that
  // resizes the card can't bounce the input under the cursor
  const [locked, setLocked] = useState<CardData[] | null>(null);
  const [localSeg, setLocalSeg] = useState<Segment | null>(null);
  const eff = localSeg ?? segment;
  // the JLPT filter is a setting, so it has to be read here rather than baked
  // into the dataset: changing it re-picks the row without touching the file
  const live = computeCards(eff, budget, settings.jlpt_max);
  const cards = locked ?? live;
  const empty = !cards.length;

  // resync when the parent pushes a fresh dataset (e.g. another song, or a
  // server-side reload); localSeg only lives for the current segment's edits
  useEffect(() => {
    setLocalSeg(null);
  }, [segment?.id]);

  /* ---- drag to reorder (every card, FLIP-animated) ---- */
  const [dragKey, setDragKey] = useState<string | null>(null);
  const [overKey, setOverKey] = useState<string | null>(null);
  const rowRef = useRef<HTMLDivElement | null>(null);
  // first-frame positions captured before a reorder so each card can be
  // inverted back to where it was, then released into the new slot
  const prevRects = useRef<Map<string, number> | null>(null);

  const baseKeys = cards.map((c) => c.key);
  const previewKeys =
    dragKey !== null && overKey !== null && dragKey !== overKey
      ? reorderPreview(baseKeys, dragKey, overKey)
      : baseKeys;
  const byKey = new Map(cards.map((c) => [c.key, c] as const));
  const renderedCards: CardData[] = previewKeys
    .map((k) => byKey.get(k))
    .filter((c): c is CardData => !!c);

  // FLIP: after React commits the reordered row, shift every moved card back
  // to its old x and let the transition carry it into place.
  useLayoutEffect(() => {
    const prev = prevRects.current;
    const row = rowRef.current;
    prevRects.current = null;
    if (!prev || !row) return;
    row.querySelectorAll<HTMLElement>("[data-card]").forEach((el) => {
      const old = prev.get(el.dataset.key ?? "");
      if (old === undefined) return;
      const dx = old - el.getBoundingClientRect().left;
      if (!dx) return;
      el.style.transition = "none";
      el.style.transform = `translateX(${dx}px)`;
      // force a reflow so the browser registers the inverted transform before
      // the card is handed back to its transition
      void el.offsetWidth;
      el.style.transition = "";
      el.style.transform = "";
    });
  }, [previewKeys]);

  function snapshotRects() {
    const map = new Map<string, number>();
    rowRef.current
      ?.querySelectorAll<HTMLElement>("[data-card]")
      .forEach((el) => {
        map.set(el.dataset.key ?? "", el.getBoundingClientRect().left);
      });
    prevRects.current = map;
  }

  function onDragStart(e: React.DragEvent, card: CardData) {
    e.dataTransfer.effectAllowed = "move";
    // some browsers need data set for a drag to start at all
    e.dataTransfer.setData("text/plain", card.key);
    setDragKey(card.key);
  }
  function onDragOver(e: React.DragEvent, card: CardData) {
    if (dragKey === null || card.key === dragKey) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    if (card.key !== overKey) {
      snapshotRects();
      setOverKey(card.key);
    }
  }
  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    finishDrag(true);
  }
  function onDragEnd() {
    finishDrag(false);
  }
  function finishDrag(persist: boolean) {
    const finalKeys = previewKeys;
    setDragKey(null);
    setOverKey(null);
    if (!persist || finalKeys.join() === baseKeys.join()) return;
    save(
      {
        hide: ov.hide,
        replace: ov.replace,
        extra: ov.extra,
        order: finalKeys,
      },
      { remove: gov.remove, replace: gov.replace, extra: gov.extra },
    );
  }

  const closeMenu = useCallback(() => setMenu(null), []);

  // close the menu on the next click anywhere — window listeners are not
  // affected by the card's preventDefault, which is why it lives here
  useEffect(() => {
    if (!menu) return;
    const onDown = (e: MouseEvent) => {
      if ((e.target as HTMLElement).closest(".ctx-menu")) return;
      closeMenu();
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [menu, closeMenu]);

  // clicks outside a card finish the edit or dismiss the menu
  useEffect(() => {
    if (!editingKey) return;
    const onDown = (e: Event) => {
      const el = e.target as HTMLElement;
      // a click that lands on the card being edited shouldn't end the edit
      if (el.closest(".vcard.editing")) return;
      commit();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setEditingKey(null);
        setLocked(null);
      }
      if (e.key === "Enter" && editingKey) commit();
    };
    // contextmenu too: a right-click elsewhere also counts as "click away"
    window.addEventListener("mousedown", onDown);
    window.addEventListener("contextmenu", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("contextmenu", onDown);
      window.removeEventListener("keydown", onKey);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editingKey, draft, segment]);

  // Hook order must not depend on `segment` below: the row can be empty for a
  // moment while the stage switches songs, and a conditional hook would crash
  // the whole tree on that flip.
  const [hint, setHint] = useState<string | null>(null);
  useEffect(() => {
    if (!hint) return;
    const t = setTimeout(() => setHint(null), 2600);
    return () => clearTimeout(t);
  }, [hint]);

  // the row's own element can only catch right-clicks inside its (clipped) box,
  // but the spec asks for the *whole stage* — the lyric line above, the cards,
  // and the gap down to the transport all open the same menu. Listen at the
  // document and open it anywhere that isn't a card (a card keeps its own
  // delete-confirm menu) or an already-open menu.
  useEffect(() => {
    const onDocContext = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      // a right-click on a card or inside an already-open menu keeps its own
      // behaviour; the lyric edit box and nav controls keep theirs too
      if (t.closest("[data-card]") || t.closest(".ctx-menu")) return;
      if (t.closest(".lyr-edit") || t.closest("nav, header, .tabbar")) return;
      e.preventDefault();
      setMenu({ x: e.clientX, y: e.clientY, target: null });
    };
    document.addEventListener("contextmenu", onDocContext);
    return () => document.removeEventListener("contextmenu", onDocContext);
  }, []);

  if (!segment) return null;

  const cur = localSeg ?? segment;
  const ov = normOverride(cur?.vocab_override);
  const gov = normGrammar(cur?.grammar_extra);

  /** Write the merged override state back through the dataset PATCH. */
  function save(
    vocab: Segment["vocab_override"] | undefined,
    grammar: Segment["grammar_extra"] | undefined,
    label = "词条编辑",
  ) {
    // snapshot before writing: the undo stack replays `restore` verbatim
    if (song && segment) {
      pushUndo({
        song,
        label,
        segmentId: segment.id,
        restore: {
          vocab_override: segment.vocab_override ?? null,
          grammar_extra: segment.grammar_extra ?? null,
        },
      });
    }
    const next = onPatch?.({
      vocab_override: vocab,
      grammar_extra: grammar,
    });
    if (next) setLocalSeg(next);
  }

  function startEdit(card: CardData) {
    setLocked(cards);
    setEditingKey(card.key);
    setDraft(card.kind === "word" ? wordToEdit(card.w) : grammarToEdit(card.g));
  }

  function commit() {
    if (!editingKey || draft === null || !segment) {
      setEditingKey(null);
      setLocked(null);
      return;
    }
    const card = cards.find((c) => c.key === editingKey);
    setEditingKey(null);
    setLocked(null);
    if (!card) return;

    if (card.kind === "word") {
      const e = draft as VocabEdit;
      const w = editToWord(e);
      const next = {
        hide: [...ov.hide],
        replace: { ...ov.replace },
        extra: [...ov.extra],
        order: [...ov.order],
      };
      if (card.id >= EXTRA_BASE) {
        next.extra[card.id - EXTRA_BASE] = w;
      } else {
        next.replace[card.id] = w;
      }
      save(next, { remove: gov.remove, replace: gov.replace, extra: gov.extra });
    } else {
      const e = draft as GrammarEdit;
      const g: GrammarHit = {
        ...(card.kind === "grammar" ? card.g : {}),
        id: card.id,
        name: e.name,
        level: e.level,
        z: e.z,
        ex: e.ex,
        matched: "",
      };
      const next = {
        remove: gov.remove,
        replace: { ...gov.replace },
        extra: [...gov.extra],
      };
      if (card.id.startsWith("__extra_")) {
        next.extra[Number(card.id.slice(8))] = g;
      } else {
        next.replace[card.id] = { name: e.name, level: e.level, z: e.z, ex: e.ex };
      }
      save(
        {
          hide: ov.hide,
          replace: ov.replace,
          extra: ov.extra,
          // keep the row order — dropping it reset every grammar card to the
          // tail of the row after any edit
          order: ov.order,
        },
        next,
      );
    }
  }

  function removeCard(card: CardData) {
    if (card.kind === "word") {
      const next = {
        hide: [...ov.hide],
        replace: { ...ov.replace },
        extra: [...ov.extra],
        // drop the removed card's key so the row doesn't keep a stale slot
        order: ov.order.filter((o) => String(o) !== card.key && o !== card.id),
      };
      if (card.id >= EXTRA_BASE) {
        next.extra.splice(card.id - EXTRA_BASE, 1);
      } else {
        next.hide.push(card.id);
        delete next.replace[card.id];
      }
      save(next, { remove: gov.remove, replace: gov.replace, extra: gov.extra });
    } else {
      const next = {
        remove: [...gov.remove],
        replace: { ...gov.replace },
        extra: [...gov.extra],
      };
      if (card.id.startsWith("__extra_")) {
        next.extra.splice(Number(card.id.slice(8)), 1);
      } else {
        next.remove.push(card.id);
      }
      save(
        {
          hide: ov.hide,
          replace: ov.replace,
          extra: ov.extra,
          order: ov.order.filter((o) => String(o) !== card.key),
        },
        next,
      );
    }
    closeMenu();
  }

  function addCard() {
    const wordCount = cards.filter((c) => c.kind === "word").length;
    const grammarVisible = cards.some((c) => c.kind === "grammar");
    const room = budget - (grammarVisible ? 1 : 0);
    if (wordCount >= room) {
      closeMenu();
      setHint("卡片已满，先删除一张再新建");
      return;
    }
    const blank: WordTiming = {
      text: "",
      romaji: "",
      zh: "",
      content: true,
      start: 0,
      end: 0,
      score: 0,
    };
    // the new card keeps the rightmost slot; generated picks shift left
    const newKey = `wx${ov.extra.length}`;
    const order = [...cards.map((c) => c.key), newKey].slice(-budget);
    save(
      {
        hide: ov.hide,
        replace: ov.replace,
        extra: [...ov.extra, blank],
        order,
      },
      { remove: gov.remove, replace: gov.replace, extra: gov.extra },
    );
    closeMenu();
  }

  function onContext(e: React.MouseEvent, card: CardData | null) {
    e.preventDefault();
    e.stopPropagation();
    setMenu({ x: e.clientX, y: e.clientY, target: card });
  }

  return (
    <>
      <div
        ref={rowRef}
        className={`vocab${empty ? " empty" : ""}${hidden ? " collapsed" : ""}`}
        onContextMenu={(e) => {
          // only the padding between cards adds a new one; right-clicking a
          // card opens its own menu instead
          if ((e.target as HTMLElement).closest("[data-card]")) return;
          e.preventDefault();
          onContext(e, null);
        }}
        onDragOver={(e) => {
          if (dragKey === null) return;
          e.preventDefault();
          // work out the insertion slot from the cursor x, so a drag over the
          // gap between cards (or past the last one) still previews the move
          const els = Array.from(
            rowRef.current?.querySelectorAll<HTMLElement>("[data-card]") ?? [],
          ).filter((el) => el.dataset.key !== dragKey);
          // dragKey inserts before `target`; the sentinel keeps an end-of-row
          // drop previewable too (it is never a real key, so it appends)
          let target: string | null = "__END__";
          for (const el of els) {
            const r = el.getBoundingClientRect();
            if (e.clientX < r.left + r.width / 2) {
              target = el.dataset.key ?? "__END__";
              break;
            }
          }
          if (target && target !== overKey) {
            snapshotRects();
            setOverKey(target);
          }
        }}
        onDrop={onDrop}
      >
        {hidden ? (
          <button
            type="button"
            className="vocab-collapsed-bar"
            onContextMenu={(e) => {
              e.preventDefault();
              onContext(e, null);
            }}
            title="词条卡片已隐藏 · 右键显示"
          >
            词条卡片已隐藏 · 右键恢复
          </button>
        ) : (
          renderedCards.map((card, i) =>
          card.kind === "word" ? (
            <VocabCard
              key={card.key}
              w={card.w}
              i={i}
              cardKey={card.key}
              editing={editingKey === card.key}
              draft={draft as VocabEdit}
              onEdit={() => startEdit(card)}
              onChange={setDraft}
              onContext={(e) => onContext(e, card)}
              dragging={dragKey === card.key}
              dropTarget={dragKey !== null && overKey === card.key}
              onDragStart={(e) => onDragStart(e, card)}
              onDragOver={(e) => onDragOver(e, card)}
              onDragEnd={onDragEnd}
              romaji={displayRomaji(card.w, settings)}
            />
          ) : (
            <GrammarCard
              key={card.key}
              g={card.g}
              i={i}
              cardKey={card.key}
              editing={editingKey === card.key}
              draft={draft as GrammarEdit}
              onEdit={() => startEdit(card)}
              onChange={setDraft}
              onContext={(e) => onContext(e, card)}
              dragging={dragKey === card.key}
              dropTarget={dragKey !== null && overKey === card.key}
              onDragStart={(e) => onDragStart(e, card)}
              onDragOver={(e) => onDragOver(e, card)}
              onDragEnd={onDragEnd}
            />
          ),
          )
        )}
      </div>

      {hint && <div className="card-hint">{hint}</div>}

      {menu && (
        <div
          className="ctx-menu"
          style={{ left: menu.x, top: menu.y }}
          role="menu"
          onMouseDown={(e) => e.stopPropagation()}
        >
          {menu.target ? (
            <>
              <div className="ctx-hint">
                删除「
                {menu.target.kind === "word"
                  ? wordToEdit(menu.target.w).text
                  : menu.target.g.name}
                」？
              </div>
              <button
                className="ctx-item danger"
                onClick={() => removeCard(menu.target!)}
              >
                删除这张卡片
              </button>
            </>
          ) : (
            <>
              {!hidden && (
                <button className="ctx-item" onClick={addCard}>
                  新建词条卡片
                </button>
              )}
              <button
                className="ctx-item"
                onClick={() => {
                  closeMenu();
                  onToggleHidden?.();
                }}
              >
                {hidden ? "显示词条卡片" : "隐藏词条卡片"}
              </button>
              {onToggleTrans && (
                <button
                  className="ctx-item"
                  onClick={() => {
                    closeMenu();
                    onToggleTrans();
                  }}
                >
                  {transHidden ? "显示中文翻译" : "隐藏中文翻译"}
                </button>
              )}
              {/* the plan puts every display switch in one place, so the same
                  menu covers 注音 / 罗马音 / 下一句 */}
              {layers &&
                onToggleLayer &&
                (
                  [
                    ["furigana", "注音"],
                    ["romaji", "罗马音"],
                    ["next_line", "下一句"],
                  ] as const
                ).map(([key, label]) => (
                  <button
                    key={key}
                    className="ctx-item"
                    onClick={() => {
                      closeMenu();
                      onToggleLayer(key);
                    }}
                  >
                    {layers[key] ? `隐藏${label}` : `显示${label}`}
                  </button>
                ))}
            </>
          )}
          <button className="ctx-item dim" onClick={closeMenu}>
            取消
          </button>
        </div>
      )}
    </>
  );
}
