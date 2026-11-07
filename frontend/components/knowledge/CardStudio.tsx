'use client';
import { useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, Download, ImagePlus, Layers, Save } from 'lucide-react';
import { exportUrl, yuan, type Card, type CardDraft, type ExportVersion, type Health, type Work } from '@/lib/knowledge';

type Action = (path: string, body: object, method?: string) => Promise<void>;
function draftOf(card: Card): CardDraft {
  return { title: card.title, body: card.body, narration: card.narration, prompt: card.prompt, template: card.template };
}

function CardEditor({ card, onSave, onDirty, locked }: { card: Card; onSave: (draft: CardDraft) => Promise<void>; onDirty: (dirty: boolean) => void; locked: boolean }) {
  const [draft, setDraft] = useState(() => draftOf(card));
  const [saved, setSaved] = useState(() => JSON.stringify(draftOf(card)));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const signature = JSON.stringify(draft);
  const snapshot = useRef(draft);
  const saveFn = useRef(onSave);
  const queue = useRef(Promise.resolve());
  const lastSaved = useRef(saved);
  useEffect(() => { snapshot.current = draft; saveFn.current = onSave; }, [draft, onSave]);
  const valid = [draft.title, draft.body, draft.narration, draft.prompt].every(v => v.trim());
  function save(value: CardDraft) {
    const operation = queue.current.catch(() => {}).then(async () => {
      const sig = JSON.stringify(value);
      if (sig === lastSaved.current) return;
      setSaving(true); setError('');
      try { await saveFn.current(value); lastSaved.current = sig; setSaved(sig); }
      catch (e) { setError(e instanceof Error ? e.message : '保存未完成'); throw e; }
      finally { setSaving(false); }
    });
    queue.current = operation;
    return operation;
  }
  useEffect(() => {
    if (!valid || locked || signature === saved) return;
    const value = JSON.parse(signature) as CardDraft;
    const timer = setTimeout(() => { void save(value).catch(() => {}); }, 1000);
    return () => clearTimeout(timer);
  }, [signature, saved, valid, locked]);
  useEffect(() => { onDirty(signature !== saved || saving); }, [signature, saved, saving, onDirty]);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (JSON.stringify(snapshot.current) !== lastSaved.current) e.preventDefault(); };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, []);
  const set = (field: keyof CardDraft, value: string) => setDraft(d => ({ ...d, [field]: value }));
  return <div className="kd-card-editor"><div className="kd-panel-heading"><h3>编辑这张卡片</h3><span className="kd-save-status" role="status">{saving ? '正在保存…' : signature === saved ? '已保存' : '等待保存'}</span></div>
    <fieldset disabled={locked}>
      <label className="kd-label">卡片标题<input value={draft.title} maxLength={60} onChange={e => set('title', e.target.value)} /></label>
      <label className="kd-label">卡片正文<textarea value={draft.body} maxLength={1000} rows={4} onChange={e => set('body', e.target.value)} /></label>
      <label className="kd-label">旁白草稿<textarea value={draft.narration} maxLength={1000} rows={2} onChange={e => set('narration', e.target.value)} /></label>
      <p className="kd-muted">旁白先随卡片保存，下一阶段用于配音。</p>
      <label className="kd-label">插图描述<textarea value={draft.prompt} maxLength={1200} rows={2} onChange={e => set('prompt', e.target.value)} /></label>
      <p className="kd-muted">改字会保留插图；修改插图描述后，原插图归入历史，需重新生图。</p>
      <label className="kd-label">排版模板<select value={draft.template} onChange={e => set('template', e.target.value)}><option value="paper">纸上笔记 · 浅色</option><option value="ink">深绿手札 · 深色</option></select></label>
      <button className="kd-button kd-secondary" disabled={!valid || saving || signature === saved} onClick={() => void save(snapshot.current).catch(() => {})}><Save size={15} />保存卡片</button>
    </fieldset>
    {error ? <p className="kd-error" role="alert">{error}</p> : null}
  </div>;
}

