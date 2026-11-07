import type { WorkflowArtifact, SessionSummary, SessionMeta, AssetUpdate, CompletedAct, WorkflowShot, StageProgress } from './workflowTypes';
/**
 * 工作流 API 客户端
 */

/**
 * Streaming endpoints must bypass the Next.js rewrite proxy because it buffers
 * the entire upstream response before forwarding, which breaks SSE real-time delivery.
 * Non-streaming endpoints can still go through the proxy (relative URL).
 */
const STREAM_API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8137';

export interface StageInfo {
  id: string;
  name: string;
  order: number;
  description: string;
}

/** 场景包中的一个阶段（内置阶段 type 与 id 相同；自定义阶段 type 为 "custom"） */
export interface StageDef {
  id: string;
  type: string;
  name: string;
  short_name: string;
  description: string;
  custom: boolean;
  /** 传给阶段 agent 的参数；UI 不使用 */
  options?: Record<string, unknown>;
}

export interface ScenarioExample {
  title: string;
  description?: string;
  idea: string;
  image?: string;
}

export interface ScenarioDefaults {
  style?: string;
  video_ratio?: string;
  video_resolution?: string;
  video_generation_mode?: string;
  episodes?: number;
  expand_idea?: boolean;
}

export interface ScenarioUi {
  hero_title?: string;
  hero_subtitle?: string;
  placeholder?: string;
  episodes_label?: string;
  examples?: ScenarioExample[];
}

export interface Scenario {
  id: string;
  name: string;
  tagline: string;
  description: string;
  category: 'video' | 'image' | string;
  order: number;
  stages: StageDef[];
  defaults: ScenarioDefaults;
  /** 场景自带的额外画风，追加在内置 STYLES 之后 */
  styles?: { id: string; label: string }[];
  ui: ScenarioUi;
  requires_video_model: boolean;
}

export interface ScenarioList {
  default: string;
  scenarios: Scenario[];
  errors: Record<string, string>;
}

export interface ProjectStatus extends SessionMeta {
  artifacts?: Record<string, WorkflowArtifact>;
  stage_progress?: Record<string, StageProgress>;
  meta?: SessionMeta;
  session_id: string;
  current_stage: string;
  status: Record<string, string>;
  error: string | null;
  scenario?: string;
  stages?: StageDef[];
}

/**
 * 从状态快照中解析会话的阶段列表。
 * 优先使用后端返回的 stages；缺失时（旧版后端）按 status 的键顺序兜底。
 */
export function resolveSessionStages(snapshot: { stages?: StageDef[]; status?: Record<string, string> } | null | undefined, fallback: StageDef[] = []): StageDef[] {
  if (Array.isArray(snapshot?.stages) && snapshot.stages.length > 0) return snapshot.stages;
  if (fallback.length > 0) return fallback;
  const keys = Object.keys(snapshot?.status || {});
  return keys.map(id => ({ id, type: id, name: id, short_name: id, description: '', custom: false }));
}

/** 自定义阶段使用通用渲染组件；内置阶段按 type 选择专用组件 */
export function isCustomStage(stage?: StageDef | null): boolean {
  return !!stage && (stage.custom || stage.type === 'custom');
}

export interface StreamEvent {
  type: 'progress' | 'heartbeat' | 'stage_complete' | 'error' | 'content';
  message?: string;
  phase?: string;
  step_desc?: string;
  percent?: number;
  stage?: string;
  status?: string;
  requires_intervention?: boolean;
  payload_summary?: unknown;
  content?: string;
  time?: number;
  data?: { assets_preview?: WorkflowArtifact; asset_complete?: AssetUpdate; beat_sheet?: string; act_complete?: CompletedAct; scene_shots_complete?: { shots: WorkflowShot[] } };
}

export interface PipelineTask {
  task_id: string;
  pipeline: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | string;
  progress?: number;
  message?: string;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  artifacts?: Array<{ kind: string; name?: string; path: string; exists?: boolean; created_at?: string }>;
  error?: string | null;
  created_at?: string;
  updated_at?: string;
  output_dir?: string;
}

export interface SandboxInput {
  [key: string]: unknown;
  prompt?: string;
  reference_image?: string;
  images?: string[];
}

