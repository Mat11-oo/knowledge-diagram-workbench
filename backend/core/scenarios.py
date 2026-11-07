# -*- coding: utf-8 -*-
"""
场景包注册表

一个场景包 = backend/scenarios/<场景 id>/ 目录，包含：

    scenario.yaml     场景声明：名称、阶段组成、默认参数、界面文案
    prompts/          可选，覆盖默认提示词（目录结构与 backend/prompts/ 相同）
    agents.py         可选，场景自定义的阶段 Agent

scenario.yaml 中的 stages 决定这个场景有哪些阶段、按什么顺序执行：
    - 内置阶段写 type（script_generation / character_design / storyboard /
      reference_generation / video_generation / post_production），可改名称和说明；
    - 自定义阶段写 id + agent（"scenarios.<场景 id>.agents:ClassName"），
      前端会用通用视图展示它的产物。

字段说明见 docs/scenarios.md。
"""

import logging
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

import yaml

from core.agents.base_agent import AgentInterface
from core.stages import STAGE_SPECS, load_agent_class

logger = logging.getLogger(__name__)

SCENARIOS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scenarios")
DEFAULT_SCENARIO_ID = "short_film"
SCENARIO_FILE = "scenario.yaml"

BUILTIN_STAGES = {spec.id: spec for spec in STAGE_SPECS}
SAFE_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

# 会话级默认参数中允许由场景设置的字段
DEFAULT_KEYS = (
    "style",
    "video_ratio",
    "video_resolution",
    "video_generation_mode",
    "episodes",
    "expand_idea",
)

# 每种内置阶段需要的模型字段；视频模型按 video_generation_mode 单独校验
STAGE_MODEL_FIELDS = {
    "script_generation": ("llm_model",),
    "character_design": ("image_t2i_model", "vlm_model"),
    "storyboard": ("llm_model",),
    "reference_generation": ("image_it2i_model", "vlm_model"),
    "video_generation": (),
    "post_production": (),
}


# 内置阶段读取的上游产物：这些阶段必须排在它前面（否则 Agent 拿不到输入）
STAGE_REQUIRES = {
    "character_design": ("script_generation",),
    "storyboard": ("script_generation",),
    "reference_generation": ("storyboard",),
    "video_generation": ("reference_generation",),
    "post_production": ("video_generation",),
}


class ScenarioError(ValueError):
    """场景包声明不合法。"""


@dataclass(frozen=True)
class ScenarioStage:
    id: str
    type: str                     # 内置阶段类型 id；自定义阶段为 "custom"
    name: str
    short_name: str
    description: str
    agent: Optional[str] = None   # "module:Class"，替换或实现该阶段的 Agent
    options: Dict[str, Any] = field(default_factory=dict)  # 传给 Agent 的场景级参数（agent.stage_options）

    @property
    def builtin(self) -> bool:
        return self.type in BUILTIN_STAGES

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "short_name": self.short_name,
            "description": self.description,
            "custom": not self.builtin,
            "options": dict(self.options),
        }


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    tagline: str
    description: str
    category: str                 # video / image，前端用于分组展示
    order: int
    stages: List[ScenarioStage]
    defaults: Dict[str, Any] = field(default_factory=dict)
    ui: Dict[str, Any] = field(default_factory=dict)
    # 场景自带的画面风格 [{id, label}]，对应 prompts/style/<id>.txt，前端会追加到风格列表
    styles: List[Dict[str, str]] = field(default_factory=list)
    path: str = ""

    @property
    def stage_ids(self) -> List[str]:
        return [stage.id for stage in self.stages]

    @property
    def prompt_dirs(self) -> List[str]:
        prompts = os.path.join(self.path, "prompts")
        return [prompts] if self.path and os.path.isdir(prompts) else []

    def stage(self, stage_id: str) -> Optional[ScenarioStage]:
        return next((s for s in self.stages if s.id == stage_id), None)

    def has_stage(self, stage_id: str) -> bool:
        return self.stage(stage_id) is not None

    def next_stage(self, stage_id: str) -> Optional[str]:
        ids = self.stage_ids
        if stage_id not in ids:
            return ids[0] if stage_id == "init" and ids else None
        idx = ids.index(stage_id)
        return ids[idx + 1] if idx + 1 < len(ids) else None

    def required_model_fields(self) -> List[str]:
        fields: List[str] = []
        for stage in self.stages:
            for name in STAGE_MODEL_FIELDS.get(stage.type, ()):
                if name not in fields:
                    fields.append(name)
        return fields

    @property
    def needs_video_model(self) -> bool:
        return self.has_stage("video_generation")

    def agent_class(self, stage_id: str, default: Optional[Type[AgentInterface]] = None) -> Type[AgentInterface]:
        stage = self.stage(stage_id)
        if stage and stage.agent:
            return load_agent_class(stage.agent)
        if default is None:
            raise ScenarioError(f"Stage {stage_id!r} of scenario {self.id!r} has no agent")
        return default

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "tagline": self.tagline,
            "description": self.description,
            "category": self.category,
            "order": self.order,
            "stages": [stage.to_dict() for stage in self.stages],
            "defaults": dict(self.defaults),
            "ui": dict(self.ui),
            "styles": [dict(style) for style in self.styles],
            "requires_video_model": self.needs_video_model,
        }


