import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import CardStudio from './CardStudio';
import type { Card, Work } from '@/lib/knowledge';

const card: Card = { id: 'a'.repeat(32), claim_id: 'claim', title: '测试标题', body: '已确认正文', narration: '旁白草稿', prompt: '插图主题', template: 'paper', illustration_id: null, kind: 'supplement', edited: false };
const work: Work = { id: 'b'.repeat(32), revision: 1, stage: 'reviewed', sources: [{ title: '材料', text: '原始材料', url: '', audience: '读者', revision: 1 }], claims: [], cards: [card, { ...card, id: 'c'.repeat(32) }, { ...card, id: 'd'.repeat(32) }], jobs: [], cards_current: true, deck_fingerprint: 'current', exports: [], budget: { settled_micro: 0, reserved_micro: 0, available_micro: 1000000 } };
const render = (value: Work) => renderToStaticMarkup(<CardStudio work={value} health={null} onAction={async () => {}} onDirty={() => {}} materialDirty={false} />);

describe('card workflow communication', () => {
  it('keeps paid generation disabled until the backend reports enabled configuration', () => {
    const html = render(work);
    expect(html).toMatch(/disabled=""[^>]*>[\s\S]*?生成这张插图/);
    expect(html).toContain('真实生图尚未启用');
    expect(html).toContain('初稿沿用知识点原文');
  });
  it('explains re-review requirements while retaining immutable version download links', () => {
    const html = render({ ...work, cards_current: false, exports: [{ id: 'old', fingerprint: 'old', files: [], cards: work.cards }] });
    expect(html).toContain('原文或知识点已变化');
    expect(html).toContain(`/exports/old/all.zip`);
    expect(html).toContain('旧版本，当前内容需重新导出');
  });
  it('identifies incomplete illustration drafts in exported history', () => {
    const html = render({ ...work, exports: [{ id: 'draft', fingerprint: 'current', files: [], cards: work.cards }] });
    expect(html).toContain('含待插图草稿');
    expect(html).toContain('/draft/01.png');
    expect(html).toContain('补充说明');
  });
});
