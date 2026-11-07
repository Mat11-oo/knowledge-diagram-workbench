from typing import Any, Dict, Optional

from pydantic import BaseModel


class ProjectStartRequest(BaseModel):
    idea: str
    # 场景包 id（backend/scenarios/ 下的目录名）；留空使用 workflow.default_scenario
    scenario: Optional[str] = None
    file_path: Optional[str] = None
    # 以下生成参数留空时，依次使用场景包 defaults 和全局配置
    style: Optional[str] = None
    video_ratio: Optional[str] = None
    video_resolution: Optional[str] = None
    expand_idea: Optional[bool] = None
    llm_model: Optional[str] = None
    vlm_model: Optional[str] = None
    image_t2i_model: Optional[str] = None
    image_it2i_model: Optional[str] = None
    video_model: Optional[str] = None
    video_first_frame_model: Optional[str] = None
    video_start_end_model: Optional[str] = None
    video_reference_model: Optional[str] = None
    video_generation_mode: Optional[str] = None
    enable_concurrency: Optional[bool] = True
    web_search: Optional[bool] = False
    episodes: Optional[int] = None


class InterventionRequest(BaseModel):
    stage: str
    modifications: Dict[str, Any]
