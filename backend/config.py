"""Backend configuration.

Values come from three layers, later layers winning:

1. ``DEFAULT_CONFIG`` below (built from ``PROVIDERS``)
2. ``config.yaml`` (path overridable with ``SFA_CONFIG``), editable from the settings page
3. ``SFA_*`` environment variables (see ``ENV_OVERRIDES`` and ``provider_env_var``)

Environment overrides are applied at runtime only and are never written back
to ``config.yaml``, so secrets injected by Docker / CI stay out of the file.
"""

import copy
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)

ENV_PREFIX = "SFA_"
BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.getenv(f"{ENV_PREFIX}CONFIG") or BASE_DIR / "config.yaml").resolve()
CONFIG_EXAMPLE_PATH = BASE_DIR / "config.yaml.example"
SECRET_MASK = "********"

# Model service providers. To add a provider, declare its fields here, then
# implement a client in models/ and route the provider id in the matching
# models/*_client.py facade (see docs/extending.md).
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "openai": {
        "label": "OpenAI",
        "fields": {"api_key": "", "base_url": "https://api.openai.com/v1", "enable_proxy": False},
        "secrets": ("api_key",),
    },
    "gemini": {
        "label": "Google Gemini",
        "fields": {
            "api_key": "",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "enable_proxy": False,
        },
        "secrets": ("api_key",),
        # Historical attribute name kept for existing clients.
        "attrs": {"base_url": "GOOGLE_GEMINI_BASE_URL"},
    },
    "deepseek": {
        "label": "DeepSeek",
        "fields": {"api_key": "", "base_url": "https://api.deepseek.com/v1", "enable_proxy": False},
        "secrets": ("api_key",),
    },
    "dashscope": {
        "label": "阿里云百炼 DashScope",
        "fields": {"api_key": "", "base_url": "https://dashscope.aliyuncs.com/api/v1", "enable_proxy": False},
        "secrets": ("api_key",),
    },
    "ark": {
        "label": "火山方舟 Ark",
        "fields": {"api_key": "", "base_url": "https://ark.cn-beijing.volces.com/api/v3", "enable_proxy": False},
        "secrets": ("api_key",),
    },
    "kling": {
        "label": "可灵 Kling",
        "fields": {
            "base_url": "https://api-beijing.klingai.com",
            "access_key": "",
            "secret_key": "",
            "enable_proxy": False,
        },
        "secrets": ("access_key", "secret_key"),
    },
    # Any OpenAI-compatible chat endpoint (vLLM, Ollama, OpenRouter, Moonshot, ...).
    # Register its models with provider: openai_compatible in registry/models.local.yaml
    # or config.yaml custom_models.
    "openai_compatible": {
        "label": "OpenAI 兼容接口",
        "fields": {"api_key": "", "base_url": "", "enable_proxy": False},
        "secrets": ("api_key",),
    },
}

SECRET_PATHS = tuple(
    f"api_providers.{provider}.{field}"
    for provider, spec in PROVIDERS.items()
    for field in spec.get("secrets", ())
)

DEFAULT_CONFIG: Dict[str, Any] = {
    "app": {
        "name": "知识图解工作台",
        "tagline": "AI 短片创作 Agent",
    },
    "server": {
        "host": "127.0.0.1",
        "port": 8000,
        "log_level": "INFO",
        "access_log": False,
    },
    "api_providers": {
        "common": {
            "print_model_input": False,
            "proxy": "",
        },
        **{provider: dict(spec["fields"]) for provider, spec in PROVIDERS.items()},
    },
    "models": {
        "llm": "qwen3.5-plus",
        "vlm": "qwen3.5-plus",
        "image_it2i": "doubao-seedream-5-0-260128",
        "image_t2i": "doubao-seedream-5-0-260128",
        "video": "wan2.7-i2v",
        "video_first_frame": "wan2.7-i2v",
        "video_start_end": "wan2.7-i2v",
        "video_reference": "wan2.7-r2v",
    },
    "generation": {
        "style": "realistic",
        "video_ratio": "16:9",
        "video_resolution": "720P",
        "video_generation_mode": "first_frame",
    },
    "workflow": {
        # Scenario used when a project does not name one (folder name under backend/scenarios/).
        "default_scenario": "short_film",
        # Replace the agent of a built-in stage in every scenario: {<stage id>: "package.module:ClassName"}.
        "agents": {},
    },
    # Extra model registry entries, same format as registry/models.yaml.
    "custom_models": {},
}

