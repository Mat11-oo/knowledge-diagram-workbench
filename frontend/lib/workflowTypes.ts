/** Contracts shared by the retained 知识图解工作台 stages and their API client. */
export type AssetStatus = 'pending' | 'running' | 'done' | 'failed';
export type AssetCollection = 'characters' | 'settings' | 'scenes' | 'clips' | 'images';
export interface MediaAsset {
  id: string;
  name: string;
  description: string;
  selected: string;
  versions: string[];
  status?: AssetStatus;
  index?: number;
  title?: string;
  duration?: number;
  episode?: number;
  episode_title?: string;
}
export interface WorkflowShot {
  shot_number: number;
  shot_type: string;
  duration: number;
  content: string;
  visual_prompt?: string;
  plot?: string;
}
export interface WorkflowSegment {
  segment_id: string;
  segment_number: number;
  episode_number: number;
  location: string;
  characters: string[];
  total_duration: number;
  shots: WorkflowShot[];
  is_new?: boolean;
}
export interface WorkflowEpisode {
  episode_number: number;
  episode_title: string;
  segments: WorkflowSegment[];
  episode?: number;
  title?: string;
  act_title?: string;
  content?: string;
}
export interface CompletedAct {
  act: number;
  act_name: string;
  characters: unknown[];
  settings: unknown[];
  scenes: unknown[];
}
export interface WorkflowArtifact {
  [key: string]: unknown;
  session_id?: string;
  title?: string;
  phase?: string;
  beat_sheet?: string;
  completed_acts?: CompletedAct[];
  characters?: MediaAsset[];
  settings?: MediaAsset[];
  scenes?: MediaAsset[];
  clips?: MediaAsset[];
  images?: MediaAsset[];
  shots?: WorkflowShot[];
  segments?: WorkflowSegment[];
  episodes?: WorkflowEpisode[];
  payload?: WorkflowArtifact;
  final_video?: string;
  final_videos?: { name: string; path: string; episode?: number }[];
}
export interface SessionSummary {
  id: string;
  title?: string;
  idea?: string;
  style?: string;
  date?: number;
  status?: Record<string, string>;
  stage_ids?: string[];
  scenario?: string;
}
export interface SessionMeta {
  scenario?: string;
  idea?: string;
  user_textbox_input?: string;
  style?: string;
  video_ratio?: string;
  video_resolution?: string;
  llm_model?: string;
  vlm_model?: string;
  image_t2i_model?: string;
  image_it2i_model?: string;
  video_model?: string;
  video_generation_mode?: import("@/config/models").VideoGenerationMode;
  video_first_frame_model?: string;
  video_start_end_model?: string;
  video_reference_model?: string;
  expand_idea?: boolean;
  enable_concurrency?: boolean;
  web_search?: boolean;
}
export interface AssetUpdate extends Partial<MediaAsset> { id: string; type: AssetCollection }
export interface StageProgress { percent?: number; message?: string; step?: string }
export type SelectionPatch = WorkflowArtifact & { _editDescs?: unknown };
export function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
export function selectedPath(value: unknown, fallback: string): string {
  return typeof value === 'string' && value ? value : fallback;
}
export function editedDescription(value: unknown, id: string, fallback: string, group?: string): string {
  if (!isRecord(value)) return fallback;
  const descriptions = group ? value[group] : value;
  if (!isRecord(descriptions)) return fallback;
  return typeof descriptions[id] === 'string' ? descriptions[id] : fallback;
}
