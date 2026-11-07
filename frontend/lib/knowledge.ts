export type Material = { title: string; text: string; url: string; audience: string };
export type Source = Material & { revision: number };
export type Reference = { source_revision: number; start_cp: number; end_cp: number; quote: string };
export type Claim = { id: string; text: string; kind: 'source' | 'supplement'; references: Reference[]; confirmed: boolean; active: boolean };
export type Job = { id: string; kind?: string; status: string; error: { code: string; message: string } | null };
export type Work = { id: string; revision: number; stage: string; sources: Source[]; claims: Claim[]; jobs: Job[]; scenes?: AnimationScene[]; scenes_basis?: string; videos?: VideoVersion[]; cards: Card[]; cards_current: boolean; deck_fingerprint: string; exports: ExportVersion[]; budget: { settled_micro: number; reserved_micro: number; available_micro: number } };
export type Health = { model_configured: boolean; paid_calls_enabled: boolean; pricing_confirmed: boolean; model: string; tts_configured?: boolean; tts_enabled?: boolean; tts_model?: string; image_configured?: boolean; image_enabled?: boolean; image_price_micro?: number };

export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`/api/knowledge${path}`, {
    method, headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined, cache: 'no-store',
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(data?.error?.message || '暂时无法连接工作台，请检查服务后重试');
  return data;
}

export const yuan = (micro: number) => (micro / 1_000_000).toFixed(3);

// Python indexes Unicode code points; JS string.slice indexes UTF-16 units.
export function sourceParts(text: string, ref: Reference) {
  const cp = Array.from(text);
  return { before: cp.slice(0, ref.start_cp).join(''), quote: cp.slice(ref.start_cp, ref.end_cp).join(''), after: cp.slice(ref.end_cp).join('') };
}

export function referenceValid(source: Source, ref: Reference) {
  return source.revision === ref.source_revision && sourceParts(source.text, ref).quote === ref.quote;
}

export type Card = { id: string; claim_id: string; title: string; body: string; narration: string; prompt: string; template: 'paper' | 'ink'; illustration_id: string | null; kind: 'source' | 'supplement'; edited: boolean };
export type CardDraft = Pick<Card, 'title' | 'body' | 'narration' | 'prompt' | 'template'>;
export type ExportVersion = { id: string; fingerprint: string; files: string[]; cards: Card[] };
export const exportUrl = (workId: string, versionId: string, file: string) => `/api/knowledge/works/${workId}/exports/${versionId}/${file}`;
export type VideoPlan = { characters: number; segments: number; uncached_segments: number; reserve_micro: number; voice: string; model: string };
export type VideoVersion = { id: string; fingerprint: string; filename: string; duration_ms: number; model: string; timeline: { text: string; card_id: string; audio_id: string; start_ms: number; end_ms: number }[] };
export const videoUrl = (workId: string, videoId: string) => `/api/knowledge/works/${workId}/videos/${videoId}.mp4`;
export type AnimationStep = { label: string; detail: string };
export type AnimationScene = { id: string; claim_id: string; card_id: string; title: string; template: 'flow' | 'relation' | 'compare'; narration: string; steps: AnimationStep[]; confirmed: boolean };
export type SceneDraft = Pick<AnimationScene,'title'|'template'|'narration'|'steps'>;