# Non-provider environment overrides: env var -> config path.
ENV_OVERRIDES = {
    f"{ENV_PREFIX}APP_NAME": "app.name",
    f"{ENV_PREFIX}APP_TAGLINE": "app.tagline",
    f"{ENV_PREFIX}HOST": "server.host",
    f"{ENV_PREFIX}PORT": "server.port",
    f"{ENV_PREFIX}LOG_LEVEL": "server.log_level",
    f"{ENV_PREFIX}DEFAULT_SCENARIO": "workflow.default_scenario",
    f"{ENV_PREFIX}PROXY": "api_providers.common.proxy",
    **{
        f"{ENV_PREFIX}MODEL_{key.upper()}": f"models.{key}"
        for key in DEFAULT_CONFIG["models"]
    },
}


def provider_env_var(provider: str, field: str) -> str:
    """Environment variable for a provider field, e.g. SFA_DASHSCOPE_API_KEY."""
    return f"{ENV_PREFIX}{provider.upper()}_{field.upper()}"


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _get(data: Dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _set(data: Dict[str, Any], path: str, value: Any) -> None:
    current = data
    parts = path.split(".")
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value


def redact_config(values: Dict[str, Any]) -> Dict[str, Any]:
    public = copy.deepcopy(values)
    for path in SECRET_PATHS:
        _set(public, path, SECRET_MASK if _get(values, path) else "")
    return public


def merge_config_update(current: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(updates, dict):
        raise ValueError("Configuration update must be a mapping.")

    clean_updates = copy.deepcopy(updates)
    for path in SECRET_PATHS:
        if _get(clean_updates, path, None) == SECRET_MASK:
            _set(clean_updates, path, _get(current, path, ""))
    return _deep_merge(current, clean_updates)


def env_overrides(environ: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Collect SFA_* environment variables as a nested config mapping."""
    environ = os.environ if environ is None else environ
    overrides: Dict[str, Any] = {}
    for env_name, path in ENV_OVERRIDES.items():
        if environ.get(env_name):
            _set(overrides, path, environ[env_name])
    for provider, spec in PROVIDERS.items():
        for field in spec["fields"]:
            env_name = provider_env_var(provider, field)
            if environ.get(env_name):
                _set(overrides, f"api_providers.{provider}.{field}", environ[env_name])
    return overrides


def _coerce_config(data: Dict[str, Any]) -> Dict[str, Any]:
    clean = _deep_merge(DEFAULT_CONFIG, data)
    clean.pop("llm", None)
    # Legacy config compatibility: the old top-level project_name was replaced by app.name.
    clean.pop("project_name", None)
    raw_server = data.get("server", {}) if isinstance(data, dict) else {}

    legacy_models = data.get("models", {}) if isinstance(data, dict) else {}
    if isinstance(legacy_models, dict):
        for legacy_key in ("style", "video_ratio", "video_resolution"):
            # Legacy config compatibility: older config.yaml stored generation settings under models.*.
            if legacy_key in legacy_models and not _get(data, f"generation.{legacy_key}"):
                clean.setdefault("generation", {})[legacy_key] = legacy_models[legacy_key]
            clean["models"].pop(legacy_key, None)
        if legacy_models.get("video") and not any(
            legacy_models.get(key) for key in ("video_first_frame", "video_start_end", "video_reference")
        ):
            # Legacy config compatibility: older configs had one models.video instead of mode-specific video models.
            clean["models"]["video_first_frame"] = legacy_models["video"]
        # Legacy config compatibility: models.eval was never used by runtime agents; keep it out after load.
        clean["models"].pop("eval", None)

    app = clean["app"]
    for key in ("name", "tagline"):
        app[key] = str(app.get(key) or DEFAULT_CONFIG["app"][key])

    server = clean["server"]
    server["host"] = str(server.get("host") or DEFAULT_CONFIG["server"]["host"])
    try:
        server["port"] = int(server.get("port"))
    except (TypeError, ValueError):
        server["port"] = DEFAULT_CONFIG["server"]["port"]
    server["log_level"] = _normalize_log_level(
        server.get("log_level") if isinstance(raw_server, dict) and "log_level" in raw_server else None,
        server.get("debug"),
    )
    server.pop("debug", None)
    server["access_log"] = _as_bool(server.get("access_log"))
    server.pop("admin_password", None)

    common = clean["api_providers"]["common"]
    for key in ("local_proxy", "http_proxy", "https_proxy"):
        common.pop(key, None)
    common["print_model_input"] = _as_bool(common.get("print_model_input"))
    common["proxy"] = str(common.get("proxy") or "")

    if isinstance(clean["models"].get("llm"), dict):
        clean["models"]["llm"] = clean["models"]["llm"].get("model") or DEFAULT_CONFIG["models"]["llm"]

    for key, value in clean["models"].items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                value[sub_key] = "" if sub_value is None else str(sub_value)
        else:
            clean["models"][key] = "" if value is None else str(value)

    for key, value in clean["generation"].items():
        clean["generation"][key] = "" if value is None else str(value)

    for provider, values in clean["api_providers"].items():
        if provider == "common":
            continue
        for key, value in values.items():
            if key == "enable_proxy":
                values[key] = _as_bool(value)
            else:
                values[key] = "" if value is None else str(value)

    workflow = clean["workflow"] if isinstance(clean.get("workflow"), dict) else {}
    agents = workflow.get("agents") if isinstance(workflow.get("agents"), dict) else {}
    workflow["agents"] = {str(k): str(v) for k, v in agents.items() if v}
    workflow["default_scenario"] = str(workflow.get("default_scenario") or "short_film")
    clean["workflow"] = workflow
    if not isinstance(clean.get("custom_models"), dict):
        clean["custom_models"] = {}

    return clean


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_log_level(value: Any, legacy_debug: Any = None) -> str:
    allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if legacy_debug is not None and (value is None or str(value).strip() == ""):
        return "DEBUG" if _as_bool(legacy_debug) else "INFO"
    normalized = str(value or DEFAULT_CONFIG["server"]["log_level"]).strip().upper()
    return normalized if normalized in allowed else DEFAULT_CONFIG["server"]["log_level"]


def load_config() -> Dict[str, Any]:
    """Load config.yaml (or the example file) without environment overrides."""
    if not CONFIG_PATH.exists():
        source = CONFIG_EXAMPLE_PATH if CONFIG_EXAMPLE_PATH.exists() else None
        if source:
            with source.open("r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            return _coerce_config(loaded)
        return copy.deepcopy(DEFAULT_CONFIG)

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{CONFIG_PATH} must contain a YAML mapping.")
    return _coerce_config(loaded)


def save_config(values: Dict[str, Any]) -> Dict[str, Any]:
    clean = _coerce_config(values)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=CONFIG_PATH.parent, prefix="config.", suffix=".yaml.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(clean, f, allow_unicode=True, sort_keys=False)
        os.replace(temp_path, CONFIG_PATH)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise
    return clean


def _attr_name(provider: str, field: str) -> str:
    custom = PROVIDERS[provider].get("attrs", {}).get(field)
    return custom or f"{provider.upper()}_{field.upper()}"


class Config:
    # Values persisted in config.yaml.
    FILE_CONFIG: Dict[str, Any] = load_config()
    # Effective values: FILE_CONFIG plus SFA_* environment overrides.
    CONFIG: Dict[str, Any] = {}
    ENV_OVERRIDDEN_PATHS: list = []

    BASE_DIR = str(BASE_DIR)
    CODE_DIR = os.path.join(BASE_DIR, "code")
    RESULT_DIR = os.path.join(CODE_DIR, "result")
    TEMP_DIR = os.path.join(BASE_DIR, "temp")
    SESSION_DIR = os.path.join(CODE_DIR, "data", "sessions")
    TASK_DIR = os.path.join(CODE_DIR, "data", "tasks")
    TASK_RESULT_DIR = os.path.join(RESULT_DIR, "task")
    CONFIG_PATH = str(CONFIG_PATH)

    @classmethod
    def _apply(cls, file_config: Dict[str, Any]) -> None:
        overrides = env_overrides()
        cls.FILE_CONFIG = file_config
        cls.CONFIG = _coerce_config(_deep_merge(file_config, overrides))
        cls.ENV_OVERRIDDEN_PATHS = sorted(
            {path for path in ENV_OVERRIDES.values() if _get(overrides, path) is not None}
            | {
                f"api_providers.{provider}.{field}"
                for provider, spec in PROVIDERS.items()
                for field in spec["fields"]
                if _get(overrides, f"api_providers.{provider}.{field}") is not None
            }
        )
        clean = cls.CONFIG

        cls.APP_NAME = _get(clean, "app.name")
        cls.APP_TAGLINE = _get(clean, "app.tagline")

        cls.HOST = _get(clean, "server.host")
        cls.PORT = _get(clean, "server.port")
        cls.LOG_LEVEL = _get(clean, "server.log_level")
        cls.DEBUG = cls.LOG_LEVEL == "DEBUG"
        cls.ACCESS_LOG = _get(clean, "server.access_log")

        cls.PRINT_MODEL_INPUT = _get(clean, "api_providers.common.print_model_input")
        cls.PROXY = _get(clean, "api_providers.common.proxy")

        # Provider credentials as flat attributes, e.g. DASHSCOPE_API_KEY, KLING_SECRET_KEY.
        for provider, spec in PROVIDERS.items():
            for field in spec["fields"]:
                setattr(cls, _attr_name(provider, field), _get(clean, f"api_providers.{provider}.{field}"))

        cls.LLM_MODEL = _get(clean, "models.llm")
        cls.VLM_MODEL = _get(clean, "models.vlm")
        cls.IMAGE_IT2I_MODEL = _get(clean, "models.image_it2i")
        cls.IMAGE_T2I_MODEL = _get(clean, "models.image_t2i")
        cls.VIDEO_MODEL = _get(clean, "models.video")
        cls.VIDEO_FIRST_FRAME_MODEL = _get(clean, "models.video_first_frame")
        cls.VIDEO_START_END_MODEL = _get(clean, "models.video_start_end")
        cls.VIDEO_REFERENCE_MODEL = _get(clean, "models.video_reference")
        cls.VIDEO_RATIO = _get(clean, "generation.video_ratio")
        cls.VIDEO_RESOLUTION = _get(clean, "generation.video_resolution")
        cls.VIDEO_GENERATION_MODE = _get(clean, "generation.video_generation_mode")
        cls.STYLE = _get(clean, "generation.style")

        cls.WORKFLOW_AGENTS = dict(_get(clean, "workflow.agents", {}) or {})
        cls.DEFAULT_SCENARIO = _get(clean, "workflow.default_scenario") or "short_film"

    @classmethod
    def as_dict(cls) -> Dict[str, Any]:
        return copy.deepcopy(cls.CONFIG)

    @classmethod
    def as_public_dict(cls) -> Dict[str, Any]:
        return redact_config(cls.CONFIG)

    @classmethod
    def provider_proxy(cls, provider: str) -> str:
        provider_config = _get(cls.CONFIG, f"api_providers.{provider}", {})
        if not isinstance(provider_config, dict) or not _as_bool(provider_config.get("enable_proxy")):
            return ""
        return cls.PROXY or ""

    @classmethod
    def requests_proxies(cls, provider: str) -> Optional[Dict[str, str]]:
        proxy = cls.provider_proxy(provider)
        if not proxy:
            return None
        return {"http": proxy, "https": proxy}

    @classmethod
    def update_config(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """Persist settings-page changes; environment overrides stay out of the file."""
        cls._apply(save_config(merge_config_update(cls.FILE_CONFIG, values)))
        try:
            from models.config_model import reload_model_config

            reload_model_config()
        except ImportError:
            pass
        return cls.as_dict()

    @classmethod
    def check_dirs(cls):
        data_dir = os.path.join(cls.CODE_DIR, "data")
        for directory in [
            cls.CODE_DIR,
            data_dir,
            cls.SESSION_DIR,
            cls.TASK_DIR,
            cls.RESULT_DIR,
            cls.TASK_RESULT_DIR,
            cls.TEMP_DIR,
        ]:
            if not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
                logger.info("Created directory: %s", directory)


Config._apply(Config.FILE_CONFIG)
Config.check_dirs()
settings = Config()
