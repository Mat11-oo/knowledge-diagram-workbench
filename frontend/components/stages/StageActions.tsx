'use client';

import React, { useState, useCallback } from 'react';
import { CheckCircle, Edit3, Save, RefreshCw, Check, Loader2, Play } from 'lucide-react';
import type { StageStatus } from './types';

// 按阶段类型（内置阶段 type 与 id 相同；自定义阶段为 "custom"）决定按钮行为。
// 逐项生成、支持"继续生成"的阶段类型
const CONTINUE_STAGE_TYPES = ['character_design', 'storyboard', 'reference_generation', 'video_generation'];
// 整体"重新生成"、需要提示后续阶段是否已开始的阶段类型（自定义阶段同样整体重跑）
const REGEN_STAGE_TYPES = ['script_generation', 'custom'];
// completed 状态下仍允许再次生成的阶段类型
const ALWAYS_REGEN_STAGE_TYPES = ['script_generation', 'post_production', 'custom'];

interface StageActionsProps {
  status: StageStatus;
  onConfirm: () => void;
  onEdit?: () => void;
  onSave?: () => void;
  onSaveSelections?: () => Promise<void>;
  onRegenerate?: () => void;
  /** 阶段ID */
  stageId?: string;
  /** 阶段类型（内置阶段类型 id 或 "custom"），缺省时与 stageId 相同 */
  stageType?: string;
  /** 是否有待生成的项（用于阶段2、3、4、5） */
  hasPendingItems?: boolean;
  /** 后续阶段是否已开始（用于阶段1） */
  hasNextStageStarted?: boolean;
  /** 是否显示"确认并继续"按钮（后续阶段已执行过时隐藏） */
  showConfirm?: boolean;
  isRunning: boolean;
}

export default function StageActions({
  status,
  onConfirm,
  onEdit,
  onSave,
  onSaveSelections,
  onRegenerate,
  stageId = '',
  stageType,
  hasPendingItems = true,
  hasNextStageStarted = false,
  showConfirm = true,
  isRunning
}: StageActionsProps) {
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved'>('idle');

  const type = stageType || stageId;
  // 是否是"继续生成"阶段（角色、分镜、参考图、视频）
  const isContinueStage = CONTINUE_STAGE_TYPES.includes(type);
  // 是否是"重新生成"阶段（剧本、自定义阶段）
  const isRegenStage = REGEN_STAGE_TYPES.includes(type);

  // 重新生成/继续生成按钮：在 != 'running' 状态下显示 (pending时也不会到这个组件)
  const showRegen = !!onRegenerate && status !== 'running';
  
  // 按钮是否禁用逻辑
  let isButtonDisabled = isRunning;
  if (!isRunning && type) {
    // 除剧本、后期与自定义阶段外，completed 状态下禁用继续生成
    if (!ALWAYS_REGEN_STAGE_TYPES.includes(type) && status === 'completed') {
      isButtonDisabled = true;
    }
  }

  // 其余按钮在 waiting、running、completed、stopped 状态显示
  const showActions = status === 'waiting' || status === 'running' || status === 'completed' || status === 'stopped';
  // 保存选项：在 waiting、completed 和 stopped 状态下都显示
  const showSaveSelections = onSaveSelections && (status === 'waiting' || status === 'completed' || status === 'stopped');
  // "确认并继续"在 showConfirm=true 且 waiting/running/completed 时显示（stopped 状态不显示确认）
  const showConfirmBtn = showConfirm && (status === 'waiting' || status === 'running' || status === 'completed');

  const handleSaveClick = useCallback(async () => {
    if (!onSaveSelections || saveState !== 'idle') return;
    setSaveState('saving');
    try {
      await onSaveSelections();
      setSaveState('saved');
      setTimeout(() => setSaveState('idle'), 1500);
    } catch {
      setSaveState('idle');
    }
  }, [onSaveSelections, saveState]);

  if (!showRegen && !showActions && !showSaveSelections) return null;

  return (
    <div className="border-t border-gray-200 bg-white px-4 sm:px-6 py-4 flex flex-wrap items-center justify-between gap-3 flex-shrink-0">
      {/* 左侧：重新生成/继续生成按钮 */}
      <div>
        {showRegen && (
          <button
            onClick={onRegenerate}
            disabled={isButtonDisabled}
            className="flex items-center gap-2 px-4 py-2 bg-white border border-orange-300 text-orange-600 rounded-lg text-sm font-medium hover:bg-orange-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            title={isButtonDisabled ? (status === 'error' ? '重新尝试生成' : (isContinueStage && !hasPendingItems ? '所有项已生成完毕' : (isRegenStage && hasNextStageStarted ? '后续阶段已开始，无法重新生成' : ''))) : ''}
          >
            {isContinueStage ? <Play className="w-4 h-4" /> : <RefreshCw className="w-4 h-4" />}
            {isContinueStage ? '继续生成' : '重新生成'}
          </button>
        )}
      </div>

      {/* 右侧：操作按钮组 */}
      <div className="flex flex-wrap items-center justify-end gap-3">
        {showActions && onEdit && (
          <button
            onClick={onEdit}
            disabled={isRunning}
            className="flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors disabled:opacity-50"
          >
            <Edit3 className="w-4 h-4" />
            修改
          </button>
        )}
        
        {showActions && onSave && (
          <button
            onClick={onSave}
            disabled={isRunning}
            className="flex items-center gap-2 px-4 py-2 bg-white border border-neutral-300 text-neutral-900 rounded-lg text-sm font-medium hover:bg-black/5 transition-colors disabled:opacity-50"
          >
            <Save className="w-4 h-4" />
            保存
          </button>
        )}

        {showSaveSelections && (
          <button
            onClick={handleSaveClick}
            disabled={saveState !== 'idle' || isRunning}
            className="flex items-center gap-2 px-4 py-2 bg-white border border-neutral-900 text-neutral-900 rounded-lg text-sm font-medium hover:bg-black/5 transition-colors disabled:opacity-50 min-w-[120px] justify-center"
          >
            {saveState === 'saving' ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : saveState === 'saved' ? (
              <Check className="w-4 h-4 text-green-600" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            {saveState === 'saving' ? '正在保存...' : saveState === 'saved' ? '保存成功' : '保存选择'}
          </button>
        )}
        
        {showConfirmBtn && (
          <button
            onClick={onConfirm}
            disabled={isRunning}
            className="flex items-center gap-2 px-6 py-2 bg-neutral-900 text-white rounded-lg text-sm font-medium hover:bg-neutral-700 transition-colors disabled:opacity-50 disabled:bg-neutral-300"
          >
            <CheckCircle className="w-4 h-4" />
            确认并继续
          </button>
        )}
      </div>
    </div>
  );
}
