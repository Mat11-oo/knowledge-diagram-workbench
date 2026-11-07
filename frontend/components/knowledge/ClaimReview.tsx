'use client';
import { useState } from 'react';
import { BookOpen, Check, Combine, Pencil, Quote, Trash2 } from 'lucide-react';
import { referenceValid, sourceParts, type Claim, type Work } from '@/lib/knowledge';

export default function ClaimReview({ work, onAction, locked = false }: { work: Work; locked?: boolean; onAction: (path: string, body: object, method?: string) => Promise<void> }) {
  const [selected, setSelected] = useState<string[]>([]);
  const [focused, setFocused] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [text, setText] = useState('');
  const [mergeText, setMergeText] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const claims = work.claims.filter(c => c.active);
  const active = claims.find(c => c.id === focused) || claims[0];
  const source = work.sources.at(-1)!;
  const selectedActive = selected.filter(id => claims.some(c => c.id === id));

  async function act(path: string, body: object, method?: string) {
    setPending(true); setError('');
    try { await onAction(path, body, method); setEditing(null); }
    catch (error) { setError(error instanceof Error ? error.message : '操作未完成'); }
    finally { setPending(false); }
  }

  function valid(claim: Claim) { return claim.references.every(ref => referenceValid(source, ref)); }

  return <section className="kd-panel" aria-labelledby="review-title"><div className="kd-panel-heading"><div><span className="kd-eyebrow">02 / 对照与核对</span><h2 id="review-title">让每个观点有据可查</h2></div><span className="kd-count">{claims.filter(c => c.confirmed).length} / {claims.length} 已核对</span></div>
    <p className="kd-muted">引用能定位原文，不代表事实一定正确。请核对含义后逐条确认。</p>
    {claims.length === 0 ? <div className="kd-empty"><BookOpen size={38} strokeWidth={1} /><h3>知识点会出现在这里</h3><p>保存正文并提取后，点击任意观点查看对应原文。<br />补充例子与类比会单独标记。</p></div> : <>
      <div className="kd-review-columns"><div className="kd-claim-list">{claims.map((claim, index) => <article key={claim.id} className={`kd-claim ${active?.id === claim.id ? 'kd-claim-active' : ''}`}>
        <div className="kd-claim-meta"><label className="kd-select"><input type="checkbox" checked={selectedActive.includes(claim.id)} aria-label={`选择知识点${index + 1}`} onChange={e => setSelected(e.target.checked ? [...selectedActive, claim.id] : selectedActive.filter(id => id !== claim.id))} /><span>{String(index + 1).padStart(2, '0')}</span></label><span className={claim.kind === 'supplement' ? 'kd-badge kd-supplement' : 'kd-badge'}>{claim.kind === 'supplement' ? '补充说明' : '原文提炼'}</span><span className="kd-muted">{claim.confirmed ? '已确认' : '待核对'}</span></div>
        {editing === claim.id ? <div><label className="kd-label">编辑知识点<textarea value={text} maxLength={1000} onChange={e => setText(e.target.value)} rows={3} /></label><button className="kd-text-button" disabled={locked || pending || !text.trim()} onClick={() => void act(`/claims/${claim.id}`, { text }, 'PATCH')}>保存并重新核对</button></div> : <button className="kd-claim-text" onClick={() => setFocused(claim.id)}>{claim.text}</button>}
        {!valid(claim) ? <p className="kd-error-text">原文已变更，请重新提取后核对。</p> : null}
        <div className="kd-claim-tools"><button onClick={() => { setFocused(claim.id); }}><Quote size={13} />看原文</button><button disabled={locked || pending} onClick={() => { setEditing(claim.id); setText(claim.text); }}><Pencil size={13} />修改</button><button disabled={locked || pending} onClick={() => { if (window.confirm('移除这个知识点？原文与历史版本会保留。')) void act(`/claims/${claim.id}/remove`, {}); }} aria-label={`移除知识点${index + 1}`}><Trash2 size={13} /></button><button disabled={locked || pending || claim.confirmed || !valid(claim)} onClick={() => void act('/confirm', { claim_ids: [claim.id] })}><Check size={13} />{claim.confirmed ? '已确认' : '确认'}</button></div>
      </article>)}</div><aside className="kd-source-panel"><span className="kd-eyebrow">原文依据</span><h3>{source.title}</h3>{active?.references.map((ref, index) => {
        const revision = work.sources.find(s => s.revision === ref.source_revision);
        const parts = revision ? sourceParts(revision.text, ref) : null;
        return <div key={index}><p className="kd-muted">原文第{ref.source_revision}版{ref.source_revision !== source.revision ? ' · 已更新，需重新核对' : ''}</p><blockquote>{parts ? <>{parts.before.slice(-80)}<mark>{parts.quote}</mark>{parts.after.slice(0, 80)}</> : ref.quote}</blockquote></div>;
      })}{source.url ? <a href={source.url} target="_blank" rel="noreferrer">打开来源 ↗</a> : null}</aside></div>
      {selectedActive.length >= 2 ? <div className="kd-merge"><label className="kd-label">合并后的知识点<textarea value={mergeText} maxLength={1000} onChange={e => setMergeText(e.target.value)} rows={2} /></label><button className="kd-button kd-secondary" disabled={locked || pending || !mergeText.trim()} onClick={() => void act('/merge', { claim_ids: selectedActive, text: mergeText })}><Combine size={15} />合并选中的{selectedActive.length}条，保留全部引用</button></div> : null}
      {work.stage === 'reviewed' ? <p className="kd-success"><Check size={16} />本组知识点已核对并保存。可在下方编排卡片。</p> : null}
    </>}
    {error ? <p className="kd-error" role="alert">{error}</p> : null}
  </section>;
}