export interface SandboxTask {
  id: string;
  tool: string;
  model: string;
  input?: SandboxInput;
  status: string;
  progress?: number;
  created_at?: string;
}

export interface PipelineStartResponse {
  task_id: string;
  pipeline: string;
  status: string;
  metadata_url: string;
  output_dir: string;
}

export interface PipelineTaskEvent {
  type: 'snapshot' | 'progress' | 'artifact' | 'completed' | 'failed';
  task_id: string;
  status?: string;
  progress?: number;
  artifact?: { kind: string; name?: string; path: string; exists?: boolean; created_at?: string };
}

export interface ApiModelOption {
  id: string;
  label: string;
  provider: string;
  family?: string;
  media_type?: 'image' | 'video';
  model_type?: 'llm' | 'vlm' | 't2i' | 'i2i' | 'video';
  type?: string[];
  ability_type?: string;
  ability_types?: string[];
  adapter_ability_types?: string[];
  input_modalities?: string[];
  adapter_input_modalities?: string[];
  api_contract_verified?: boolean;
  capabilities?: Record<string, unknown>;
}

export interface StandardTemplateOption {
  id: string;
  name: string;
  label: string;
  size: string;
  ratio: '9:16' | '1:1' | '16:9' | string;
  width: number;
  height: number;
  media_width: number;
  media_height: number;
  media_ratio: string;
  media_resolution: string;
  supports_video?: boolean;
  fields: Array<{ key: string; type: string; default: string }>;
  preview_url: string;
}

async function requireOkResponse(response: Response, fallbackMessage: string): Promise<Response> {
  if (response.ok) return response;

  const payload = await response.json().catch(() => null);
  const detail = typeof payload?.detail === 'string' ? payload.detail : fallbackMessage;
  throw new Error(`${detail} (HTTP ${response.status})`);
}

export async function fetchStages(): Promise<StageInfo[]> {
  const resp = await fetch('/api/stages');
  await requireOkResponse(resp, '获取工作流阶段失败');
  const data = await resp.json();
  return data.stages;
}

export async function fetchScenarios(): Promise<ScenarioList> {
  const resp = await fetch('/api/scenarios');
  await requireOkResponse(resp, '获取场景列表失败');
  const data = await resp.json();
  return {
    default: data.default || '',
    scenarios: Array.isArray(data.scenarios) ? data.scenarios : [],
    errors: data.errors || {},
  };
}

export async function fetchSessions(): Promise<SessionSummary[]> {
  const resp = await fetch('/api/sessions');
  await requireOkResponse(resp, '获取会话列表失败');
  const data = await resp.json();
  return data.sessions || [];
}

async function postPipelineTask(path: string, params: Record<string, unknown>): Promise<PipelineStartResponse> {
  const resp = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: '启动任务失败' }));
    throw new Error(err.detail || '启动任务失败');
  }
  return resp.json();
}

export async function startStandardPipeline(params: Record<string, unknown>): Promise<PipelineStartResponse> {
  return postPipelineTask('/api/pipelines/standard/tasks', params);
}

export async function startActionTransferPipeline(params: Record<string, unknown>): Promise<PipelineStartResponse> {
  return postPipelineTask('/api/pipelines/action_transfer/tasks', params);
}

export async function startDigitalHumanPipeline(params: Record<string, unknown>): Promise<PipelineStartResponse> {
  return postPipelineTask('/api/pipelines/digital_human/tasks', params);
}

export async function fetchPipelineTasks(limit = 100): Promise<PipelineTask[]> {
  const resp = await fetch(`/api/tasks?limit=${limit}`);
  if (!resp.ok) throw new Error('获取任务历史失败');
  const data = await resp.json();
  return data.tasks || [];
}

export async function fetchPipelineTask(taskId: string): Promise<PipelineTask> {
  const resp = await fetch(`/api/tasks/${taskId}`);
  if (!resp.ok) throw new Error('获取任务状态失败');
  return resp.json();
}

export async function fetchSandboxTasks(): Promise<SandboxTask[]> {
  const resp = await fetch('/api/sandbox/tasks');
  if (!resp.ok) return [];
  const data = await resp.json();
  return data.tasks || [];
}

