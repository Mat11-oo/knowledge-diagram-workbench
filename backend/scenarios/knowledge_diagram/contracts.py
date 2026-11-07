from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Versioned(StrictModel):
    expected_revision: int = Field(ge=1)


class ExtractRequest(Versioned):
    operation_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,80}$")
