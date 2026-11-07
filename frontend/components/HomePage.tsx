'use client';

import React, { useState, useRef, useEffect } from 'react';
import { Settings2, Clock, ArrowRight, CheckCircle, Trash2, Globe, ListOrdered, Loader2, Film, ImageIcon } from 'lucide-react';
import clsx from 'clsx';
import { brand } from '@/config/brand';
import {
  STYLES,
  VIDEO_RATIOS,
  VIDEO_RESOLUTIONS,
  VIDEO_GENERATION_MODES,
  type ProviderGroup,
  type VideoGenerationMode,
} from '@/config/models';
import { fetchModelGroupsByType, fetchVideoModelGroupsByAbility } from '@/lib/modelRegistry';
import { fetchScenarios, type Scenario } from '@/lib/workflowApi';

const SCENARIO_STORAGE_KEY = `${brand.storagePrefix}.scenario`;

/* 首页默认文案：场景未声明 ui 字段或场景列表加载失败时使用 */
const DEFAULT_HERO_TITLE = 'Hi，一起聊聊你的创作想法';
const DEFAULT_HERO_SUBTITLE = '从一句灵感开始，让 AI 陪你完成整部作品';
const DEFAULT_PLACEHOLDER = '描述你的想法，输入一段故事、一个画面或一句灵感……';

function readStoredScenario(): string {
  try {
    return window.localStorage.getItem(SCENARIO_STORAGE_KEY) || '';
  } catch {
    return '';
  }
}

function writeStoredScenario(id: string) {
  try {
    window.localStorage.setItem(SCENARIO_STORAGE_KEY, id);
  } catch {
    // ignore storage failures (private mode / quota)
  }
}

export interface ProjectParams {
  /** 场景包 id；留空时后端使用默认场景 */
  scenario?: string;
  idea: string;
  file_path?: string; // 上传的文件路径 (由后端返回的文件名)
  style: string;
  video_ratio: string;
  video_resolution: string;
  llm_model: string;
  vlm_model: string;
  image_t2i_model: string;
  image_it2i_model: string;
  video_model: string;
  video_first_frame_model: string;
  video_start_end_model: string;
  video_reference_model: string;
  video_generation_mode: VideoGenerationMode;
  expand_idea?: boolean;
  enable_concurrency?: boolean;
  web_search?: boolean;
  episodes?: number;
}

interface HistoryItem {
  id: string;
  idea: string;
  style?: string;
  date: string;
  status: string;
  stages?: Record<string, string>;
  /** 会话所属场景的阶段顺序 */
  stageIds?: string[];
  scenario?: string;
}

interface HomePageProps {
  onStartProject: (params: ProjectParams, autoMode?: boolean) => void;
  onResumeProject: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => Promise<void>;
  history: HistoryItem[];
}

/* 会话自身的阶段顺序：优先 stage_ids，旧数据回退到 status 映射的键 */
function sessionStageIds(item: HistoryItem): string[] {
  if (item.stageIds && item.stageIds.length > 0) return item.stageIds;
  return Object.keys(item.stages || {});
}

function isSessionDone(item: HistoryItem): boolean {
  const ids = sessionStageIds(item);
  const map = item.stages || {};
  return ids.length > 0 && ids.every(id => ["completed", "session_completed"].includes(map[id]));
}

/* 根据会话自己的阶段列表生成进度文本 */
function stageProgressLabel(item: HistoryItem, scenario?: Scenario): { text: string; color: string } {
  const map = item.stages || {};
  const ids = sessionStageIds(item);
  const completed = ids.filter(id => ["completed", "session_completed"].includes(map[id]));
  if (completed.length === 0) return { text: '未开始', color: 'text-gray-400' };
  if (isSessionDone(item)) return { text: '已完成', color: 'text-green-600' };

  const lastStageId = completed[completed.length - 1];
  const stageDef = scenario?.stages.find(s => s.id === lastStageId);
  const name = stageDef?.short_name || stageDef?.name || lastStageId;
  return { text: `已完成：${name} (${completed.length}/${ids.length})`, color: 'text-neutral-900' };
}

