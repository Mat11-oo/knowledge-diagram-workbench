# -*- coding: utf-8 -*-
"""
工作流阶段注册表

所有阶段的 id、顺序、展示信息和默认 Agent 都在这里声明。
可在 config.yaml 的 workflow.agents 中按阶段替换 Agent 实现，例如：

    workflow:
      agents:
        script_generation: my_plugins.script:MyScriptAgent

替换的 Agent 需继承 core.agents.base_agent.AgentInterface，并保持该阶段的 payload 结构。
"""

import importlib
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Mapping, Optional, Type

from core.agents import (
    CharacterDesignerAgent,
    ReferenceGeneratorAgent,
    ScriptWriterAgent,
    StoryboardAgent,
    VideoDirectorAgent,
    VideoEditorAgent,
)
from core.agents.base_agent import AgentInterface

logger = logging.getLogger(__name__)


class WorkflowStage(str, Enum):
    """工作流阶段"""
    INIT = "init"
    SCRIPT_GENERATION = "script_generation"
    CHARACTER_DESIGN = "character_design"
    STORYBOARD = "storyboard"
    REFERENCE_GENERATION = "reference_generation"
    VIDEO_GENERATION = "video_generation"
    POST_PRODUCTION = "post_production"
    COMPLETED = "completed"


@dataclass(frozen=True)
class StageSpec:
    stage: WorkflowStage
    name: str
    description: str
    agent: Type[AgentInterface]

    @property
    def id(self) -> str:
        return self.stage.value


STAGE_SPECS: List[StageSpec] = [
    StageSpec(WorkflowStage.SCRIPT_GENERATION, "剧本生成", "将灵感转化为结构化剧本", ScriptWriterAgent),
    StageSpec(WorkflowStage.CHARACTER_DESIGN, "角色/场景设计", "生成角色设计图和场景背景", CharacterDesignerAgent),
    StageSpec(WorkflowStage.STORYBOARD, "分镜设计", "设计镜头语言和分镜脚本", StoryboardAgent),
    StageSpec(WorkflowStage.REFERENCE_GENERATION, "参考图生成", "生成高精度参考图", ReferenceGeneratorAgent),
    StageSpec(WorkflowStage.VIDEO_GENERATION, "视频生成", "将参考图/分镜图生成视频", VideoDirectorAgent),
    StageSpec(WorkflowStage.POST_PRODUCTION, "后期剪辑", "拼接视频片段为最终成片", VideoEditorAgent),
]

STAGE_ORDER: List[WorkflowStage] = [spec.stage for spec in STAGE_SPECS]


def load_agent_class(path: str) -> Type[AgentInterface]:
    """Import an agent class from a "package.module:ClassName" path."""
    module_name, sep, class_name = path.partition(":")
    if not sep or not module_name or not class_name:
        raise ValueError(f"Agent path must look like 'package.module:ClassName', got {path!r}")
    agent_cls = getattr(importlib.import_module(module_name), class_name)
    if not isinstance(agent_cls, type) or not issubclass(agent_cls, AgentInterface):
        raise TypeError(f"{path} is not an AgentInterface subclass")
    return agent_cls


def build_agent_factories(overrides: Optional[Mapping[str, str]] = None) -> Dict[WorkflowStage, Type[AgentInterface]]:
    """Map each stage to its agent class, applying workflow.agents overrides."""
    factories = {spec.stage: spec.agent for spec in STAGE_SPECS}
    for stage_id, path in (overrides or {}).items():
        try:
            stage = WorkflowStage(stage_id)
        except ValueError:
            raise ValueError(f"Unknown workflow stage in workflow.agents: {stage_id!r}") from None
        if stage not in factories:
            raise ValueError(f"Stage {stage_id!r} has no agent to replace")
        factories[stage] = load_agent_class(path)
        logger.info("Stage %s uses custom agent %s", stage_id, path)
    return factories


def stage_catalog() -> List[Dict[str, object]]:
    """Public stage list served by /api/stages."""
    return [
        {"id": spec.id, "name": spec.name, "order": index, "description": spec.description}
        for index, spec in enumerate(STAGE_SPECS, start=1)
    ]