def _text(value: Any, default: str = "") -> str:
    return str(value).strip() if value is not None else default


def _parse_stage(raw: Any, scenario_id: str, index: int) -> ScenarioStage:
    if isinstance(raw, str):
        raw = {"type": raw}
    if not isinstance(raw, dict):
        raise ScenarioError(f"{scenario_id}: stages[{index}] must be a mapping or a stage type")

    stage_type = _text(raw.get("type"))
    stage_id = _text(raw.get("id")) or stage_type
    agent = _text(raw.get("agent")) or None

    if stage_type and stage_type not in BUILTIN_STAGES:
        raise ScenarioError(
            f"{scenario_id}: unknown stage type {stage_type!r}; built-in types are {', '.join(BUILTIN_STAGES)}"
        )
    if stage_type and stage_id != stage_type:
        raise ScenarioError(f"{scenario_id}: built-in stage {stage_type!r} must keep its id")
    if not stage_type:
        if not SAFE_ID.match(stage_id):
            raise ScenarioError(f"{scenario_id}: custom stage id {stage_id!r} must be snake_case")
        if stage_id in BUILTIN_STAGES:
            raise ScenarioError(f"{scenario_id}: use `type: {stage_id}` for built-in stages")
        if not agent:
            raise ScenarioError(f"{scenario_id}: custom stage {stage_id!r} needs an `agent`")

    options = raw.get("options") or {}
    if not isinstance(options, dict):
        raise ScenarioError(f"{scenario_id}: options of stage {stage_id!r} must be a mapping")

    spec = BUILTIN_STAGES.get(stage_type)
    name = _text(raw.get("name")) or (spec.name if spec else stage_id)
    return ScenarioStage(
        id=stage_id,
        type=stage_type or "custom",
        name=name,
        short_name=_text(raw.get("short_name")) or name[:2],
        description=_text(raw.get("description")) or (spec.description if spec else ""),
        agent=agent,
        options=dict(options),
    )


