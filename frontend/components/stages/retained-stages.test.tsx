import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import ScriptStage from './ScriptStage';
import StoryboardStage from './StoryboardStage';
import ReferenceStage from './ReferenceStage';
import PostProductionStage from './PostProductionStage';
import type { StageViewProps } from './types';
import { editedDescription, selectedPath, isRecord } from '@/lib/workflowTypes';

const props: StageViewProps = {
  state: { status: 'completed', progress: 100, progressMessage: '', artifact: null, error: null },
  sessionId: 'offline-regression', isRunning: false,
  onConfirm() {}, onIntervene() {}, onRegenerate() {},
};

describe('保留底座组件的契约回归（离线，不调用外部服务）', () => {
  it('保留剧本标题和摘要展示', () => {
    const state = { ...props.state, artifact: { title: '离线剧本', logline: '需要保留的原有摘要' } };
    const html = renderToStaticMarkup(<ScriptStage {...props} state={state} />);
    expect(html).toContain('离线剧本');
    expect(html).toContain('需要保留的原有摘要');
  });
  it('保留分镜集与片段数据展示', () => {
    const state = { ...props.state, artifact: { episodes: [{ episode_number: 1, episode_title: '离线第一集', segments: [{ segment_id: 'seg1', segment_number: 1, episode_number: 1, location: '书房', characters: ['讲解者'], total_duration: 5, shots: [{ shot_number: 1, shot_type: '近景', duration: 5, content: '讲解者翻开书本' }] }] }] } };
    const html = renderToStaticMarkup(<StoryboardStage {...props} state={state} />);
    expect(html).toContain('离线第一集');
    expect(html).toContain('书房');
  });
  it('保留参考图版本与选中素材', () => {
    const state = { ...props.state, artifact: { scenes: [{ id: 'scene1', name: '离线画面', description: '书房插图', versions: ['code/result/a.png'], selected: 'code/result/a.png', status: 'done' as const }] } };
    const html = renderToStaticMarkup(<ReferenceStage {...props} state={state} />);
    expect(html).toContain('离线画面');
    expect(html).toContain('code/result/a.png');
  });
  it('保留成片预览和下载地址', () => {
    const state = { ...props.state, artifact: { final_videos: [{ name: '离线成片', path: 'code/result/clip-01.mp4', episode: 1 }] } };
    const html = renderToStaticMarkup(<PostProductionStage {...props} state={state} />);
    expect(html).toContain('离线成片');
    expect(html).toContain('clip-01.mp4');
    expect(html).toContain('下载本集');
  });
  it('不同阶段的描述保存不会丢掉空字符串或串用分组', () => {
    const values = { characters: { hero: '' }, settings: { hero: '场景描述' } };
    expect(editedDescription(values, 'hero', '旧描述', 'characters')).toBe('');
    expect(editedDescription(values, 'hero', '旧描述', 'settings')).toBe('场景描述');
    expect(editedDescription({ scene1: '画面描述' }, 'scene1', '旧描述')).toBe('画面描述');
  });
  it('不合法选项不会作为素材路径或描述写回', () => {
    expect(selectedPath({ selected: 'bad' }, 'old.png')).toBe('old.png');
    expect(selectedPath('new.png', 'old.png')).toBe('new.png');
    expect(editedDescription(null, 'scene1', '旧描述')).toBe('旧描述');
    expect(isRecord([])).toBe(false);
  });
});
