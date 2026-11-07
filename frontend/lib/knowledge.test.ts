import { describe, expect, it } from 'vitest';
import { referenceValid, sourceParts, yuan, type Reference } from './knowledge';

describe('知识引用与费用展示', () => {
  const ref: Reference = { source_revision: 1, start_cp: 1, end_cp: 3, quote: '甲乙' };
  it('emoji前缀不使Python码点引用偏移', () => { expect(sourceParts('😀甲乙丙', ref)).toEqual({ before: '😀', quote: '甲乙', after: '丙' }); });
  it('新原文版本不能沿用旧确认', () => { expect(referenceValid({ title: '标题', text: '😀甲乙丙', url: '', audience: '', revision: 2 }, ref)).toBe(false); });
  it('引用文字变化拒绝匹配', () => { expect(referenceValid({ title: '标题', text: '😀甲丁丙', url: '', audience: '', revision: 1 }, ref)).toBe(false); });
  it('微元保留到厘不错误展示为零元', () => { expect(yuan(12345)).toBe('0.012'); });
});