export default function HomePage({ onStartProject, onResumeProject, onDeleteSession, history }: HomePageProps) {
  const [idea, setIdea] = useState('');
  const [showSettings, setShowSettings] = useState(false);
  const [selectedStyle, setSelectedStyle] = useState('realistic');
  const [selectedLLM, setSelectedLLM] = useState('');
  const [selectedVLM, setSelectedVLM] = useState('');
  const [selectedT2I, setSelectedT2I] = useState('');
  const [selectedI2I, setSelectedI2I] = useState('');
  const [selectedFirstFrameVideo, setSelectedFirstFrameVideo] = useState('');
  const [selectedStartEndVideo, setSelectedStartEndVideo] = useState('');
  const [selectedReferenceVideo, setSelectedReferenceVideo] = useState('');
  const [selectedVideoMode, setSelectedVideoMode] = useState<VideoGenerationMode>('first_frame');
  const [selectedRatio, setSelectedRatio] = useState('');
  const [selectedResolution, setSelectedResolution] = useState('720P');
  const [configLoading, setConfigLoading] = useState(true);
  const [configError, setConfigError] = useState('');
  const [enableConcurrency, setEnableConcurrency] = useState(true);
  const [webSearch, setWebSearch] = useState(false);
  const [episodes, setEpisodes] = useState(4);
  const [showEpisodesPanel, setShowEpisodesPanel] = useState(false);

  // 场景包
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState('');
  const selectedScenario = scenarios.find(item => item.id === selectedScenarioId);
  // 场景未加载时按旧行为处理（需要视频模型）
  const requiresVideo = selectedScenario ? selectedScenario.requires_video_model : true;
  const showEpisodes = !selectedScenario
    || selectedScenario.category === 'video'
    || selectedScenario.defaults?.episodes !== undefined;
  const scenarioExamples = selectedScenario?.ui?.examples || [];
  // 集数控件文案：场景可改名（如"组数"），带"集"字时沿用原有单位与提示
  const episodesLabel = selectedScenario?.ui?.episodes_label || '剧集';
  const episodesIsSeries = episodesLabel.includes('集');
  const episodesUnit = episodesIsSeries ? ' 集' : '';
  const scenarioById = (id?: string) => scenarios.find(item => item.id === id);
  // 内置画风 + 当前场景自带画风（去重），保证场景默认画风能被选中
  const styleOptions: { id: string; label: string }[] = [
    ...STYLES,
    ...(selectedScenario?.styles || []).filter(st => st?.id && !STYLES.some(b => b.id === st.id)),
  ];

  // 上传相关状态
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadedFile, setUploadedFile] = useState<{name: string, path: string} | null>(null);

  // 管理模式状态
  const [manageMode, setManageMode] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [llmProviders, setLlmProviders] = useState<ProviderGroup[]>([]);
  const [vlmProviders, setVlmProviders] = useState<ProviderGroup[]>([]);
  const [t2iProviders, setT2iProviders] = useState<ProviderGroup[]>([]);
  const [i2iProviders, setI2iProviders] = useState<ProviderGroup[]>([]);
  const [firstFrameVideoProviders, setFirstFrameVideoProviders] = useState<ProviderGroup[]>([]);
  const [startEndVideoProviders, setStartEndVideoProviders] = useState<ProviderGroup[]>([]);
  const [referenceVideoProviders, setReferenceVideoProviders] = useState<ProviderGroup[]>([]);
  const activeVideoModel =
    selectedVideoMode === 'start_end_frame'
      ? selectedStartEndVideo
      : selectedVideoMode === 'reference'
        ? selectedReferenceVideo
        : selectedFirstFrameVideo;
  const modelConfigReady = Boolean(
    selectedLLM && selectedVLM && selectedT2I && selectedI2I && selectedRatio && selectedResolution
    && (!requiresVideo || activeVideoModel)
  );
  const canStart = Boolean((idea.trim() || uploadedFile) && modelConfigReady && !configLoading);

  useEffect(() => {
    let cancelled = false;
    fetchModelGroupsByType('llm')
      .then(groups => { if (!cancelled) setLlmProviders(groups); })
      .catch(() => {});
    fetchModelGroupsByType('vlm')
      .then(groups => { if (!cancelled) setVlmProviders(groups); })
      .catch(() => {});
    fetchModelGroupsByType('t2i')
      .then(groups => { if (!cancelled) setT2iProviders(groups); })
      .catch(() => {});
    fetchModelGroupsByType('i2i')
      .then(groups => { if (!cancelled) setI2iProviders(groups); })
      .catch(() => {});
    fetchVideoModelGroupsByAbility('first_frame_i2v')
      .then(groups => { if (!cancelled) setFirstFrameVideoProviders(groups); })
      .catch(() => {});
    fetchVideoModelGroupsByAbility('start_end_frame_i2v')
      .then(groups => { if (!cancelled) setStartEndVideoProviders(groups); })
      .catch(() => {});
    fetchVideoModelGroupsByAbility('reference_to_video')
      .then(groups => { if (!cancelled) setReferenceVideoProviders(groups); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const loadDefaultConfig = async () => {
      setConfigLoading(true);
      setConfigError('');
      // 场景列表与默认配置并行加载；场景加载失败不阻塞首页（后端会使用默认场景）
      const scenariosPromise = fetchScenarios().catch(() => null);
      try {
        const resp = await fetch('/api/config');
        if (!resp.ok) throw new Error('读取默认模型配置失败');
        const data = await resp.json();
        const models = data.config?.models || {};
        const generation = data.config?.generation || {};
        // Legacy config compatibility: older config.yaml only has models.video, so treat it as first-frame video.
        const firstFrameModel = models.video_first_frame || models.video;
        const startEndModel = models.video_start_end || 'wan2.7-i2v';
        const referenceModel = models.video_reference || 'wan2.7-r2v';
        const videoMode = (generation.video_generation_mode || 'first_frame') as VideoGenerationMode;
        const selectedModel = videoMode === 'start_end_frame' ? startEndModel : videoMode === 'reference' ? referenceModel : firstFrameModel;
        // 视频模型是否必填取决于所选场景，这里只校验各场景共用的模型
        if (!models.llm || !models.vlm || !models.image_t2i || !models.image_it2i) {
          throw new Error('backend/config.yaml 缺少主流程默认模型');
        }
        if (cancelled) return;
        setSelectedStyle(generation.style || 'realistic');
        setSelectedLLM(models.llm);
        setSelectedVLM(models.vlm);
        setSelectedT2I(models.image_t2i);
        setSelectedI2I(models.image_it2i);
        setSelectedVideoMode(videoMode);
        setSelectedFirstFrameVideo(firstFrameModel);
        setSelectedStartEndVideo(startEndModel);
        setSelectedReferenceVideo(referenceModel);
        setSelectedRatio(generation.video_ratio || '16:9');
        setSelectedResolution(generation.video_resolution || '720P');
        void selectedModel;
      } catch (e: unknown) {
        if (!cancelled) setConfigError((e instanceof Error ? e.message : "") || '读取默认模型配置失败');
      } finally {
        const list = await scenariosPromise;
        if (!cancelled && list && list.scenarios.length > 0) {
          setScenarios(list.scenarios);
          const stored = readStoredScenario();
          const initial = list.scenarios.find(item => item.id === stored)
            || list.scenarios.find(item => item.id === list.default)
            || list.scenarios[0];
          setSelectedScenarioId(initial.id);
          applyScenarioDefaults(initial);
        }
        if (!cancelled) setConfigLoading(false);
      }
    };
    loadDefaultConfig();
    return () => { cancelled = true; };
  }, []);

  /* 切换场景时把场景默认参数套用到风格 / 比例 / 分辨率 / 视频方式 / 集数 */
  function applyScenarioDefaults(scenario: Scenario) {
    const d = scenario.defaults || {};
    if (d.style) setSelectedStyle(d.style);
    if (d.video_ratio) setSelectedRatio(d.video_ratio);
    if (d.video_resolution) setSelectedResolution(d.video_resolution);
    if (d.video_generation_mode) setSelectedVideoMode(d.video_generation_mode as VideoGenerationMode);
    if (typeof d.episodes === 'number' && d.episodes > 0) setEpisodes(d.episodes);
  }

  const handleSelectScenario = (scenario: Scenario) => {
    if (scenario.id === selectedScenarioId) return;
    setSelectedScenarioId(scenario.id);
    applyScenarioDefaults(scenario);
    writeStoredScenario(scenario.id);
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    setDeleteError('');
    try {
      await onDeleteSession(deleteTarget);
      setDeleteTarget(null);
    } catch (e: unknown) {
      setDeleteError((e instanceof Error ? e.message : "") || '删除失败');
    } finally {
      setDeleting(false);
    }
  };

  const activeVideoProviders =
    selectedVideoMode === 'start_end_frame'
      ? startEndVideoProviders
      : selectedVideoMode === 'reference'
        ? referenceVideoProviders
        : firstFrameVideoProviders;

  const setActiveVideoModel = (value: string) => {
    if (selectedVideoMode === 'start_end_frame') {
      setSelectedStartEndVideo(value);
    } else if (selectedVideoMode === 'reference') {
      setSelectedReferenceVideo(value);
    } else {
      setSelectedFirstFrameVideo(value);
    }
  };

  const selectedVideoModeLabel = VIDEO_GENERATION_MODES.find(item => item.id === selectedVideoMode)?.label || '首帧生视频';

  const handleStart = (auto?: boolean) => {
    if (!canStart) return;
    onStartProject({
      scenario: selectedScenario?.id,
      idea,
      file_path: uploadedFile?.path, // 如果上传了文件，传给后端
      style: selectedStyle,
      video_ratio: selectedRatio,
      video_resolution: selectedResolution,
      llm_model: selectedLLM,
      vlm_model: selectedVLM,
      image_t2i_model: selectedT2I,
      image_it2i_model: selectedI2I,
      video_generation_mode: selectedVideoMode,
      video_first_frame_model: selectedFirstFrameVideo,
      video_start_end_model: selectedStartEndVideo,
      video_reference_model: selectedReferenceVideo,
      video_model: activeVideoModel,
      enable_concurrency: enableConcurrency,
      web_search: webSearch,
      // 不展示集数控件的场景交给后端按场景默认值处理
      episodes: showEpisodes ? episodes : undefined,
    }, auto);
  };

  const handleExampleClick = (text: string) => {
    setIdea(text);
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const allowedExtensions = ['.doc', '.docx', '.txt', '.md', '.pdf'];
    const extension = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
    
    if (!allowedExtensions.includes(extension)) {
      alert(`仅支持 ${allowedExtensions.join(', ')} 格式的文件`);
      return;
    }

    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch('/api/upload_file', {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        throw new Error('文件上传失败');
      }

      const data = await response.json();
      if (data.file_path) {
        // 记录已上传的文件信息，不修改输入框
        setUploadedFile({
          name: file.name,
          path: data.file_path
        });
      }
    } catch (error) {
      console.error('上传错误:', error);
      alert('上传提取内容失败，请重试');
    } finally {
      setUploading(false);
      // 清空 input 方便下次选择同一文件
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  return (
    <div className="sfa-home h-full flex flex-col items-center overflow-y-auto bg-gray-50/50">
      {/* 主区域 - 居中 */}
      <div className="sfa-home-main w-full max-w-6xl px-6 pt-16 pb-8 flex-shrink-0">
        {/* 标题 */}
        <div className="sfa-hero-title text-center mb-10">
          <div className="inline-flex items-center gap-2 mb-3">
            <h1 className="text-2xl font-medium text-white">{selectedScenario?.ui?.hero_title || DEFAULT_HERO_TITLE}</h1>
          </div>
          <p className="text-sm text-white/75">
            {selectedScenario?.ui?.hero_subtitle || selectedScenario?.tagline || DEFAULT_HERO_SUBTITLE}
          </p>
        </div>

        {/* 场景选择 */}
        {scenarios.length > 1 && (
          <div className="sfa-scenario-picker" role="tablist" aria-label="创作场景">
            {scenarios.map(item => {
              const active = item.id === selectedScenarioId;
              const isImage = item.category === 'image';
              return (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => handleSelectScenario(item)}
                  className={clsx('sfa-scenario-tab', active && 'sfa-scenario-tab-active')}
                  title={item.description || item.tagline}
                >
                  <span className="sfa-scenario-tab-head">
                    <span className="sfa-scenario-tab-name">{item.name}</span>
                    <span className="sfa-scenario-badge">
                      {isImage ? <ImageIcon className="w-3 h-3" /> : <Film className="w-3 h-3" />}
                      {isImage ? '图片' : '视频'}
                    </span>
                  </span>
                  {item.tagline && <span className="sfa-scenario-tab-tagline">{item.tagline}</span>}
                </button>
              );
            })}
          </div>
        )}

        {/* 输入区域 */}
        <div className="sfa-composer bg-white rounded-2xl shadow-sm border border-gray-200 p-5 mb-6">
          <textarea
            value={idea}
            onChange={e => setIdea(e.target.value)}
            placeholder={selectedScenario?.ui?.placeholder || DEFAULT_PLACEHOLDER}
            className="sfa-prompt-input w-full bg-transparent text-sm text-gray-800 placeholder-gray-400 resize-none outline-none min-h-[100px]"
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey && (idea.trim() || uploadedFile)) {
                e.preventDefault();
                handleStart(false);
              }
            }}
          />

          <div className="sfa-composer-toolbar flex items-center justify-between mt-3 pt-3 border-t border-gray-100">
            <div className="flex items-center gap-3">
              {showEpisodes && (
              <div className="relative">
                <button
                  onClick={() => setShowEpisodesPanel(!showEpisodesPanel)}
                  className={clsx(
                    'sfa-tool-button flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
                    showEpisodesPanel
                      ? 'bg-black/5 text-neutral-900'
                      : 'text-gray-400 hover:text-gray-600 hover:bg-gray-50'
                  )}
                >
                  <ListOrdered className="w-3.5 h-3.5" />
                  {episodesLabel}：{episodes}{episodesUnit}
                </button>

                {showEpisodesPanel && (
                  <>
                    <div 
                      className="fixed inset-0 z-10" 
                      onClick={() => setShowEpisodesPanel(false)}
                    />
                    <div className="sfa-episodes-popover absolute bottom-full left-0 mb-2 w-48 bg-white rounded-xl shadow-xl border border-gray-100 p-4 z-20 animate-in fade-in slide-in-from-bottom-2">
                      <div className="flex flex-col gap-3">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-semibold text-gray-700">{episodesIsSeries ? '设置总集数' : `设置${episodesLabel}`}</span>
                          <span className="sfa-episode-count text-[10px] text-neutral-900 font-bold bg-black/5 px-1.5 py-0.5 rounded-full">
                            {episodes}{episodesUnit}
                          </span>
                        </div>
                        
                        <div className="flex items-center gap-2">
                          <button 
                            onClick={(e) => { e.stopPropagation(); setEpisodes(Math.max(1, episodes - 1)); }}
                            className="w-7 h-7 flex items-center justify-center rounded-lg bg-gray-50 text-gray-600 hover:bg-gray-100 active:scale-95 transition-all text-sm font-bold"
                          >
                            -
                          </button>
                          <input
                            type="range"
                            min={1}
                            max={10}
                            value={episodes}
                            onChange={(e) => setEpisodes(parseInt(e.target.value))}
                            className="flex-1 h-1.5 bg-gray-100 rounded-lg appearance-none cursor-pointer accent-neutral-900"
                          />
                          <button 
                            onClick={(e) => { e.stopPropagation(); setEpisodes(Math.min(10, episodes + 1)); }}
                            className="w-7 h-7 flex items-center justify-center rounded-lg bg-gray-50 text-gray-600 hover:bg-gray-100 active:scale-95 transition-all text-sm font-bold"
                          >
                            +
                          </button>
                        </div>

                        {episodesIsSeries && (
                        <div className="space-y-1 border-t border-gray-50 pt-2">
                          <p className="text-[10px] text-gray-400 leading-tight">
                            每集预估时长约 1–2 分钟
                          </p>
                          <p className="text-[10px] text-neutral-400/80 leading-tight">
                            推荐设置 4–6 集
                          </p>
                        </div>
                        )}
                      </div>
                    </div>
                  </>
                )}
              </div>
              )}

              <button
                onClick={() => setShowSettings(!showSettings)}
                className={clsx(
                  'sfa-tool-button flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
                  showSettings
                    ? 'bg-black/5 text-neutral-900'
                    : 'text-gray-400 hover:text-gray-600 hover:bg-gray-50'
                )}
              >
                <Settings2 className="w-3.5 h-3.5" />
                生成配置
              </button>
              <button
                onClick={() => setWebSearch(!webSearch)}
                className={clsx(
                  'sfa-tool-button flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
                  webSearch
                    ? 'bg-black/5 text-neutral-900'
                    : 'text-gray-400 hover:text-gray-600 hover:bg-gray-50'
                )}
              >
                <Globe className="w-3.5 h-3.5" />
                联网搜索
              </button>
            </div>
            <div className="flex items-center gap-2">
              {/* 隐藏的文件输入框 */}
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleFileUpload}
                accept=".doc,.docx,.txt,.md,.pdf"
                className="hidden"
              />
              <button
                onClick={() => {
                  if (uploadedFile) {
                    setUploadedFile(null); // 已有文件则点击取消
                  } else {
                    fileInputRef.current?.click();
                  }
                }}
                disabled={uploading}
                className={clsx(
                  'sfa-upload-button flex items-center gap-2 px-5 py-2 rounded-xl text-sm font-medium transition-colors border shadow-sm relative',
                  uploading
                    ? 'bg-gray-50 text-gray-400 cursor-not-allowed border-gray-100'
                    : uploadedFile
                    ? 'bg-black/5 text-neutral-900 border-black/10 hover:bg-black/10'
                    : 'bg-white text-gray-600 hover:bg-gray-50 border-gray-200'
                )}
                title={uploadedFile ? `已选择: ${uploadedFile.name} (点击取消)` : "上传文档 (Word/TXT/MD)"}
              >
                {uploading ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : uploadedFile ? (
                  <CheckCircle className="w-4 h-4" />
                ) : null}
                {uploading ? '上传中……' : uploadedFile ? `已选：${uploadedFile.name.length > 8 ? `${uploadedFile.name.substring(0, 8)}…` : uploadedFile.name}` : '上传文件'}
              </button>
              <button
                onClick={() => handleStart(false)}
                disabled={!canStart}
                className={clsx(
                  'sfa-action-secondary flex items-center gap-2 px-5 py-2 rounded-xl text-sm font-medium transition-colors',
                  canStart
                    ? 'bg-white text-gray-900 hover:bg-gray-50 border border-gray-300'
                    : 'bg-gray-100 text-gray-400 cursor-not-allowed'
                )}
              >
                逐步创作
              </button>
              <button
                onClick={() => handleStart(true)}
                disabled={!canStart}
                className={clsx(
                  'sfa-action-primary flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-colors',
                  canStart
                    ? 'bg-black text-white hover:bg-gray-800 shadow-sm'
                    : 'bg-gray-100 text-gray-400 cursor-not-allowed'
                )}
                title={`自动执行全部 ${selectedScenario?.stages.length || ''} 个阶段，无需手动确认`.replace('  ', ' ')}
              >
                一键生成
              </button>
            </div>
          </div>
          {(configLoading || configError) && (
            <div className={clsx('mt-3 text-xs', configError ? 'text-red-500' : 'text-gray-400')}>
              {configError || '正在读取默认模型……'}
            </div>
          )}
          {!configLoading && !configError && requiresVideo && !activeVideoModel && (
            <div className="mt-3 text-xs text-red-500">当前场景需要视频模型，请在「生成配置」中选择</div>
          )}

          {/* 模型设置折叠面板 */}
          {showSettings && (
            <div className="sfa-generation-panel mt-4 p-4 bg-gray-50 rounded-xl space-y-4 text-xs">
              <div className="grid grid-cols-1 gap-3">
                <label className="flex flex-col gap-1">
                  <span className="text-gray-500 font-medium">风格</span>
                  <select
                    value={selectedStyle}
                    onChange={e => setSelectedStyle(e.target.value)}
                    className="bg-white border border-gray-200 rounded-lg px-2.5 py-2 text-gray-700 outline-none"
                  >
                    {styleOptions.map(s => (
                      <option key={s.id} value={s.id}>{s.label}</option>
                    ))}
                  </select>
                </label>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <label className="flex flex-col gap-1">
                  <span className="text-gray-500 font-medium">{requiresVideo ? '视频分辨率' : '分辨率'}</span>
                  <select
                    value={selectedResolution}
                    onChange={e => setSelectedResolution(e.target.value)}
                    className="bg-white border border-gray-200 rounded-lg px-2.5 py-2 text-gray-700 outline-none min-h-[40px]"
                  >
                    {VIDEO_RESOLUTIONS.map(item => (
                      <option key={item.id} value={item.id}>{item.label}</option>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-gray-500 font-medium">{requiresVideo ? '视频长宽比' : '画面比例'}</span>
                  <div className="flex gap-1">
                    {VIDEO_RATIOS.map(r => (
                      <button
                        key={r.id}
                        onClick={() => setSelectedRatio(r.id)}
                        className={`flex flex-col items-center gap-1 p-2 rounded-lg border transition-all ${
                          selectedRatio === r.id
                            ? 'border-neutral-900 bg-black/5'
                            : 'border-gray-200 hover:border-gray-300'
                        }`}
                        title={r.label}
                      >
                        <div
                          className="bg-gray-700 rounded-sm"
                          style={{
                            width: r.ratio === '16:9' ? '32px' :
                                   r.ratio === '9:16' ? '18px' :
                                   r.ratio === '1:1' ? '24px' :
                                   r.ratio === '4:3' ? '28px' :
                                   r.ratio === '3:4' ? '20px' :
                                   '36px',
                            height: r.ratio === '16:9' ? '18px' :
                                   r.ratio === '9:16' ? '32px' :
                                   r.ratio === '1:1' ? '24px' :
                                   r.ratio === '4:3' ? '21px' :
                                   r.ratio === '3:4' ? '28px' :
                                   '15px',
                          }}
                        />
                        <span className="text-[10px] text-gray-500">{r.label}</span>
                      </button>
                    ))}
                  </div>
                </label>
              </div>

              <div className="space-y-3 border-t border-gray-200/70 pt-4">
                <div className="flex items-center justify-between">
                  <span className="text-gray-500 font-semibold">模型配置</span>
                  <span className="text-[10px] text-gray-400">用于主流程各阶段调用</span>
                </div>
                <div className="grid grid-cols-2 gap-3">
                <label className="flex flex-col gap-1">
                  <span className="text-gray-500 font-medium">LLM 模型</span>
                  <select
                    value={selectedLLM}
                    onChange={e => setSelectedLLM(e.target.value)}
                    className="bg-white border border-gray-200 rounded-lg px-2.5 py-2 text-gray-700 outline-none"
                  >
                    {llmProviders.map(pg => (
                      <optgroup key={pg.provider} label={pg.label}>
                        {pg.models.map(m => (
                          <option key={m.id} value={m.id}>{m.label}</option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-gray-500 font-medium">VLM 评估模型</span>
                  <select
                    value={selectedVLM}
                    onChange={e => setSelectedVLM(e.target.value)}
                    className="bg-white border border-gray-200 rounded-lg px-2.5 py-2 text-gray-700 outline-none"
                  >
                    {vlmProviders.map(pg => (
                      <optgroup key={pg.provider} label={pg.label}>
                        {pg.models.map(m => (
                          <option key={m.id} value={m.id}>{m.label}</option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-gray-500 font-medium">文生图</span>
                  <select
                    value={selectedT2I}
                    onChange={e => setSelectedT2I(e.target.value)}
                    className="bg-white border border-gray-200 rounded-lg px-2.5 py-2 text-gray-700 outline-none"
                  >
                    {t2iProviders.map(pg => (
                      <optgroup key={pg.provider} label={pg.label}>
                        {pg.models.map(m => (
                          <option key={m.id} value={m.id}>{m.label}</option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-gray-500 font-medium">图生图</span>
                  <select
                    value={selectedI2I}
                    onChange={e => setSelectedI2I(e.target.value)}
                    className="bg-white border border-gray-200 rounded-lg px-2.5 py-2 text-gray-700 outline-none"
                  >
                    {i2iProviders.map(pg => (
                      <optgroup key={pg.provider} label={pg.label}>
                        {pg.models.map(m => (
                          <option key={m.id} value={m.id}>{m.label}</option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                </label>
                {requiresVideo && (<>
                <label className="flex flex-col gap-1 col-span-2">
                  <span className="text-gray-500 font-medium">视频生成方式</span>
                  <select
                    value={selectedVideoMode}
                    onChange={e => setSelectedVideoMode(e.target.value as VideoGenerationMode)}
                    className="bg-white border border-gray-200 rounded-lg px-2.5 py-2 text-gray-700 outline-none"
                  >
                    {VIDEO_GENERATION_MODES.map(item => (
                      <option key={item.id} value={item.id}>{item.label}</option>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1 col-span-2">
                  <span className="text-gray-500 font-medium">{selectedVideoModeLabel}模型</span>
                  <select
                    value={activeVideoModel}
                    onChange={e => setActiveVideoModel(e.target.value)}
                    className="bg-white border border-gray-200 rounded-lg px-2.5 py-2 text-gray-700 outline-none"
                  >
                    {activeVideoProviders.map(pg => (
                      <optgroup key={pg.provider} label={pg.label}>
                        {pg.models.map(m => (
                          <option key={m.id} value={m.id}>{m.label}</option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                </label>
                </>)}
                <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={enableConcurrency}
                    onChange={e => setEnableConcurrency(e.target.checked)}
                    className="w-4 h-4 rounded border-gray-300 text-neutral-900 focus:ring-neutral-900/30"
                  />
                  <span className="text-gray-600">并发生成</span>
                </label>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* 示例卡片：来自当前场景的 ui.examples */}
        {scenarioExamples.length > 0 && (
        <div className="sfa-inspiration mb-10">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">
            灵感示例
          </h3>
          <div className="sfa-inspiration-grid grid grid-cols-2 md:grid-cols-3 gap-2.5">
            {scenarioExamples.map((ex, idx) => (
              <button
                key={`${selectedScenarioId}-${idx}`}
                onClick={() => handleExampleClick(ex.idea)}
                className="sfa-inspiration-card text-left bg-white rounded-xl border border-gray-200 hover:shadow-sm transition-all group"
              >
                {ex.image ? (
                  <div
                    className="sfa-inspiration-media"
                    style={{ backgroundImage: `url(${JSON.stringify(ex.image)})` }}
                  />
                ) : (
                  <div className="sfa-inspiration-media sfa-inspiration-media-placeholder" aria-hidden="true">
                    {selectedScenario?.category === 'image'
                      ? <ImageIcon className="w-6 h-6" />
                      : <Film className="w-6 h-6" />}
                  </div>
                )}
                <div className="sfa-inspiration-copy">
                  <div className="text-sm font-medium text-white transition-colors mb-1">
                    {ex.title}
                  </div>
                  <div className="text-xs text-white/70 line-clamp-2">
                    {ex.description || ex.idea}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
        )}
      </div>

      {/* 历史记录区域 */}
      {history.length > 0 && (
        <div className="sfa-history w-full max-w-6xl px-6 pb-12 flex-shrink-0">
          <div className="flex items-center gap-2 mb-4">
            <Clock className="w-4 h-4 text-gray-400" />
            <h3 className="text-sm font-medium text-gray-600">历史记录</h3>
            <button
              onClick={() => setManageMode(m => !m)}
              className={`ml-auto text-xs px-2 py-0.5 rounded transition-colors ${
                manageMode ? 'bg-red-100 text-red-600' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
              }`}
            >
              {manageMode ? '完成' : '管理'}
            </button>
          </div>
          <div className="max-h-[60vh] overflow-y-auto pr-1">
            <div className="grid grid-cols-2 gap-3">
              {history.map(item => {
                const itemScenario = scenarioById(item.scenario);
                const progress = stageProgressLabel(item, itemScenario);
                return (
                <div key={item.id} className="relative group">
                  <div
                    onClick={() => !manageMode && onResumeProject(item.id)}
                    className={`sfa-history-card w-full text-left p-4 bg-white rounded-xl border border-gray-200 hover:shadow-sm transition-all ${!manageMode ? 'cursor-pointer' : ''}`}
                  >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-gray-700 group-hover:text-neutral-700 transition-colors truncate">
                        {item.idea}
                      </div>
                      <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                        {itemScenario && scenarios.length > 1 && (
                          <span className="text-[10px] bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded">
                            {itemScenario.name}
                          </span>
                        )}
                        {item.style && (
                          <span className="text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">
                            {item.style}
                          </span>
                        )}
                        <span className="text-[10px] text-gray-400">{item.date}</span>
                      </div>
                      <div className={`flex items-center gap-1 mt-1.5 text-[10px] font-medium ${progress.color}`}>
                        {isSessionDone(item) ? (
                          <CheckCircle className="w-3 h-3" />
                        ) : (
                          <span className="w-1.5 h-1.5 rounded-full bg-current flex-shrink-0" />
                        )}
                        <span>{progress.text}</span>
                      </div>
                    </div>
                    {manageMode ? (
                      <button
                        onClick={(e) => { e.stopPropagation(); setDeleteTarget(item.id); setDeleteError(''); }}
                        className="w-6 h-6 rounded-full bg-red-500 text-white flex items-center justify-center hover:bg-red-600 transition-colors flex-shrink-0 mt-0.5"
                        title="删除"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    ) : (
                      <ArrowRight className="w-4 h-4 text-gray-300 group-hover:text-neutral-400 transition-colors flex-shrink-0 mt-0.5" />
                    )}
                  </div>
                </div>
                </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* 删除确认弹窗 */}
      {deleteTarget && (
        <div className="sfa-dialog-scrim fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="sfa-delete-dialog bg-white rounded-2xl shadow-xl w-80 p-6 relative" role="dialog" aria-modal="true" aria-labelledby="delete-dialog-title">
            <div className="flex items-center gap-2 mb-4">
              <Trash2 className="w-4 h-4 text-red-500" />
              <h4 id="delete-dialog-title" className="text-sm font-semibold text-gray-700">删除项目</h4>
            </div>
            <p className="text-xs text-gray-500 mb-6">确认删除这个项目吗？此操作不可撤销。</p>
            {deleteError && <p className="text-xs text-red-500 mb-2">{deleteError}</p>}
            <div className="flex gap-2">
              <button
                onClick={() => { setDeleteTarget(null); setDeleteError(''); }}
                className="flex-1 text-sm py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
              >
                取消
              </button>
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="flex-1 text-sm py-1.5 rounded-lg bg-red-500 text-white hover:bg-red-600 disabled:opacity-50"
              >
                {deleting ? '删除中…' : '确认删除'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
