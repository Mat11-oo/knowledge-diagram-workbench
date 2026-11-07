from pydantic import Field

from .contracts import ExtractRequest, StrictModel


class VideoRequest(ExtractRequest):
    max_cost_micro: int = Field(ge=0, le=60_000)


class AudioAsset(StrictModel):
    id: str
    key: str
    filename: str
    sha256: str
    duration_ms: int
    model: str


class Cue(StrictModel):
    card_id: str
    scene_id: str = ""
    scene_step_index: int = Field(default=0, ge=0, le=4)
    text: str
    audio_id: str
    start_ms: int
    end_ms: int


class VideoVersion(StrictModel):
    id: str
    fingerprint: str
    filename: str
    sha256: str
    export_id: str
    duration_ms: int
    timeline: list[Cue]
    model: str


class VideoPlan(StrictModel):
    characters: int
    segments: int
    uncached_segments: int
    reserve_micro: int
    voice: str
    model: str
