from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .cards_schema import Card, ExportVersion, Illustration
from .contracts import ExtractRequest as ExtractRequest
from .contracts import StrictModel, Versioned
from .scenes import Scene
from .video_schema import AudioAsset, VideoVersion


class Material(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=6000)
    url: str = Field(default="", max_length=2000)
    audience: str = Field(default="普通读者", max_length=200)

    @field_validator("title", "text", "audience")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("内容不能为空")
        return value

    @field_validator("url")
    @classmethod
    def source_link(cls, value):
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("来源链接需要http或https协议")
        return value


class SaveMaterial(Material):
    expected_revision: int = Field(ge=1)


class ClaimEdit(Versioned):
    text: str = Field(min_length=1, max_length=1000)


class ClaimSelection(Versioned):
    claim_ids: list[str] = Field(min_length=1, max_length=6)


class MergeClaims(ClaimSelection):
    text: str = Field(min_length=1, max_length=1000)


class Candidate(StrictModel):
    text: str = Field(min_length=1, max_length=1000)
    kind: Literal["source", "supplement"]
    quotes: list[str] = Field(min_length=1, max_length=6)


class Extraction(StrictModel):
    claims: list[Candidate] = Field(min_length=4, max_length=6)


class ErrorDetail(StrictModel):
    code: str
    message: str


class ErrorResponse(StrictModel):
    error: ErrorDetail


class SourceSnapshot(Material):
    revision: int = Field(ge=1)


class Reference(StrictModel):
    source_revision: int = Field(ge=1)
    start_cp: int = Field(ge=0)
    end_cp: int = Field(ge=1)
    quote: str


class Claim(StrictModel):
    id: str
    text: str
    kind: Literal["source", "supplement"]
    references: list[Reference]
    confirmed: bool
    active: bool


class Job(StrictModel):
    id: str
    operation_id: str
    status: Literal["pending", "running", "interrupted", "completed", "failed", "stale"]
    error: ErrorDetail | None
    kind: str = "extract"


class Budget(StrictModel):
    limit_micro: int
    settled_micro: int
    reserved_micro: int
    available_micro: int


class WorkData(BaseModel):
    schema_version: Literal[1]
    id: str
    owner_id: Literal["local"]
    revision: int = Field(ge=1)
    stage: Literal["material", "review_required", "review", "reviewed"]
    sources: list[SourceSnapshot]
    claims: list[Claim]
    jobs: list[Job]
    budget: Budget
    cards: list[Card] = Field(default_factory=list)
    cards_basis: str = ""
    cards_current: bool = False
    illustrations: list[Illustration] = Field(default_factory=list)
    exports: list[ExportVersion] = Field(default_factory=list)
    deck_fingerprint: str = ""
    audios: list[AudioAsset] = Field(default_factory=list)
    videos: list[VideoVersion] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)
    scenes_basis: str = ""


class WorkResponse(BaseModel):
    work: WorkData


class WorksResponse(BaseModel):
    works: list[WorkData]


class JobResponse(BaseModel):
    job: Job


class HealthResponse(StrictModel):
    status: str
    model_configured: bool
    paid_calls_enabled: bool
    pricing_confirmed: bool
    model: str
    tts_configured: bool = False
    tts_enabled: bool = False
    tts_model: str = "qwen3-tts-flash"
    image_configured: bool = False
    image_enabled: bool = False
    image_price_micro: int = 40_000
