import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it } from 'vitest';
import VideoStudio from './VideoStudio';
import type { Work } from '@/lib/knowledge';
const work: Work = { id:'work', revision:1, stage:'reviewed', cards:[], cards_current:true, deck_fingerprint:'new', exports:[], sources:[], claims:[], jobs:[], budget:{settled_micro:0,reserved_micro:0,available_micro:1000000}, videos:[{id:'old',fingerprint:'old',filename:'old.mp4',duration_ms:36000,model:'offline-tts-test',timeline:[]}] };
it('retains old video preview and explains update is manual',()=>{
 const html=renderToStaticMarkup(<VideoStudio work={work} health={null} onAction={async()=>{}} dirty={false}/>);
 expect(html).toContain('旧视频保留，需点击更新');
 expect(html).toContain('/videos/old.mp4');
 expect(html).toContain('离线测试音频，不是真实配音');
});
it('keeps real synthesis disabled before authorization and configuration',()=>{
 const html=renderToStaticMarkup(<VideoStudio work={{...work,videos:[]}} health={null} onAction={async()=>{}} dirty={false}/>);
 expect(html).toContain('真实配音尚未启用');
 expect(html).toContain('请先补全并确认全部当前分镜');
 expect(html).toMatch(/disabled=""[^>]*>检查旁白与费用/);
 expect(html).toMatch(/disabled=""[^>]*>制作配音字幕视频/);
});
