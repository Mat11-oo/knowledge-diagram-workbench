"""Central model registry.

Model metadata (provider, model type, concurrency, pricing and API capability
tags) is declared in ``backend/registry/models.yaml``. Deployments can add or
override models without touching code through ``registry/models.local.yaml``
or the ``custom_models`` section of ``config.yaml``.
"""

import os
import sys

models_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(models_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import logging
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

REGISTRY_DIR = Path(backend_dir) / "registry"
REGISTRY_PATH = REGISTRY_DIR / "models.yaml"
LOCAL_REGISTRY_PATH = REGISTRY_DIR / "models.local.yaml"


def _read_registry_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    models = data.get("models", {}) if isinstance(data, dict) else {}
    if not isinstance(models, dict):
        raise ValueError(f"{path} must contain a 'models' mapping.")
    return models


def _custom_models_from_config() -> dict[str, Any]:
    try:
        from config import Config
    except ImportError:
        return {}
    custom = Config.CONFIG.get("custom_models") or {}
    return custom if isinstance(custom, dict) else {}


def _build_model_config() -> dict[str, Any]:
    models: dict[str, Any] = {}
    for source in (
        _read_registry_file(REGISTRY_PATH),
        _read_registry_file(LOCAL_REGISTRY_PATH),
        _custom_models_from_config(),
    ):
        for model_id, metadata in source.items():
            if not isinstance(metadata, dict):
                logger.warning("Ignoring model %s: metadata must be a mapping", model_id)
                continue
            models[str(model_id)] = {**models.get(str(model_id), {}), **metadata}
    return {"models": models}


MODEL_CONFIG: dict[str, Any] = _build_model_config()


def reload_model_config() -> dict[str, Any]:
    """Re-read the registry files and config.yaml custom_models in place."""
    MODEL_CONFIG.clear()
    MODEL_CONFIG.update(_build_model_config())
    return MODEL_CONFIG


def resolve_provider(model: str) -> str:
    """Return the registered provider id for a model, or "" when unregistered."""
    metadata = MODEL_CONFIG.get("models", {}).get(model or "")
    return str(metadata.get("provider") or "") if metadata else ""


def load_model_config() -> dict[str, Any]:
    return MODEL_CONFIG


def get_model_config(model: str) -> dict[str, Any]:
    """Get metadata for one model, with a loose fallback for provider aliases."""
    models = MODEL_CONFIG.get("models", {})
    if model in models:
        return models[model]

    model_lower = model.lower()
    for key, value in models.items():
        if key in model_lower or model_lower in key:
            return value

    return {
        "name": model,
        "provider": "unknown",
        "type": [],
        "concurrency": 3,
    }


def get_max_concurrency(model: str, enable_concurrency: bool = False) -> int:
    if not enable_concurrency:
        return 1
    return int(get_model_config(model).get("concurrency", 3))


def get_models_by_type(model_type: str) -> list[dict[str, Any]]:
    result = []
    for model_id, metadata in MODEL_CONFIG.get("models", {}).items():
        if model_type in (metadata.get("type") or []):
            result.append({"id": model_id, **metadata})
    return result


def model_type_capabilities(model_type: str, metadata: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Return normalized capability metadata for non-media model selectors."""
    metadata = metadata or {}
    if metadata.get("capabilities"):
        return deepcopy(metadata["capabilities"])
    if model_type == "llm":
        return {
            "ability_type": "text_generation",
            "ability_types": ["text_generation"],
            "adapter_ability_types": ["text_generation"],
            "input_modalities": ["text"],
            "adapter_input_modalities": ["text"],
            "api_contract_verified": bool(metadata.get("api_contract_verified", False)),
        }
    if model_type == "vlm":
        return {
            "ability_type": "vision_language",
            "ability_types": ["vision_language", "image_understanding"],
            "adapter_ability_types": ["vision_language", "image_understanding"],
            "input_modalities": ["text", "image"],
            "adapter_input_modalities": ["text", "image"],
            "api_contract_verified": bool(metadata.get("api_contract_verified", False)),
        }
    return media_capabilities(metadata.get("provider", ""), metadata.get("id", ""), "video" if model_type == "video" else "image")


def model_records(media_type: Optional[str] = None) -> list[dict[str, Any]]:
    records = []
    for model_id, metadata in MODEL_CONFIG.get("models", {}).items():
        resolved_media_type = _resolve_media_type(metadata.get("type") or [])
        if media_type and resolved_media_type != media_type:
            continue
        if resolved_media_type not in {"image", "video"}:
            continue
        records.append(_workflow_info(model_id, metadata, resolved_media_type))
    return records


def list_api_models(
    media_type: Optional[str] = None,
    required_adapter_abilities: Optional[list[str]] = None,
    verified_only: bool = False,
) -> list[dict[str, Any]]:
    records = model_records(media_type=media_type)
    required = set(required_adapter_abilities or [])
    if verified_only:
        records = [record for record in records if record.get("api_contract_verified", True)]
    if required:
        records = [record for record in records if required.intersection(model_ability_tags(record))]
    return records


def parse_api_model(model: str, media_type: str) -> tuple[str, str]:
    if model and model.startswith("api/"):
        _, provider, model_id = model.split("/", 2)
        return provider, model_id

    metadata = MODEL_CONFIG.get("models", {}).get(model)
    if metadata and _resolve_media_type(metadata.get("type") or []) == media_type:
        return metadata.get("provider", ""), model
    return "", model


def media_capabilities(provider: str, model: str, media_type: str) -> dict[str, Any]:
    metadata = MODEL_CONFIG.get("models", {}).get(model, {})
    capabilities = metadata.get("capabilities")
    if capabilities:
        return deepcopy(capabilities)
    if media_type == "image":
        return {
            "ability_type": "image_generation",
            "ability_types": ["text_to_image"],
            "adapter_ability_types": ["text_to_image"],
            "input_modalities": ["text"],
            "adapter_input_modalities": ["text"],
            "api_contract_verified": False,
        }
    return {
        "ability_type": "image_to_video",
        "ability_types": [],
        "adapter_ability_types": ["first_frame_i2v"],
        "input_modalities": ["text", "image"],
        "adapter_input_modalities": ["text", "image"],
        "api_contract_verified": False,
        "duration": {"min": 3, "max": 15, "integer": True, "verified": False},
    }


def video_capabilities(provider: str, model: str) -> dict[str, Any]:
    return media_capabilities(provider, model, "video")


def image_capabilities(provider: str, model: str) -> dict[str, Any]:
    return media_capabilities(provider, model, "image")


def model_ability_tags(record: dict[str, Any]) -> set[str]:
    tags = set(record.get("adapter_ability_types") or [])
    tags.update(record.get("ability_types") or [])
    if record.get("ability_type"):
        tags.add(record["ability_type"])
    tags.update(record.get("type") or [])
    return tags


def _workflow_info(model_id: str, metadata: dict[str, Any], media_type: str) -> dict[str, Any]:
    provider = metadata.get("provider", "")
    capabilities = media_capabilities(provider, model_id, media_type)
    return {
        "key": f"api/{provider}/{model_id}",
        "name": model_id,
        "display_name": f"{metadata.get('name') or model_id} - API {provider.title()}",
        "source": "api",
        "provider": provider,
        "family": metadata.get("family"),
        "model": model_id,
        "media_type": media_type,
        "type": metadata.get("type", []),
        "capabilities": capabilities,
        "ability_type": capabilities.get("ability_type"),
        "ability_types": capabilities.get("ability_types", []),
        "adapter_ability_types": capabilities.get("adapter_ability_types", []),
        "input_modalities": capabilities.get("input_modalities", []),
        "adapter_input_modalities": capabilities.get("adapter_input_modalities", []),
        "api_contract_verified": capabilities.get("api_contract_verified", False),
        "concurrency": metadata.get("concurrency"),
    }


def _resolve_media_type(types: list[str]) -> str:
    if "video" in types:
        return "video"
    if any(item in types for item in ("t2i", "i2i", "image")):
        return "image"
    return ""
