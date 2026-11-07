import os
from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel, Field

from api.logging_config import apply_access_log_setting, apply_log_level_setting
from config import Config


def _config_response():
    try:
        path = os.path.relpath(Config.CONFIG_PATH, os.path.dirname(Config.BASE_DIR))
    except ValueError:
        path = Config.CONFIG_PATH
    return {
        "config": Config.as_public_dict(),
        "path": path,
        # Paths currently set by SFA_* environment variables; edits to them are saved
        # to config.yaml but stay shadowed until the variable is removed.
        "env_overrides": Config.ENV_OVERRIDDEN_PATHS,
    }


router = APIRouter(tags=["Configuration"])


class ConfigUpdateRequest(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict)


@router.get("/api/config")
async def get_config():
    return _config_response()


@router.put("/api/config")
async def update_config(req: ConfigUpdateRequest):
    Config.update_config(req.values)
    apply_log_level_setting()
    apply_access_log_setting()
    return _config_response()
