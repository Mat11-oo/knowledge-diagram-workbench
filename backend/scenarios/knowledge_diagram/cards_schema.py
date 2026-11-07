"""Card and immutable asset contracts. Defaults allow stage 2-1 manifests to reopen."""

from typing import Literal

from pydantic import Field, field_validator

from .contracts import ExtractRequest, StrictModel, Versioned


class Card(StrictModel):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    claim_id: str
    title: str = Field(min_length=1, max_length=60)
    body: str = Field(min_length=1, max_length=1000)
    narration: str = Field(min_length=1, max_length=1000)
    prompt: str = Field(min_length=1, max_length=1200)
    template: Literal["paper", "ink"] = "paper"
    illustration_id: str | None = None
    kind: Literal["source", "supplement"]
    edited: bool = False

    @field_validator("title", "body", "narration", "prompt")
    @classmethod
    def visible_text(cls, value):
        if not value.strip() or any(ord(c) < 32 and c not in "\n\t" for c in value):
            raise ValueError("请填写可显示的文字")
        return value


class CardEdit(Versioned):
    title: str = Field(min_length=1, max_length=60)
    body: str = Field(min_length=1, max_length=1000)
    narration: str = Field(min_length=1, max_length=1000)
    prompt: str = Field(min_length=1, max_length=1200)
    template: Literal["paper", "ink"]

    _visible = field_validator("title", "body", "narration", "prompt")(Card.visible_text.__func__)


class CardOrder(Versioned):
    card_ids: list[str] = Field(min_length=3, max_length=6)


class ImageRequest(ExtractRequest):
    # An explicit cost confirmation for the visible single-image action, in micro-yuan.
    max_cost_micro: int = Field(ge=1, le=1_000_000)


class Illustration(StrictModel):
    id: str
    card_id: str
    prompt: str
    sha256: str
    filename: str
    model: str = ""


class ExportVersion(StrictModel):
    id: str
    fingerprint: str
    files: list[str]
    cards: list[Card]
