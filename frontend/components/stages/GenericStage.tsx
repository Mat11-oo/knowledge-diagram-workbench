'use client';

import React, { useMemo } from 'react';
import { FileJson } from 'lucide-react';
import type { StageViewProps } from './types';
import type { StageDef } from '@/lib/workflowApi';
import StageProgress from './StageProgress';
import StageActions from './StageActions';

interface GenericStageProps extends StageViewProps {
  /** 场景包中声明的阶段定义（自定义阶段） */
  stage?: StageDef;
}

function formatArtifact(artifact: unknown): string {
  if (artifact === null || artifact === undefined) return '';
  if (typeof artifact === 'string') return artifact;
  try {
    return JSON.stringify(artifact, null, 2);
  } catch {
    return String(artifact);
  }
}

/**
 * 通用阶段视图：用于场景包中的自定义阶段（custom: true）。
 * 产物是任意 JSON，这里以格式化文本展示，并提供常规的运行 / 确认操作。
 */
export default function GenericStage({
  stage,
  state,
  onConfirm,
  onRegenerate,
  showConfirm,
  isRunning,
  hasNextStageStarted,
}: GenericStageProps) {
  const artifactText = useMemo(() => formatArtifact(state.artifact), [state.artifact]);
  const hasArtifact = artifactText.trim().length > 0;
  const title = stage?.name || stage?.id || '自定义阶段';

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 min-w-0 overflow-y-auto p-4 sm:p-6">
        <h2 className="text-lg font-semibold text-gray-800 mb-1">{title}</h2>
        <p className="text-sm text-gray-500 mb-6">{stage?.description || '场景自定义阶段'}</p>

        {state.status === 'running' && (
          <StageProgress message={state.progressMessage} fallback="正在执行..." progress={state.progress} />
        )}

        {state.error && (
          <div className="text-sm text-red-600 bg-red-50 border border-red-200 p-4 rounded-xl mb-4 whitespace-pre-wrap break-words">
            {state.error}
          </div>
        )}

        {hasArtifact && (
          <div className="sfa-generic-artifact rounded-xl border border-gray-200 bg-white overflow-hidden">
            <div className="flex items-center gap-2 px-4 py-2.5 border-b border-gray-100 text-xs font-medium text-gray-500">
              <FileJson className="w-3.5 h-3.5" />
              阶段产物
            </div>
            <pre className="px-4 py-3 text-xs leading-relaxed text-gray-800 font-mono whitespace-pre-wrap break-words max-h-[65vh] overflow-auto">
              {artifactText}
            </pre>
          </div>
        )}

        {!hasArtifact && (state.status === 'completed' || state.status === 'waiting') && (
          <div className="flex flex-col items-center justify-center py-20 text-gray-400">
            <FileJson className="w-12 h-12 mb-3" />
            <div className="text-sm">该阶段已完成，暂无产物数据</div>
          </div>
        )}

        {state.status === 'pending' && !hasArtifact && (
          <div className="text-center text-gray-400 text-sm py-20">等待上一阶段完成...</div>
        )}
      </div>

      <StageActions
        status={state.status}
        onConfirm={onConfirm}
        showConfirm={showConfirm}
        onRegenerate={onRegenerate}
        stageId={stage?.id}
        stageType="custom"
        hasNextStageStarted={hasNextStageStarted}
        isRunning={isRunning}
      />
    </div>
  );
}
