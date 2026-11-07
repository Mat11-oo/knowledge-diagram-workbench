'use client';
import { useEffect, useRef, useState } from 'react';
import { ArrowRight, Check, Loader2, Save } from 'lucide-react';
import type { Material } from '@/lib/knowledge';

export default function MaterialEditor({ initial, onSave, onExtract, onDirty, configured, busy, blocked = false }: {
  initial: Material; onSave: (material: Material) => Promise<void>;
  onExtract: () => Promise<void>; configured: boolean; busy: boolean; blocked?: boolean;
  onDirty: (dirty: boolean) => void;
}) {
  const [draft, setDraft] = useState(initial);
  const [status, setStatus] = useState('已载入');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const lastSaved = useRef(JSON.stringify(initial));
  const queue = useRef(Promise.resolve());
  const current = useRef(draft);
  const saveFn = useRef(onSave);
  useEffect(() => { current.current = draft; saveFn.current = onSave; }, [draft, onSave]);
  const signature = JSON.stringify(draft);
  const valid = draft.title.trim() && draft.text.trim() && Array.from(draft.text).length <= 6000;

  function save(material: Material): Promise<void> {
    const signature = JSON.stringify(material);
    const operation = queue.current.catch(() => {}).then(async () => {
      if (signature === lastSaved.current) return;
      setSaving(true); setStatus('正在保存'); setError('');
      try {
        await saveFn.current(material);
        lastSaved.current = signature;
        setStatus(JSON.stringify(current.current) === signature ? '已自动保存' : '等待保存');
      } catch (error) {
        setStatus('尚未保存'); setError(error instanceof Error ? error.message : '保存失败');
        throw error;
      } finally { setSaving(false); }
    });
    queue.current = operation;
    return operation;
  }

  useEffect(() => {
    if (!valid || signature === lastSaved.current) return;
    const snapshot = JSON.parse(signature) as Material;
    const timer = setTimeout(() => { void save(snapshot).catch(() => {}); }, 1000);
    return () => clearTimeout(timer);
  }, [signature, valid]);

  useEffect(() => { onDirty(signature !== lastSaved.current || saving); }, [signature, saving, onDirty]);

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (JSON.stringify(current.current) !== lastSaved.current) { event.preventDefault(); }
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, []);

  async function extract() {
    try { await save(current.current); await onExtract(); }
    catch (error) { setError(error instanceof Error ? error.message : '提取未完成'); }
  }

  return <section className="kd-panel" aria-labelledby="material-title">
    <div className="kd-panel-heading"><div><span className="kd-eyebrow">01 / 原始材料</span><h2 id="material-title">先把内容放进来</h2></div><span className="kd-save-status" role="status">{saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />} {status}</span></div>
    <p className="kd-muted">粘贴公开或已脱敏的正文。来源只用于标注，不会自动抓取链接。</p>
    <fieldset className="kd-material-fields" disabled={blocked}><label className="kd-label">来源标题<input value={draft.title} maxLength={200} onChange={e => setDraft({ ...draft, title: e.target.value })} placeholder="例如：理解一个概念的笔记" /></label>
    <div className="kd-input-row"><label className="kd-label">来源链接（可选）<input type="url" value={draft.url} maxLength={2000} onChange={e => setDraft({ ...draft, url: e.target.value })} placeholder="https://" /></label><label className="kd-label">写给谁看<input value={draft.audience} maxLength={200} onChange={e => setDraft({ ...draft, audience: e.target.value })} /></label></div>
    <label className="kd-label">正文<textarea value={draft.text} onChange={e => setDraft({ ...draft, text: e.target.value })} placeholder="在这里粘贴知识材料。提取完成后，每个知识点都可以对照这份原文核对。" rows={12} /></label>
    <div className="kd-text-meta"><span>修改原文后，相关知识点需要重新核对。</span><span className={Array.from(draft.text).length > 6000 ? 'kd-error-text' : ''}>{Array.from(draft.text).length} / 6000字</span></div>
    </fieldset>
    {error ? <p role="alert" className="kd-error">{error}</p> : null}
    <div className="kd-actions"><button className="kd-button kd-secondary" disabled={!valid || saving || blocked} onClick={() => void save(current.current).catch(() => {})}><Save size={16} />保存材料</button><button className="kd-button kd-primary" disabled={!valid || busy || saving || blocked} onClick={() => void extract()}>{busy ? <Loader2 size={16} className="animate-spin" /> : <ArrowRight size={16} />}{busy ? '任务进行中' : '提取知识点'}</button></div>
    {!configured ? <p className="kd-muted kd-footnote">云端提取尚未启用。你可以先保存材料，配置完成后再继续；当前不会产生模型费用。</p> : <p className="kd-muted kd-footnote">提取会将正文发送至已启用的云端模型，并计入本套作品的1元预算。</p>}
  </section>;
}