def parse_scenario(data: Dict[str, Any], scenario_id: str, path: str = "") -> Scenario:
    """Validate a scenario.yaml mapping and build a Scenario."""
    if not isinstance(data, dict):
        raise ScenarioError(f"{scenario_id}: scenario.yaml must be a mapping")
    if not SAFE_ID.match(scenario_id):
        raise ScenarioError(f"Scenario id {scenario_id!r} must be snake_case (it is also a Python package name)")

    raw_stages = data.get("stages")
    if not isinstance(raw_stages, list) or not raw_stages:
        raise ScenarioError(f"{scenario_id}: `stages` must be a non-empty list")
    stages = [_parse_stage(raw, scenario_id, i) for i, raw in enumerate(raw_stages)]
    ids = [s.id for s in stages]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ScenarioError(f"{scenario_id}: duplicate stages {duplicates}")
    for index, stage in enumerate(stages):
        earlier = ids[:index]
        for required in STAGE_REQUIRES.get(stage.type, ()):
            if required not in earlier:
                raise ScenarioError(f"{scenario_id}: stage {stage.id!r} needs {required!r} earlier in `stages`")

    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ScenarioError(f"{scenario_id}: `defaults` must be a mapping")
    unknown = sorted(set(defaults) - set(DEFAULT_KEYS))
    if unknown:
        raise ScenarioError(f"{scenario_id}: unsupported defaults {unknown}; allowed: {', '.join(DEFAULT_KEYS)}")

    ui = data.get("ui") or {}
    if not isinstance(ui, dict):
        raise ScenarioError(f"{scenario_id}: `ui` must be a mapping")

    styles = []
    for raw in data.get("styles") or []:
        if not isinstance(raw, dict) or not _text(raw.get("id")):
            raise ScenarioError(f"{scenario_id}: each entry of `styles` needs an id")
        styles.append({"id": _text(raw["id"]), "label": _text(raw.get("label")) or _text(raw["id"])})
    if path:
        for style in styles:
            if not os.path.isfile(os.path.join(path, "prompts", "style", f"{style['id']}.txt")):
                raise ScenarioError(f"{scenario_id}: style {style['id']!r} needs prompts/style/{style['id']}.txt")

    category = _text(data.get("category"), "video")
    if category not in ("video", "image"):
        raise ScenarioError(f"{scenario_id}: category must be video or image")

    try:
        order = int(data.get("order", 100))
    except (TypeError, ValueError):
        raise ScenarioError(f"{scenario_id}: order must be an integer") from None

    return Scenario(
        id=scenario_id,
        name=_text(data.get("name"), scenario_id),
        tagline=_text(data.get("tagline")),
        description=_text(data.get("description")),
        category=category,
        order=order,
        stages=stages,
        defaults=dict(defaults),
        ui=dict(ui),
        styles=styles,
        path=path,
    )


def load_scenario_dir(path: str) -> Scenario:
    scenario_id = os.path.basename(os.path.normpath(path))
    with open(os.path.join(path, SCENARIO_FILE), "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    declared = _text(data.get("id")) if isinstance(data, dict) else ""
    if declared and declared != scenario_id:
        raise ScenarioError(f"{path}: id {declared!r} must match its folder name {scenario_id!r}")
    return parse_scenario(data, scenario_id, path)


class ScenarioRegistry:
    """Loads every scenario package under a directory; invalid packages are logged and skipped."""

    def __init__(self, root: str = SCENARIOS_DIR):
        self.root = root
        self._lock = threading.RLock()
        self._scenarios: Dict[str, Scenario] = {}
        self.errors: Dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        scenarios: Dict[str, Scenario] = {}
        errors: Dict[str, str] = {}
        if os.path.isdir(self.root):
            for name in sorted(os.listdir(self.root)):
                path = os.path.join(self.root, name)
                if not os.path.isfile(os.path.join(path, SCENARIO_FILE)):
                    continue
                try:
                    scenario = load_scenario_dir(path)
                    for stage in scenario.stages:
                        if stage.agent:
                            load_agent_class(stage.agent)
                    scenarios[scenario.id] = scenario
                except Exception as exc:
                    errors[name] = str(exc)
                    logger.error("Skipping scenario %s: %s", name, exc)
        with self._lock:
            self._scenarios = scenarios
            self.errors = errors

    def list(self) -> List[Scenario]:
        with self._lock:
            return sorted(self._scenarios.values(), key=lambda s: (s.order, s.id))

    def get(self, scenario_id: Optional[str]) -> Optional[Scenario]:
        with self._lock:
            return self._scenarios.get(scenario_id or "")

    def default_id(self, preferred: Optional[str] = None) -> str:
        with self._lock:
            for candidate in (preferred, DEFAULT_SCENARIO_ID):
                if candidate and candidate in self._scenarios:
                    return candidate
            ordered = self.list()
            if not ordered:
                raise ScenarioError(f"No valid scenario found in {self.root}")
            return ordered[0].id

    def resolve(self, scenario_id: Optional[str], preferred_default: Optional[str] = None) -> Scenario:
        """Return the named scenario, or the default one when scenario_id is empty (old sessions)."""
        if scenario_id:
            scenario = self.get(scenario_id)
            if scenario is None:
                raise KeyError(f"Unknown scenario: {scenario_id}")
            return scenario
        return self._scenarios[self.default_id(preferred_default)]
