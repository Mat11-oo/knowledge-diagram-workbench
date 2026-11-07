'use client';
import { useState } from 'react';
import { api, videoUrl, yuan, type Health, type VideoPlan, type Work } from '@/lib/knowledge';

type Action = (path: string, body: object, method?: string) => Promise<void>;
export default function VideoStudio({work, health, onAction, dirty}: {work: Work; health: Health | null; onAction: Action; dirty: boolean}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [plan, setPlan] = useState<VideoPlan | null>(null);
  const running = work.jobs.some(j => ['pending','running'].includes(j.status));
  const disabled = dirty || pending || running;
  const characters = work.cards.reduce((n,c) => n+Array.from(c.narration.trim()).length,0);
  const scenesReady = !!work.scenes?.length && work.scenes_basis === work.deck_fingerprint && work.scenes.length === work.cards.length && work.scenes.every(scene => scene.confirmed && scene.steps.every(step => step.label.trim() && step.detail.trim()));
  async function act(path: string, body: object) {
    setPending(true); setError('');
    try { await onAction(path,body); }
    catch(e) { setError(e instanceof Error ? e.message : '操作未完成'); }
    finally { setPending(false); }
  }
  async function checkPlan() {
    setPending(true); setError('');
    try { setPlan(await api<VideoPlan>(`/works/${work.id}/video-plan`)); }
    catch(e) { setPlan(null); setError(e instanceof Error ? e.message : '无法检查旁白'); }
    finally { setPending(false); }
  }
  async function generate() {
    setPending(true); setError('');
    try {
      const current = await api<VideoPlan>(`/works/${work.id}/video-plan`);
      setPlan(current);
      if (!window.confirm(`将按${current.segments}个短句制作配音与字幕视频，其中${current.uncached_segments}句需要云端配音，费用预留上限¥${yuan(current.reserve_micro)}。不自动重试；已完成音频会复用。继续？`)) return;
      await onAction('/videos',{operation_id: crypto.randomUUID(),max_cost_micro: current.reserve_micro});
    } catch(e) { setError(e instanceof Error ? e.message : '视频未完成'); }
    finally { setPending(false); }
  }
  return <section className="kd-panel kd-card-studio" aria-labelledby="video-title"><p className="kd-eyebrow">04 / 配音与字幕视频</p><h2 id="video-title">把图解讲给读者听</h2>
    <p className="kd-muted">每个短句分别配音，按真实音频时长切换字幕。卡片、旁白或顺序变化后，旧视频保留，点击更新才会重新制作。</p>
    <p className="kd-muted">整套分镜旁白 {characters} / 180–240字。旁白需在上方分镜编辑中逐段确认；每段步骤都会对应画面高亮。卡片修改后需重新核对分镜并导出当前PNG。</p>
    {!scenesReady ? <p className="kd-error" role="status">请先补全并确认全部当前分镜；分镜过期或未确认时不会开始配音。</p> : null}
    <div className="kd-actions"><button className="kd-button kd-secondary" disabled={disabled || !work.cards_current || !scenesReady} onClick={() => void checkPlan()}>检查旁白与费用</button><button className="kd-button kd-primary" disabled={disabled || !work.cards_current || !scenesReady || !(health?.tts_configured && health?.tts_enabled)} onClick={() => void generate()}>{running ? '任务进行中…' : work.videos?.length ? '更新配音字幕视频' : '制作配音字幕视频'}</button></div>
    {plan ? <p className="kd-muted">{plan.segments}个短句 · {plan.uncached_segments}句待配音 · 上限预留¥{yuan(plan.reserve_micro)} · {plan.model} / {plan.voice}。生成时会重新检查当前卡片。</p> : null}
    {!health?.tts_enabled ? <p className="kd-muted">真实配音尚未启用。可先编辑旁白并检查费用。</p> : null}
    {error ? <p className="kd-error" role="alert">{error}</p> : null}
    {work.jobs.filter(j=>j.kind==='video' && ['failed','interrupted'].includes(j.status)).map(j=><div key={j.id} className="kd-error"><p>{j.error?.message}</p><button className="kd-text-button" disabled={disabled} onClick={()=>void act(`/video-jobs/${j.id}/resume`,{})}>继续原任务（复用已完成音频）</button></div>)}
    {(work.videos || []).length ? <div className="kd-video-history">{[...(work.videos || [])].reverse().map((video,i)=><article key={video.id}><h3>视频第{(work.videos?.length || 0)-i}版 · {(video.duration_ms/1000).toFixed(2)}秒</h3><p className="kd-muted">{video.fingerprint===work.deck_fingerprint && work.cards_current ? '与当前卡片一致' : '卡片已修改，旧视频保留，需点击更新'}{video.model.startsWith('offline-') ? ' · 离线测试音频，不是真实配音' : ''}</p><video controls preload="metadata" src={videoUrl(work.id,video.id)} aria-label={`图解视频第${(work.videos?.length || 0)-i}版`} /><a className="kd-button kd-secondary" href={videoUrl(work.id,video.id)} download>下载MP4</a></article>)}</div> : null}
  </section>;
}
