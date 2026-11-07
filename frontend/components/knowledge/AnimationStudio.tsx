'use client';
import { useEffect, useRef, useState } from 'react';
import type { AnimationScene, SceneDraft, Work } from '@/lib/knowledge';
type Action = (path:string,body:object,method?:string)=>Promise<void>;
const initial = (s:AnimationScene):SceneDraft => ({title:s.title,template:s.template,narration:s.narration,steps:s.steps});
function SceneEditor({scene,onAction,onDirty,locked}:{scene:AnimationScene;onAction:Action;onDirty:(v:boolean)=>void;locked:boolean}) {
 const [draft,setDraft]=useState(()=>initial(scene));
 const [saved,setSaved]=useState(()=>JSON.stringify(initial(scene)));
 const [saving,setSaving]=useState(false);
 const [error,setError]=useState('');
 const queue=useRef(Promise.resolve());
 const last=useRef(saved);
 const latest=useRef(draft);
 const action=useRef(onAction);
 const signature=JSON.stringify(draft);
 const valid=draft.title.trim() && draft.narration.trim() && draft.steps.every(s=>s.label.trim());
 useEffect(()=>{latest.current=draft;action.current=onAction;},[draft,onAction]);
 function save(value:SceneDraft) {
  const operation=queue.current.catch(()=>{}).then(async()=>{
   const sig=JSON.stringify(value);if(sig===last.current)return;
   setSaving(true);setError('');
   try {await action.current(`/scenes/${scene.id}`,value,'PATCH');last.current=sig;setSaved(sig);}
   catch(e){setError(e instanceof Error?e.message:'保存失败');throw e;}
   finally{setSaving(false);}
  });queue.current=operation;return operation;
 }
 useEffect(()=>{if(locked||!valid||signature===saved)return;const value=JSON.parse(signature) as SceneDraft;const timer=setTimeout(()=>{void save(value).catch(()=>{});},1000);return()=>clearTimeout(timer);},[signature,saved,valid,locked]);
 useEffect(()=>{onDirty(signature!==saved||saving);},[signature,saved,saving,onDirty]);
 useEffect(()=>{const warn=(e:BeforeUnloadEvent)=>{if(JSON.stringify(latest.current)!==last.current)e.preventDefault();};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[]);
 function step(index:number,key:'label'|'detail',value:string){setDraft(d=>({...d,steps:d.steps.map((s,i)=>i===index?{...s,[key]:value}:s)}));}
 return <div><div className="kd-panel-heading"><h3>这段动画讲什么</h3><span className="kd-save-status" role="status">{saving?'正在保存…':signature===saved?'已保存':'等待保存'}</span></div>
  <fieldset className="kd-material-fields" disabled={locked}>
   <label className="kd-label">分镜标题<input value={draft.title} maxLength={60} onChange={e=>setDraft({...draft,title:e.target.value})}/></label>
   <label className="kd-label">动画形式<select value={draft.template} onChange={e=>setDraft({...draft,template:e.target.value as SceneDraft['template']})}><option value="flow">流程推进：步骤和箭头依次展开</option><option value="relation">关系建立：对象连线与重点高亮</option><option value="compare">对照解释：两侧逐项出现</option></select></label>
   <p className="kd-muted">{draft.template==='flow'?'填写每一步发生什么，动画按顺序推进。':draft.template==='relation'?'填写涉及的对象、它们的关系和要突出的位置。':'分别填写两侧对象及需要强调的共同点或差异。'}</p>
   {draft.steps.map((s,i)=><div className="kd-scene-step" key={i}><label className="kd-label">第{i+1}步：对象或动作<input maxLength={24} value={s.label} onChange={e=>step(i,'label',e.target.value)}/></label><label className="kd-label">需要解释的内容<textarea rows={2} maxLength={160} value={s.detail} onChange={e=>step(i,'detail',e.target.value)} placeholder="用已确认的知识说明这一动作解释了什么"/></label><div className="kd-actions"><button className="kd-text-button" disabled={draft.steps.length<=2} onClick={()=>setDraft({...draft,steps:draft.steps.filter((_,n)=>n!==i)})}>移除此步骤</button></div></div>)}
   <button className="kd-button kd-secondary" disabled={draft.steps.length>=5} onClick={()=>setDraft({...draft,steps:[...draft.steps,{label:`步骤${draft.steps.length+1}`,detail:''}]})}>添加步骤（最多5步）</button>
   <label className="kd-label">对应旁白<textarea rows={3} maxLength={1000} value={draft.narration} onChange={e=>setDraft({...draft,narration:e.target.value})}/></label>
   <div className="kd-actions"><button className="kd-button kd-secondary" disabled={!valid||saving||signature===saved} onClick={()=>void save(latest.current).catch(()=>{})}>保存分镜</button><button className="kd-button kd-primary" disabled={saving||signature!==saved||scene.confirmed||draft.steps.some(s=>!s.detail.trim())} onClick={()=>void action.current(`/scenes/${scene.id}/confirm`,{}).catch(e=>setError(e.message))}>{scene.confirmed?'已核对分镜':'核对并确认这段讲解'}</button></div>
  </fieldset>{error?<p className="kd-error" role="alert">{error}</p>:null}
 </div>;
}
export default function AnimationStudio({work,onAction,onDirty,otherDirty}:{work:Work;onAction:Action;onDirty:(v:boolean)=>void;otherDirty:boolean}) {
 const [selected,setSelected]=useState('');const [dirty,setDirty]=useState(false);const [pending,setPending]=useState(false);const [error,setError]=useState('');
 const scenes=work.scenes||[];const scene=scenes.find(s=>s.id===selected)||scenes[0];
 const current=work.cards_current&&work.scenes_basis===work.deck_fingerprint;
 const running=work.jobs.some(j=>['pending','running'].includes(j.status));
 useEffect(()=>{onDirty(dirty||pending);},[dirty,pending,onDirty]);
 async function act(path:string,body:object,method?:string){setPending(true);try{await onAction(path,body,method);}finally{setPending(false);}}
 return <section className="kd-panel kd-card-studio"><p className="kd-eyebrow">动态讲解 / 分镜编辑</p><h2>先把知识变成可讲清楚的动作</h2><p className="kd-muted">每段说明对象怎样出现、如何连接、哪里需要高亮。这里只准备和保存分镜，不调用模型，不导出媒体。初始步骤是待填写的结构，不是AI分析结果。</p>
 <div className="kd-actions"><button className="kd-button kd-secondary" disabled={otherDirty||dirty||pending||running||!work.cards_current} onClick={()=>{
  if(scenes.length&&!window.confirm('重新准备分镜会保留旧分镜历史；当前编辑请先保存。继续？'))return;
  setError('');void act('/scenes/draft',{}).catch(e=>setError(e.message));
 }}>{scenes.length?'重新准备分镜结构':'从已确认内容准备分镜结构'}</button></div>
 {scenes.length&&!current?<p className="kd-error">知识或卡片已经变化。请重新准备分镜，旧版保留。</p>:null}
 {scene?<div className="kd-cards-layout"><div className="kd-card-picker">{scenes.map((s,i)=><button className="kd-card-pick kd-card-pick-main" key={s.id} disabled={dirty||pending} onClick={()=>setSelected(s.id)}><strong>{i+1}. {s.title}</strong><small>{s.confirmed?'已核对':'待编辑/核对'}</small></button>)}</div><SceneEditor key={scene.id} scene={scene} onAction={act} onDirty={setDirty} locked={!current||otherDirty||running}/></div>:null}
 {error?<p className="kd-error" role="alert">{error}</p>:null}</section>;
}
