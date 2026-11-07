'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowUpRight, FileText, Plus, RotateCcw } from 'lucide-react';
import MaterialEditor from '@/components/knowledge/MaterialEditor';
import ClaimReview from '@/components/knowledge/ClaimReview';
import CardStudio from '@/components/knowledge/CardStudio';
import VideoStudio from '@/components/knowledge/VideoStudio';
import AnimationStudio from '@/components/knowledge/AnimationStudio';
import { api, yuan, type Health, type Material, type Work } from '@/lib/knowledge';
import { brand } from '@/config/brand';
import './workbench.css';

const empty: Material = { title: '', text: '', url: '', audience: '普通读者' };

export default function KnowledgePage() {
  const [works, setWorks] = useState<Work[]>([]);
  const [work, setWork] = useState<Work | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [materialDirty, setDirty] = useState(false);
  const [cardDirty, setCardDirty] = useState(false);
  const [sceneDirty, setSceneDirty] = useState(false);
  const dirty = materialDirty || cardDirty || sceneDirty;
  const latest = useRef<Work | null>(null);
  const [editorKey, setEditorKey] = useState('new');
  // 一次只显示一个步骤，避免整页变成一条长滚动
  const [step, setStep] = useState(0);
  const accept = useCallback((value: Work) => {
    latest.current = value; setWork(value);
    setWorks(items => [value, ...items.filter(w => w.id !== value.id)]);
  }, []);

  const load = useCallback(async () => {
    try {
      const [data, status] = await Promise.all([api<{ works: Work[] }>('/works'), api<Health>('/health')]);
      setWorks(data.works); setHealth(status); setError('');
    } catch (error) { setError(error instanceof Error ? error.message : '无法连接工作台'); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => {
    let active = true;
    void Promise.all([api<{ works: Work[] }>('/works'), api<Health>('/health')])
      .then(([data, status]) => { if (active) { setWorks(data.works); setHealth(status); } })
      .catch(error => { if (active) setError(error.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const running = work?.jobs.some(j => ['pending', 'running'].includes(j.status)) ?? false;
  const workId = work?.id;
  useEffect(() => {
    if (!running || !workId) return;
    const id = workId;
    const timer = setInterval(() => {
      void api<{ work: Work }>(`/works/${id}`).then(data => {
        if (latest.current?.id === id) accept(data.work);
      }).catch(error => setError(error.message));
    }, 1200);
    return () => clearInterval(timer);
  }, [running, workId, accept]);

  async function save(material: Material) {
    const current = latest.current;
    const data = current
      ? await api<{ work: Work }>(`/works/${current.id}/material`, 'PUT', { ...material, expected_revision: current.revision })
      : await api<{ work: Work }>('/works', 'POST', material);
    accept(data.work);
  }

  async function extract() {
    const current = latest.current;
    if (!current) return;
    await api(`/works/${current.id}/extract`, 'POST', { operation_id: crypto.randomUUID(), expected_revision: current.revision });
    const data = await api<{ work: Work }>(`/works/${current.id}`); accept(data.work);
  }

  async function action(path: string, body: object, method = 'POST') {
    const current = latest.current;
    if (!current) return;
    const data = await api<{ work?: Work }>(`/works/${current.id}${path}`, method, { ...body, expected_revision: current.revision });
    if (data.work) accept(data.work);
    else { const fresh = await api<{ work: Work }>(`/works/${current.id}`); accept(fresh.work); }
  }

  async function open(id: string) {
    if (dirty) { setError("当前材料尚未保存，请先保存成功后再切换作品。"); return; }
    if (!window.confirm('打开另一份作品？请先确认当前材料显示“已保存”。')) return;
    try { const data = await api<{ work: Work }>(`/works/${id}`); accept(data.work); setEditorKey(id); setStep(0); }
    catch (error) { setError(error instanceof Error ? error.message : '无法打开作品'); }
  }

  return <main className="kd-workbench"><a className="kd-skip-link" href="#kd-main">跳到主要内容</a><header className="kd-header"><div className="kd-brand"><span className="kd-logo" aria-hidden="true">知</span><span>{brand.name}<small>{brand.tagline}</small></span></div><span className="kd-local">本机工作空间</span></header>
    <div className="kd-container" id="kd-main" tabIndex={-1} aria-busy={loading}>
      {(() => {
        // 步骤条既是导航也是进度：点一下切到那一步，已完成的显示勾
        const hasCards = !!work?.cards?.length;
        const hasExports = !!work?.exports?.length;
        const hasScenes = !!work?.scenes?.length && work!.scenes!.every(s => s.confirmed);
        const hasVideos = !!work?.videos?.length;
        const steps = [
          { n: '01', label: '材料与核对', done: hasCards, enabled: true },
          { n: '02', label: '卡片与插图', done: hasExports, enabled: !!work },
          { n: '03', label: '动态分镜', done: hasScenes, enabled: hasCards },
          { n: '04', label: '配音视频', done: hasVideos, enabled: hasCards },
        ];
        return <div className="kd-topbar">
          <div className="kd-hero"><div><p className="kd-eyebrow">KNOWLEDGE → CLARITY</p><h1>好图解，从读懂材料开始。</h1><p>先核对内容，再把它变成值得分享的作品。</p></div><div className="kd-budget"><span>本套预算</span><strong>¥ 1.00</strong><small>已核算 ¥{yuan(work?.budget.settled_micro ?? 0)}<br />预留 ¥{yuan(work?.budget.reserved_micro ?? 0)}</small></div></div>
          <nav className="kd-steps" aria-label="创作步骤">{steps.map((s, i) => <button key={s.n} type="button" className={`kd-step${s.done ? ' kd-step-done' : ''}${i === step ? ' kd-step-current' : ''}`} aria-current={i === step ? 'step' : undefined} disabled={!s.enabled} onClick={() => setStep(i)}><b>{s.n}</b>{s.label}{s.done ? <span className="kd-step-check" aria-label="已完成">✓</span> : null}</button>)}</nav>
          {running ? <p className="kd-running-bar" role="status"><span className="kd-running-dot" aria-hidden="true" />任务正在后台运行，可以切到其他步骤继续编辑，不会中断</p> : null}
        </div>;
      })()}
      <div className="kd-toolbar"><div className="kd-work-title"><FileText size={16} />{work?.sources.at(-1)?.title || '新的知识作品'}</div><div className="kd-toolbar-actions">{work ? <button disabled={dirty} className="kd-text-button" onClick={() => void api<{ work: Work }>(`/works/${work.id}`).then(data => { accept(data.work); setEditorKey(`${work.id}-${Date.now()}`); setStep(0); }).catch(e => setError(e.message))}><RotateCcw size={14} />重新载入</button> : null}<button disabled={dirty} className="kd-text-button" onClick={() => { if (!work || window.confirm('开始新的作品？请先确认当前作品已保存。')) { latest.current = null; setWork(null); setEditorKey(`new-${Date.now()}`); setStep(0); } }}><Plus size={15} />新作品</button></div></div>
      {error ? <div className="kd-error" role="alert">{error} <button onClick={() => void load()}>重新连接</button></div> : null}
      {health?.model === 'offline-test' ? <div className="kd-error" role="status">离线交互测试：知识点来自测试替身，不是真实模型结果，不产生费用。</div> : null}
      {loading ? <p role="status" className="kd-loading">正在打开工作空间…</p> : <>
        <div className="kd-stage" hidden={step !== 0}>
          <div className="kd-stage-label"><span className="kd-step-num">01</span>材料与核对</div>
          <div className="kd-grid"><MaterialEditor key={editorKey} initial={work?.sources.at(-1) || empty} onSave={save} onExtract={extract} onDirty={setDirty} busy={running} blocked={cardDirty || sceneDirty} configured={!!(health?.model_configured && health?.paid_calls_enabled && health?.pricing_confirmed)} />{work ? <ClaimReview work={work} onAction={action} locked={dirty || running} /> : <section className="kd-panel kd-intro"><span className="kd-eyebrow">核对之后，才是创作</span><h2>原文与观点，<br />放在一起看。</h2><div className="kd-intro-lines"><p><span>01</span> 提取4–6个核心知识点</p><p><span>02</span> 点击观点，查看原文依据</p><p><span>03</span> 修改、合并，再由你确认</p></div><p className="kd-muted">每一次核对都被保存。<br />原文变化后，相关观点需要重新确认。</p><ArrowUpRight size={34} strokeWidth={1} /></section>}</div>
        </div>
        {work ? <div className="kd-stage" hidden={step !== 1}><div className="kd-stage-label"><span className="kd-step-num">02</span>卡片与插图</div><CardStudio key={editorKey} work={work} health={health} onAction={action} onDirty={setCardDirty} materialDirty={materialDirty || sceneDirty} /></div> : null}
        {work?.cards?.length ? <div className="kd-stage" hidden={step !== 2}><div className="kd-stage-label"><span className="kd-step-num">03</span>动态分镜</div><AnimationStudio key={`${editorKey}-scenes`} work={work} onAction={action} onDirty={setSceneDirty} otherDirty={materialDirty || cardDirty} /></div> : null}
        {work?.cards?.length ? <div className="kd-stage" hidden={step !== 3}><div className="kd-stage-label"><span className="kd-step-num">04</span>配音视频</div><VideoStudio key={`${editorKey}-video`} work={work} health={health} onAction={action} dirty={dirty} /></div> : null}
      </>}
      {work?.jobs.at(-1)?.error ? <p role="alert" className="kd-error">{work.jobs.at(-1)?.error?.message}</p> : null}
      {works.length ? <section className="kd-library"><div><p className="kd-eyebrow">继续创作</p><h2>保存的作品</h2></div><div className="kd-work-list">{works.map(item => <button key={item.id} onClick={() => void open(item.id)}><FileText size={18} /><span>{item.sources.at(-1)?.title}<small>{item.claims.filter(c => c.active && c.confirmed).length}个知识点已确认 · 原文第{item.sources.at(-1)?.revision}版</small></span><ArrowUpRight size={16} /></button>)}</div></section> : null}
      <footer className="kd-footer">来源可见 · 修改可控 · 内容由你确认<span>作品保存在本机，自动提取需联网。</span></footer>
    </div></main>;
}
