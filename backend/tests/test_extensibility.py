import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

import config
from config import Config, env_overrides, merge_config_update
from core.agents.base_agent import AgentInterface
from core.stages import STAGE_ORDER, WorkflowStage, build_agent_factories, load_agent_class, stage_catalog
from models import config_model


class DummyScriptAgent(AgentInterface):
    async def process(self, input_data, intervention=None):
        return {"payload": {}}


class EnvOverrideTests(unittest.TestCase):
    def test_provider_and_server_env_vars(self):
        overrides = env_overrides({
            "SFA_DASHSCOPE_API_KEY": "sk-env",
            "SFA_KLING_SECRET_KEY": "kling-secret",
            "SFA_PORT": "9001",
            "SFA_MODEL_LLM": "my-llm",
            "UNRELATED": "x",
        })
        self.assertEqual(overrides["api_providers"]["dashscope"]["api_key"], "sk-env")
        self.assertEqual(overrides["api_providers"]["kling"]["secret_key"], "kling-secret")
        self.assertEqual(overrides["server"]["port"], "9001")
        self.assertEqual(overrides["models"]["llm"], "my-llm")

    def test_env_secrets_are_not_written_to_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            original = (Config.FILE_CONFIG, config.CONFIG_PATH)
            try:
                config.CONFIG_PATH = path
                with patch.dict("os.environ", {"SFA_OPENAI_API_KEY": "sk-from-env"}):
                    Config._apply(Config.FILE_CONFIG)
                    self.assertEqual(Config.OPENAI_API_KEY, "sk-from-env")
                    Config.update_config({"generation": {"style": "anime"}})
                saved = yaml.safe_load(path.read_text(encoding="utf-8"))
                self.assertEqual(saved["generation"]["style"], "anime")
                self.assertEqual(saved["api_providers"]["openai"]["api_key"], "")
            finally:
                config.CONFIG_PATH = original[1]
                Config._apply(original[0])

    def test_masked_secret_keeps_file_value(self):
        current = {"api_providers": {"openai_compatible": {"api_key": "sk-real"}}}
        merged = merge_config_update(
            current, {"api_providers": {"openai_compatible": {"api_key": config.SECRET_MASK}}}
        )
        self.assertEqual(merged["api_providers"]["openai_compatible"]["api_key"], "sk-real")


class ModelRegistryTests(unittest.TestCase):
    def tearDown(self):
        config_model.reload_model_config()

    def test_builtin_registry_loads_from_yaml(self):
        self.assertEqual(config_model.resolve_provider("wan2.7-i2v"), "dashscope")
        self.assertEqual(config_model.resolve_provider("not-a-model"), "")

    def test_custom_models_from_config(self):
        custom = {"my-llm": {"name": "My LLM", "provider": "openai_compatible", "type": ["llm"]}}
        with patch.dict(Config.CONFIG, {"custom_models": custom}):
            config_model.reload_model_config()
            self.assertEqual(config_model.resolve_provider("my-llm"), "openai_compatible")
            self.assertIn("my-llm", [m["id"] for m in config_model.get_models_by_type("llm")])

    def test_local_registry_overrides_builtin(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "models.local.yaml"
            local.write_text(yaml.safe_dump({"models": {"wan2.7-i2v": {"concurrency": 1}}}), encoding="utf-8")
            with patch.object(config_model, "LOCAL_REGISTRY_PATH", local):
                config_model.reload_model_config()
                metadata = config_model.get_model_config("wan2.7-i2v")
        self.assertEqual(metadata["concurrency"], 1)
        self.assertEqual(metadata["provider"], "dashscope")


class StageRegistryTests(unittest.TestCase):
    def test_default_stage_order(self):
        self.assertEqual(STAGE_ORDER[0], WorkflowStage.SCRIPT_GENERATION)
        self.assertEqual(STAGE_ORDER[-1], WorkflowStage.POST_PRODUCTION)
        self.assertEqual([s["id"] for s in stage_catalog()], [s.value for s in STAGE_ORDER])

    def test_agent_override(self):
        path = f"{__name__}:DummyScriptAgent"
        factories = build_agent_factories({"script_generation": path})
        self.assertIs(factories[WorkflowStage.SCRIPT_GENERATION], DummyScriptAgent)

    def test_invalid_overrides_are_rejected(self):
        with self.assertRaises(ValueError):
            build_agent_factories({"no_such_stage": f"{__name__}:DummyScriptAgent"})
        with self.assertRaises(TypeError):
            load_agent_class("unittest:TestCase")


if __name__ == "__main__":
    unittest.main()