export async function clearTempCache(): Promise<{ status: string; deleted: number; freed_bytes?: number; freed_mb?: number; errors?: Array<{ path: string; error: string }> }> {
  const resp = await fetch('/api/cache/temp', { method: 'DELETE' });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: '清空缓存失败' }));
    throw new Error(err.detail || '清空缓存失败');
  }
  return resp.json();
}

export async function deletePipelineTask(taskId: string): Promise<void> {
  const resp = await fetch(`/api/tasks/${taskId}`, { method: 'DELETE' });
  if (!resp.ok) throw new Error('删除任务失败');
}

export async function fetchApiModels(params: {
  mediaType?: 'image' | 'video';
  modelType?: 'llm' | 'vlm' | 't2i' | 'i2i' | 'video';
  ability?: string;
  verifiedOnly?: boolean;
} = {}): Promise<ApiModelOption[]> {
  const search = new URLSearchParams();
  if (params.mediaType) search.set('media_type', params.mediaType);
  if (params.modelType) search.set('model_type', params.modelType);
  if (params.ability) search.set('ability', params.ability);
  if (params.verifiedOnly) search.set('verified_only', 'true');
  const resp = await fetch(`/api/models${search.toString() ? `?${search.toString()}` : ''}`);
  if (!resp.ok) throw new Error('获取模型列表失败');
  const data = await resp.json();
  return data.models || [];
}

export async function fetchStandardTemplates(): Promise<StandardTemplateOption[]> {
  const resp = await fetch('/api/pipelines/standard/templates');
  if (!resp.ok) throw new Error('获取模版列表失败');
  const data = await resp.json();
  return data.templates || [];
}

export async function uploadMedia(file: File): Promise<{ filename: string; file_path: string }> {
  const formData = new FormData();
  formData.append('file', file);
  const resp = await fetch('/api/upload_media', {
    method: 'POST',
    body: formData,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: '上传失败' }));
    throw new Error(err.detail || '上传失败');
  }
  return resp.json();
}

export async function uploadArtifactImage(
  sessionId: string,
  stage: string,
  itemType: string,
  itemId: string,
  file: File,
): Promise<{ status: string; path: string; artifact: WorkflowArtifact; status_map: Record<string, string> }> {
  const formData = new FormData();
  formData.append('item_type', itemType);
  formData.append('item_id', itemId);
  formData.append('file', file);
  const resp = await fetch(`/api/project/${sessionId}/artifact/${stage}/upload_image`, {
    method: 'POST',
    body: formData,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: '上传图片失败' }));
    throw new Error(err.detail || '上传图片失败');
  }
  return resp.json();
}

export function subscribePipelineTask(
  taskId: string,
  onEvent: (event: PipelineTaskEvent) => void,
  onError?: () => void,
): () => void {
  const source = new EventSource(`${STREAM_API_BASE}/api/tasks/${taskId}/events`);
  source.onmessage = event => {
    try {
      onEvent(JSON.parse(event.data));
    } catch {
      // Ignore malformed stream events.
    }
  };
  source.onerror = () => {
    onError?.();
    source.close();
  };
  return () => source.close();
}

export interface StartProjectResponse {
  session_id: string;
  status: Record<string, string>;
  params: Record<string, unknown>;
  scenario?: string;
  stages?: StageDef[];
}

export async function startProject(params: {
  scenario?: string;
  idea: string;
  file_path?: string;
  style?: string;
  video_ratio?: string;
  video_resolution?: string;
  llm_model?: string;
  vlm_model?: string;
  image_t2i_model?: string;
  image_it2i_model?: string;
  video_model?: string;
  video_first_frame_model?: string;
  video_start_end_model?: string;
  video_reference_model?: string;
  video_generation_mode?: string;
  scene_number?: number;
  enable_concurrency?: boolean;
  web_search?: boolean;
  expand_idea?: boolean;
  episodes?: number;
}): Promise<StartProjectResponse> {
  const resp = await fetch('/api/project/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: '项目创建失败' }));
    throw new Error(err.detail || '项目创建失败');
  }
  return resp.json();
}

export async function getProjectStatus(sessionId: string): Promise<ProjectStatus> {
  const resp = await fetch(`/api/project/${sessionId}/status`);
  if (!resp.ok) throw new Error('Failed to get project status');
  return resp.json();
}

