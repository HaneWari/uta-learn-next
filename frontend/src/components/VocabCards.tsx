import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useCallback } from "react";
import type { GrammarHit, Segment, WordTiming } from "../types";

/** How many vocabulary cards the current window can carry. */
function useCardBudget() {
  const [budget, setBudget] = useState(() => compute(window.innerWidth));

  useEffect(() => {
    const onResize = () => setBudget(compute(window.innerWidth));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  return budget;
}

function compute(width: number) {
  if (width < 900) return 2;
  if (width < 1300) return 3;
  return 4;
}

/** JLPT weight: the card row should teach upward, so N1 outranks N5 by a lot. */
const LEVEL_SCORE: Record<string, number> = {
  N1: 5,
  N2: 4,
  N3: 3,
  N4: 2,
  N5: 1,
};

function levelScore(level?: string) {
  return LEVEL_SCORE[(level ?? "").toUpperCase()] ?? 0;
}

/* ---------- editable card model ----------

 * The generated picks are only the starting point. Every card on the row can
 * be edited, hidden or added by hand; those choices live in
 * `segment.vocab_override` / `segment.grammar_extra` and are written back to
 * the dataset file, so the video export sees exactly what the stage shows.
 */

interface VocabEdit {
  text: string;
  kana: string;
  romaji: string;
  pos: string;
  zh: string;
  jlpt: string;
  /** the form actually sung — only kept when it differs from `text` */
  used: string;
}

interface GrammarEdit {
  name: string;
  level: string;
  z: string;
  ex: string;
}

interface VocabCardData {
  key: string;
  kind: "word";
  /** stable identity within the segment: word index, or extra index + 10000 */
  id: number;
  w: WordTiming;
}

interface GrammarCardData {
  key: string;
  kind: "grammar";
  /** grammar id from the source, or `__extra_${i}` */
  id: string;
  g: GrammarHit;
}

type CardData = VocabCardData | GrammarCardData;

const EXTRA_BASE = 10000;

/** Move `dragKey` to where `overKey` sits in the visible row. */
function reorderPreview(keys: string[], dragKey: string, overKey: string) {
  const rest = keys.filter((k) => k !== dragKey);
  const at = rest.indexOf(overKey);
  if (at < 0) return rest.concat(dragKey);
  rest.splice(at, 0, dragKey);
  return rest;
}

function normOverride(ov?: Segment["vocab_override"]) {
  return {
    hide: ov?.hide ?? [],
    replace: ov?.replace ?? {},
    extra: ov?.extra ?? [],
    order: ov?.order ?? [],
  };
}

function normGrammar(ov?: Segment["grammar_extra"]) {
  return {
    remove: ov?.remove ?? [],
    replace: ov?.replace ?? {},
    extra: ov?.extra ?? [],
  };
}

function wordToEdit(w: WordTiming): VocabEdit {
  const isLemma = !!w.lemma && w.lemma !== w.text;
  const head = isLemma ? w.lemma! : w.text;
  const raw = isLemma ? w.lemma_kana ?? w.kana : w.kana;
  return {
    text: head,
    kana: raw && raw !== head ? raw : "",
    romaji: w.romaji ?? "",
    pos: w.pos ?? "",
    zh: w.zh ?? "",
    jlpt: w.jlpt ?? "",
    used: isLemma ? w.text : "",
  };
}

function editToWord(e: VocabEdit): WordTiming {
  const used = e.used.trim();
  return {
    text: used || e.text,
    lemma: used && used !== e.text ? e.text : e.text,
    kana: e.kana || undefined,
    lemma_kana: used && used !== e.text ? e.kana || undefined : undefined,
    romaji: e.romaji,
    pos: e.pos || undefined,
    zh: e.zh,
    jlpt: e.jlpt || undefined,
    content: true,
    start: 0,
    end: 0,
    score: 0,
  };
}

function grammarToEdit(g: GrammarHit): GrammarEdit {
  return { name: g.name, level: g.level ?? "", z: g.z, ex: g.ex ?? "" };
}

/** Merge generated picks + overrides into the final visible cards. */
function computeCards(
  segment: Segment | null,
  budget: number,
): CardData[] {
  if (!segment) return [];
  const ov = normOverride(segment.vocab_override);
  const gov = normGrammar(segment.grammar_extra);

  // ask for one extra word so hiding a card can be backfilled, like before
  const generated = pickWords(segment, budget + 1);
  const shown = generated.filter(
    (w) => !ov.hide.includes(segment.words.indexOf(w)),
  );
  const genCards: VocabCardData[] = shown.map((w) => {
    const idx = segment.words.indexOf(w);
    return {
      key: `w${idx}`,
      kind: "word",
      id: idx,
      w: { ...w, ...ov.replace[idx] },
    };
  });
  const extraCards: VocabCardData[] = ov.extra.map((w, i) => ({
    key: `wx${i}`,
    kind: "word",
    id: EXTRA_BASE + i,
    w,
  }));

  const grammar: GrammarCardData[] = [
    ...(segment.grammar ?? [])
      .filter((g) => !gov.remove.includes(g.id))
      .map(
        (g): GrammarCardData => ({
          key: `g-${g.id}`,
          kind: "grammar",
          id: g.id,
          g: { ...g, ...gov.replace[g.id] },
        }),
      )
      .slice(0, 1),
    ...gov.extra.map(
      (g, i): GrammarCardData => ({
        key: `gx${i}`,
        kind: "grammar",
        id: `__extra_${i}`,
        g,
      }),
    ),
  ];

  // One ordering for the whole row. Newer saves store every card's `key`
  // (`w${index}` / `wx${i}` / `g-${id}` / `gx${i}`); older saves only listed
  // generated word indexes, which are normalised to `w${index}` keys first.
  const all: CardData[] = [...genCards, ...extraCards, ...grammar];
  const byKey = new Map(all.map((c) => [c.key, c] as const));
  const defaultKeys = all.map((c) => c.key);
  const storedKeys = ov.order.map((o) =>
    typeof o === "number" ? `w${o}` : o,
  );
  const orderedKeys = storedKeys.length
    ? [
        ...storedKeys.filter((k) => byKey.has(k)),
        ...defaultKeys.filter((k) => !storedKeys.includes(k)),
      ]
    : defaultKeys;

  // Fit the ordered row into the budget. A grammar card always keeps one
  // reserved slot (it is the line's pattern, not just another word), so word
  // cards fill `budget - gSlots` and never push the grammar card out — while
  // still letting the user drag it anywhere in the row.
  const ordered = orderedKeys
    .map((k) => byKey.get(k))
    .filter((c): c is CardData => !!c);
  const gSlots = Math.min(1, ordered.filter((c) => c.kind === "grammar").length);
  const wordBudget = budget - gSlots;
  let wTaken = 0;
  let gTaken = 0;
  return ordered.filter((c) =>
    c.kind === "word" ? wTaken++ < wordBudget : gTaken++ < gSlots,
  );
}

/**
 * Choose which words get a card, and in what order.
 *
 * Selection prefers higher JLPT levels (that is what "优先高阶" means here), but
 * the cards are still shown in the order the words appear in the line: reordering
 * the row by difficulty would break the reader's eye movement across the lyric.
 */
function pickWords(segment: Segment | null, limit: number): WordTiming[] {
  if (!segment) return [];
  const scored = segment.words
    .filter((w) => w.content !== false && w.zh)
    .map((w, index) => {
      // level dominates: 3 points per JLPT step means an N2 noun always beats
      // an N5 noun, which is the behaviour the "prefer harder words" ask wants
      let score = levelScore(w.jlpt) * 3;
      if (w.pos1 === "名詞" || w.pos1 === "動詞" || w.pos1 === "形容詞") score += 2;
      score += Math.min(3, w.text.length);
      if (w.kana) score += 1;
      return { w, score, index };
    })
    .sort((a, b) => b.score - a.score || a.index - b.index);

  // never show the same surface twice on one line
  const seen = new Set<string>();
  const chosen: { w: WordTiming; index: number }[] = [];
  for (const { w, index } of scored) {
    if (seen.has(w.text)) continue;
    seen.add(w.text);
    chosen.push({ w, index });
    if (chosen.length === limit) break;
  }

  // back to reading order for display
  chosen.sort((a, b) => a.index - b.index);
  return chosen.map((c) => c.w);
}

function VocabCard({
  w,
  i,
  cardKey,
  editing,
  draft,
  onEdit,
  onChange,
  onContext,
  dragging,
  dropTarget,
  onDragStart,
  onDragOver,
  onDragEnd,
}: {
  w: WordTiming;
  i: number;
  cardKey: string;
  editing: boolean;
  draft: VocabEdit;
  onEdit: () => void;
  onChange: (v: VocabEdit) => void;
  onContext: (e: React.MouseEvent) => void;
  dragging: boolean;
  dropTarget: boolean;
  onDragStart: (e: React.DragEvent) => void;
  onDragOver: (e: React.DragEvent) => void;
  onDragEnd: () => void;
}) {
  // Headline the dictionary form when the line uses an inflected one, so the
  // card matches what a learner would look up (逃げる, not 逃げ).
  const isLemma = !!w.lemma && w.lemma !== w.text;
  const head = isLemma ? w.lemma! : w.text;
  const raw = isLemma ? w.lemma_kana ?? w.kana : w.kana;
  // a word already written in kana must not repeat its reading beside itself
  const kana = raw && raw !== head ? raw : undefined;

  if (editing) {
    const edit = draft;
    const field =
      (key: keyof VocabEdit, ph: string, cls = "vedit") => (
        <input
          className={cls}
          value={edit[key]}
          placeholder={ph}
          onChange={(e) => onChange({ ...edit, [key]: e.target.value })}
        />
      );
    return (
      <article className="vcard editing">
        <header className="vhead">
          {field("text", "词条")}
          {field("kana", "读音")}
          {field("jlpt", "JLPT", "vedit tag")}
        </header>
        <div className="vbody">
          {field("pos", "词性", "vedit pos")}
          {field("zh", "中文释义")}
        </div>
        <div className="vmeta">
          {field("romaji", "罗马音", "vedit roma")}
          {field("used", "歌中形", "vedit used")}
        </div>
      </article>
    );
  }

  return (
    <article
      className={
        "vcard editable" +
        (dragging ? " dragging" : "") +
        (dropTarget ? " drop-target" : "")
      }
      style={{
        animationDelay: `${i * 70}ms`,
        transition: "transform 0.18s var(--ease-out)",
      }}
      onDoubleClick={onEdit}
      onContextMenu={onContext}
      title="双击编辑"
      data-card
      data-key={cardKey}
      draggable={!editing}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDragEnd={onDragEnd}
    >
      <header className="vhead">
        <span className="vw">{head}</span>
        {kana && <span className="vkana">{kana}</span>}
        {w.jlpt && <span className="vtag">{w.jlpt}</span>}
      </header>
      <div className="vbody">
        {w.pos && <span className="vpos">{w.pos}</span>}
        <span className="vzh">{w.zh}</span>
      </div>
      <div className="vmeta">
        {w.romaji && <span className="vroma">{w.romaji}</span>}
        {isLemma && <span className="vused">歌中 {w.text}</span>}
      </div>
    </article>
  );
}

function GrammarCard({
  g,
  i,
  cardKey,
  editing,
  draft,
  onEdit,
  onChange,
  onContext,
  dragging,
  dropTarget,
  onDragStart,
  onDragOver,
  onDragEnd,
}: {
  g: GrammarHit;
  i: number;
  cardKey: string;
  editing: boolean;
  draft: GrammarEdit;
  onEdit: () => void;
  onChange: (v: GrammarEdit) => void;
  onContext: (e: React.MouseEvent) => void;
  dragging: boolean;
  dropTarget: boolean;
  onDragStart: (e: React.DragEvent) => void;
  onDragOver: (e: React.DragEvent) => void;
  onDragEnd: () => void;
}) {
  if (editing) {
    const edit = draft;
    const field =
      (key: keyof GrammarEdit, ph: string, cls = "vedit") => (
        <input
          className={cls}
          value={edit[key]}
          placeholder={ph}
          onChange={(e) => onChange({ ...edit, [key]: e.target.value })}
        />
      );
    return (
      <article className="vcard gcard editing">
        <header className="vhead">
          {field("name", "句型")}
          {field("level", "等级", "vedit tag")}
        </header>
        <div className="vbody">
          <span className="vpos">句型</span>
          {field("z", "中文释义")}
        </div>
        <div className="vmeta">
          {field("ex", "例句", "vedit used")}
        </div>
      </article>
    );
  }
  return (
    <article
      className={
        "vcard gcard editable" +
        (dragging ? " dragging" : "") +
        (dropTarget ? " drop-target" : "")
      }
      style={{
        animationDelay: `${i * 70}ms`,
        transition: "transform 0.18s var(--ease-out)",
      }}
      onDoubleClick={onEdit}
      onContextMenu={onContext}
      title="双击编辑"
      data-card
      data-key={cardKey}
      draggable={!editing}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDragEnd={onDragEnd}
    >
      <header className="vhead">
        <span className="vw">{g.name}</span>
        {g.level && <span className="vtag gtag">{g.level}</span>}
      </header>
      <div className="vbody">
        <span className="vpos">句型</span>
        <span className="vzh">{g.z}</span>
      </div>
      <div className="vmeta">
        <span className="vused">{g.ex}</span>
      </div>
    </article>
  );
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
}: {
  segment: Segment | null;
  onPatch?: (patch: {
    vocab_override?: Segment["vocab_override"];
    grammar_extra?: Segment["grammar_extra"];
  }) => Segment | undefined;
}) {
  const budget = useCardBudget();
  const [menu, setMenu] = useState<MenuState | null>(null);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [draft, setDraft] = useState<VocabEdit | GrammarEdit | null>(null);
  // freeze the row while a card is being edited so a field change that
  // resizes the card can't bounce the input under the cursor
  const [locked, setLocked] = useState<CardData[] | null>(null);
  const [localSeg, setLocalSeg] = useState<Segment | null>(null);
  const eff = localSeg ?? segment;
  const live = computeCards(eff, budget);
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

  if (!segment) return null;

  const cur = localSeg ?? segment;
  const ov = normOverride(cur?.vocab_override);
  const gov = normGrammar(cur?.grammar_extra);

  /** Write the merged override state back through the dataset PATCH. */
  function save(
    vocab: Segment["vocab_override"] | undefined,
    grammar: Segment["grammar_extra"] | undefined,
  ) {
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
        { hide: ov.hide, replace: ov.replace, extra: ov.extra },
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

  const [hint, setHint] = useState<string | null>(null);
  useEffect(() => {
    if (!hint) return;
    const t = setTimeout(() => setHint(null), 2600);
    return () => clearTimeout(t);
  }, [hint]);

  function onContext(e: React.MouseEvent, card: CardData | null) {
    e.preventDefault();
    e.stopPropagation();
    setMenu({ x: e.clientX, y: e.clientY, target: card });
  }

  return (
    <>
      <div
        ref={rowRef}
        className={`vocab${empty ? " empty" : ""}`}
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
        {renderedCards.map((card, i) =>
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
            <button className="ctx-item" onClick={addCard}>
              新建空白卡片
            </button>
          )}
          <button className="ctx-item dim" onClick={closeMenu}>
            取消
          </button>
        </div>
      )}
    </>
  );
}