export default function CardStudio({ work, health, onAction, onDirty, materialDirty }: { work: Work; health: Health | null; onAction: Action; onDirty: (dirty: boolean) => void; materialDirty: boolean }) {
  const [selectedId, setSelectedId] = useState('');
  const [dirty, setDirty] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const cards = work.cards || [];
  const selected = cards.find(c => c.id === selectedId) || cards[0];
  const running = work.jobs.some(j => ['pending', 'running'].includes(j.status));
  const disabled = pending || running || materialDirty;
  useEffect(() => { onDirty(dirty || pending); }, [dirty, pending, onDirty]);
  async function act(path: string, body: object, method?: string) {
    setPending(true); setError('');
    try { await onAction(path, body, method); }
    catch (e) { setError(e instanceof Error ? e.message : '操作未完成'); throw e; }
    finally { setPending(false); }
  }
  function perform(path: string, body: object, method?: string) { void act(path, body, method).catch(() => {}); }
  function move(index: number, delta: number) {
    const ids = cards.map(c => c.id);
    [ids[index], ids[index + delta]] = [ids[index + delta], ids[index]];
    perform('/cards/order', { card_ids: ids });
  }
  const price = health?.image_price_micro ?? 40000;
  const imageEnabled = health?.image_configured && health?.image_enabled;
  return <section className="kd-panel kd-card-studio" aria-labelledby="cards-title">
    <div className="kd-panel-heading"><div><p className="kd-eyebrow">02 — 04 / 从观点到图解</p><h2 id="cards-title">编排你的知识卡片</h2></div><Layers size={22} /></div>
    <p className="kd-muted">先把确认过的知识点放入卡片，再调整标题、正文和插图描述。初稿沿用知识点原文，不会额外调用文本模型。</p>
    {cards.length && !work.cards_current ? <p className="kd-error" role="status">原文或知识点已变化。请完成核对，再重新编排；旧图片版本仍可下载。</p> : null}
    <div className="kd-actions"><button className="kd-button kd-secondary" disabled={disabled || dirty || work.stage !== 'reviewed'} onClick={() => {
      if (cards.length && !window.confirm('重新编排将生成新卡片草稿。已有图片版本与旧卡片历史会保留，当前编辑请先保存。')) return;
      perform('/cards/draft', {});
    }}>{cards.length ? '重新编排卡片' : '用已确认知识点编排卡片'}</button></div>
    {!cards.length ? <p className="kd-muted">确认全部知识点后继续；每套需要3–6个知识点。</p> : <div className="kd-cards-layout"><div className="kd-card-picker">{cards.map((card, i) => <article className={`kd-card-pick ${selected?.id === card.id ? 'kd-card-selected' : ''}`} key={card.id}>
      <button className="kd-card-pick-main" disabled={dirty || pending} onClick={() => setSelectedId(card.id)}><span className="kd-eyebrow">{String(i + 1).padStart(2, '0')} / {card.kind === 'supplement' ? '补充说明' : '原文提炼'}</span><strong>{card.title}</strong><small>{card.illustration_id ? '插图已保存' : '等待生成插图'}</small></button>
      <div className="kd-card-order"><button aria-label={`上移第${i + 1}张`} disabled={disabled || dirty || !work.cards_current || i === 0} onClick={() => move(i, -1)}><ArrowUp size={14} /></button><button aria-label={`下移第${i + 1}张`} disabled={disabled || dirty || !work.cards_current || i === cards.length - 1} onClick={() => move(i, 1)}><ArrowDown size={14} /></button></div>
    </article>)}</div>{selected ? <div><CardEditor key={selected.id} card={selected} onSave={draft => act(`/cards/${selected.id}`, draft, 'PATCH')} onDirty={setDirty} locked={!work.cards_current || materialDirty || running} />
      <div className="kd-illustration">{selected.illustration_id ? <img src={`/api/knowledge/works/${work.id}/illustrations/${selected.illustration_id}`} width={280} height={280} alt={`卡片插图：${selected.title}`} /> : <p className="kd-muted">插图尚未生成。此时导出会带有“插图尚未生成”标识。</p>}
        <button className="kd-button kd-secondary" disabled={disabled || dirty || !work.cards_current || !imageEnabled} onClick={() => {
          if (!window.confirm(`将此卡片的插图描述发送到云端，生成1张插图，费用上限¥${yuan(price)}，不自动重试。继续？`)) return;
          perform(`/cards/${selected.id}/illustration`, { operation_id: crypto.randomUUID(), max_cost_micro: price });
        }}><ImagePlus size={16} />{selected.illustration_id ? '重新生成插图' : '生成这张插图'} · ¥{yuan(price)}</button>
        {!imageEnabled ? <p className="kd-muted">真实生图尚未启用，可先编辑并导出排版草稿。</p> : null}
      </div></div> : null}</div>}
    <div className="kd-actions"><button className="kd-button kd-primary" disabled={disabled || dirty || !work.cards_current} onClick={() => perform('/exports', { operation_id: crypto.randomUUID() })}><Download size={16} />{running ? '正在处理…' : '生成PNG与编号ZIP'}</button></div>
    {error ? <p className="kd-error" role="alert">{error}</p> : null}
    {work.jobs.filter(j => j.kind === 'illustration' && ['failed', 'interrupted'].includes(j.status)).map(j => <p className="kd-muted" key={j.id}>{j.error?.message}<button className="kd-text-button" disabled={disabled || dirty || !imageEnabled} onClick={() => perform(`/jobs/${j.id}/resume`, {})}>核对原远程任务</button></p>)}
    {(work.exports || []).length ? (() => {
      const versions = [...work.exports].reverse();
      const latest = versions[0];
      const older = versions.slice(1);
      const label = (version: ExportVersion, index: number) => `第${work.exports.length - index}版 · ${version.cards.length}张 · ${version.fingerprint === work.deck_fingerprint && work.cards_current ? '与当前卡片一致' : '旧版本，当前内容需重新导出'}${version.cards.some(c => !c.illustration_id) ? ' · 含待插图草稿' : ''}`;
      return <div className="kd-export-history"><h3>保存的图片版本</h3>
        <article>
          <div className="kd-panel-heading"><span>{label(latest, 0)}</span><a className="kd-button kd-secondary" href={exportUrl(work.id, latest.id, 'all.zip')} download>下载编号ZIP</a></div>
          <div className="kd-export-thumbnails">{latest.cards.map((card, n) => <a key={card.id} href={exportUrl(work.id, latest.id, `${String(n + 1).padStart(2, '0')}.png`)} download><img src={exportUrl(work.id, latest.id, `${String(n + 1).padStart(2, '0')}.png`)} alt={`第${n + 1}张：${card.title}`} width={180} height={320} /><span>下载 {String(n + 1).padStart(2, '0')}.png</span></a>)}</div>
        </article>
        {older.length ? <details className="kd-export-older"><summary>更早的 {older.length} 个版本（仍然可下载，不占版面）</summary>
          {older.map((version, i) => <div className="kd-export-older-row" key={version.id}><span>{label(version, i + 1)}</span><span className="kd-export-older-links">{version.cards.map((card, n) => <a key={card.id} href={exportUrl(work.id, version.id, `${String(n + 1).padStart(2, '0')}.png`)} download>{String(n + 1).padStart(2, '0')}.png</a>)}<a className="kd-button kd-secondary" href={exportUrl(work.id, version.id, 'all.zip')} download>ZIP</a></span></div>)}
        </details> : null}
      </div>;
    })() : null}
  </section>;
}