// 兼容旧路由名；后端实际会通过统一的 workflow state 入口返回状态。
export async function getProjectStatusFromDisk(sessionId: string): Promise<ProjectStatus> {
  const resp = await fetch(`/api/project/${sessionId}/status/from_disk`);
  if (!resp.ok) throw new Error('Failed to get project status snapshot');
  return resp.json();
}

export async function getArtifact(sessionId: string, stage: string): Promise<{ artifact: WorkflowArtifact }> {
  const resp = await fetch(`/api/project/${sessionId}/artifact/${stage}`);
  if (!resp.ok) throw new Error(`Artifact for stage '${stage}' not found`);
  return resp.json();
}

export async function checkSceneAssets(sessionId: string, sceneNumber: number): Promise<{
  scene_number: number;
  reference_images: number;
  videos: number;
  shot_count: number;
}> {
  const resp = await fetch(`/api/project/${sessionId}/scene/${sceneNumber}/assets`);
  if (!resp.ok) return { scene_number: sceneNumber, reference_images: 0, videos: 0, shot_count: 0 };
  return resp.json();
}

export async function executeStage(
  sessionId: string,
  stage: string,
  inputData: Record<string, unknown> = {},
  signal?: AbortSignal,
): Promise<Response> {
  const response = await fetch(`${STREAM_API_BASE}/api/project/${sessionId}/execute/${stage}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(inputData),
    signal,
  });
  return requireOkResponse(response, `阶段 ${stage} 启动失败`);
}

export async function intervene(
  sessionId: string,
  stage: string,
  modifications: Record<string, unknown>,
): Promise<Response> {
  // Use STREAM_API_BASE to bypass Next.js proxy (SSE endpoint)
  const response = await fetch(`${STREAM_API_BASE}/api/project/${sessionId}/intervene`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ stage, modifications }),
  });
  return requireOkResponse(response, `阶段 ${stage} 修改失败`);
}

export async function stopProject(sessionId: string): Promise<{ status: string }> {
  const resp = await fetch(`/api/project/${sessionId}/stop`, {
    method: 'POST',
  });
  await requireOkResponse(resp, '停止项目失败');
  return resp.json();
}

export async function updateModels(
  sessionId: string,
  models: Partial<Record<string, string | boolean>>,
): Promise<{ status: string }> {
  const resp = await fetch(`/api/project/${sessionId}/models`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(models),
  });
  await requireOkResponse(resp, '更新项目模型失败');
  return resp.json();
}

export async function deleteSession(
  sessionId: string,
): Promise<{ status: string }> {
  const resp = await fetch(`/api/sessions/${sessionId}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: '删除失败' }));
    throw new Error(err.detail || '删除失败');
  }
  return resp.json();
}

export async function saveSelections(
  sessionId: string,
  stage: string,
  selections: Record<string, unknown>,
): Promise<{ status: string }> {
  const resp = await fetch(`/api/project/${sessionId}/artifact/${stage}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(selections),
  });
  if (!resp.ok) throw new Error('保存选项失败');
  return resp.json();
}

export async function continueWorkflow(sessionId: string): Promise<{ status: string; next_stage?: string; status_map?: Record<string, string> }> {
  const resp = await fetch(`/api/project/${sessionId}/continue`, {
    method: 'POST',
  });
  await requireOkResponse(resp, '继续工作流失败');
  return resp.json();
}

export async function* parseStreamEvents(response: Response): AsyncGenerator<StreamEvent> {
  if (!response.body) throw new Error('阶段事件流没有响应体');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let terminalEventReceived = false;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || ''; // keep incomplete trailing line in buffer
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const event: StreamEvent = JSON.parse(line);
        if (event.type === 'stage_complete' || event.type === 'error') terminalEventReceived = true;
        if (event.type !== 'heartbeat') yield event;
      } catch { /* skip malformed */ }
    }
  }
  // Process any remaining data in buffer after stream ends
  if (buffer.trim()) {
    try {
      const event: StreamEvent = JSON.parse(buffer);
      if (event.type === 'stage_complete' || event.type === 'error') terminalEventReceived = true;
      if (event.type !== 'heartbeat') yield event;
    } catch { /* skip malformed */ }
  }
  if (!terminalEventReceived) {
    throw new Error('阶段事件流提前结束，未收到完成或错误事件');
  }
}
