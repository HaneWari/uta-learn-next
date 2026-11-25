import type { GrammarHit, WordTiming } from "../types";
import type { GrammarEdit, VocabEdit } from "./cardEdit";

/* ---------- editable card model ----------

 * The generated picks are only the starting point. Every card on the row can
 * be edited, hidden or added by hand; those choices live in
 * `segment.vocab_override` / `segment.grammar_extra` and are written back to
 * the dataset file, so the video export sees exactly what the stage shows.
 */

export function VocabCard({
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
  romaji,
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
  /** settings-aware romaji: particles + long-vowel style already applied */
  romaji: string;
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
        {romaji && <span className="vroma">{romaji}</span>}
        {isLemma && <span className="vused">歌中 {w.text}</span>}
      </div>
    </article>
  );
}

export function GrammarCard({
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