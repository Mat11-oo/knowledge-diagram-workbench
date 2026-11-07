import asyncio
import json
import os
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from config import settings
from core.agents.base_agent import AgentInterface
from core.orchestrator import WorkflowEngine
from core.scenarios import SCENARIOS_DIR, ScenarioError, ScenarioRegistry, parse_scenario


class EchoAgent(AgentInterface):
    """Custom stage agent used by the test scenario: echoes the prompt it loaded."""

    async def process(self, input_data, intervention=None):
        return {
            "payload": {"text": self._prompt("script", "generate_script"), "scenario": self.scenario.get("id")},
            "requires_intervention": True,
        }


POSTER_YAML = """
name: Test Poster
category: image
defaults:
  video_ratio: "3:4"
stages:
  - type: script_generation
    name: 海报文案
  - type: character_design
  - type: storyboard
  - type: reference_generation
    name: 海报生成
"""

CUSTOM_YAML = """
name: Custom
stages:
  - id: review
    name: 审核
    agent: tests.test_scenarios:EchoAgent
"""


def _write_scenario(root: Path, scenario_id: str, body: str, prompts: dict = None) -> None:
    folder = root / scenario_id
    folder.mkdir(parents=True)
    (folder / "scenario.yaml").write_text(textwrap.dedent(body), encoding="utf-8")
    for rel, text in (prompts or {}).items():
        path = folder / "prompts" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class BundledScenarioTests(unittest.TestCase):
    def test_bundled_scenarios_are_valid(self):
        registry = ScenarioRegistry(SCENARIOS_DIR)
        self.assertEqual(registry.errors, {})
        ids = [s.id for s in registry.list()]
        self.assertEqual(ids[0], "short_film")
        # 学生新增的场景包也会被加载，这里只检查内置示例都在
        self.assertTrue({"short_film", "ecommerce_ad", "comic_drama", "travel_promo", "product_poster"} <= set(ids))
        self.assertFalse(registry.get("product_poster").needs_video_model)

    def test_short_film_keeps_the_original_six_stages(self):
        scenario = ScenarioRegistry(SCENARIOS_DIR).get("short_film")
        self.assertEqual(scenario.stage_ids, [
            "script_generation", "character_design", "storyboard",
            "reference_generation", "video_generation", "post_production",
        ])
        self.assertTrue(scenario.needs_video_model)


class ScenarioPromptOverrideTests(unittest.TestCase):
    """A scenario prompt replaces a default prompt, so it may only use the placeholders the agent fills in."""

    def test_overrides_use_only_known_placeholders_and_format_cleanly(self):
        import string
        from prompts.loader import PROMPTS_DIR

        formatter = string.Formatter()
        fields = lambda text: {name for _, name, _, _ in formatter.parse(text) if name}
        checked = 0
        for scenario in ScenarioRegistry(SCENARIOS_DIR).list():
            for prompt_dir in scenario.prompt_dirs:
                for root, _, files in os.walk(prompt_dir):
                    for filename in files:
                        path = os.path.join(root, filename)
                        rel = os.path.relpath(path, prompt_dir)
                        default = os.path.join(PROMPTS_DIR, rel)
                        if rel.startswith("style" + os.sep) or not os.path.exists(default):
                            continue
                        text = Path(path).read_text(encoding="utf-8")
                        allowed = fields(Path(default).read_text(encoding="utf-8"))
                        with self.subTest(scenario=scenario.id, prompt=rel):
                            self.assertLessEqual(fields(text), allowed)
                            text.format(**{name: "x" for name in allowed})
                        checked += 1
        self.assertGreater(checked, 0)


class ScenarioValidationTests(unittest.TestCase):
    def assertInvalid(self, data, message):
        with self.assertRaises(ScenarioError) as ctx:
            parse_scenario(data, "bad")
        self.assertIn(message, str(ctx.exception))

    def test_rejects_bad_declarations(self):
        self.assertInvalid({"stages": []}, "non-empty")
        self.assertInvalid({"stages": [{"type": "nope"}]}, "unknown stage type")
        self.assertInvalid({"stages": ["script_generation", "script_generation"]}, "duplicate")
        self.assertInvalid({"stages": ["storyboard"]}, "needs 'script_generation'")
        self.assertInvalid({"stages": [{"id": "review"}]}, "needs an `agent`")
        self.assertInvalid({"stages": ["script_generation"], "defaults": {"foo": 1}}, "unsupported defaults")

    def test_image_scenario_needs_no_video_model(self):
        import yaml
        scenario = parse_scenario(yaml.safe_load(POSTER_YAML), "poster")
        self.assertFalse(scenario.needs_video_model)
        self.assertEqual(scenario.next_stage("storyboard"), "reference_generation")
        self.assertIsNone(scenario.next_stage("reference_generation"))

    def test_invalid_package_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_scenario(root, "poster", POSTER_YAML)
            _write_scenario(root, "broken", "stages: [storyboard]")
            registry = ScenarioRegistry(str(root))
            self.assertEqual([s.id for s in registry.list()], ["poster"])
            self.assertIn("broken", registry.errors)


class EngineScenarioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        _write_scenario(root / "scenarios", "poster", POSTER_YAML)
        _write_scenario(root / "scenarios", "custom", CUSTOM_YAML, {"script/generate_script_zh.txt": "场景覆盖的提示词"})
        _write_scenario(root / "scenarios", "short_film", (Path(SCENARIOS_DIR) / "short_film" / "scenario.yaml").read_text("utf-8"))
        self.session_dir = root / "sessions"
        self.session_dir.mkdir()
        patcher = patch.object(settings, "SESSION_DIR", str(self.session_dir))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.engine = WorkflowEngine(ScenarioRegistry(str(root / "scenarios")))

    def test_session_uses_scenario_stage_list(self):
        session = self.engine.create_session("s1", {"scenario": "poster", "idea": "x"})
        self.assertEqual(session["scenario"], "poster")
        self.assertEqual(list(session["status"]), ["script_generation", "character_design", "storyboard", "reference_generation"])
        state = self.engine.get_state("s1")
        self.assertEqual(self.engine._get_next_stage(state, "init"), "script_generation")
        self.assertIsNone(self.engine._get_next_stage(state, "reference_generation"))

    def test_storyboard_sync_skips_stages_missing_from_scenario(self):
        self.engine.create_session("s2", {"scenario": "poster"})
        state = self.engine.get_state("s2")
        storyboard = {"episodes": [{"episode_number": 1, "segments": [{"segment_id": "seg_01_01", "shots": [{"plot": "p", "duration": 5}]}]}]}
        self.engine._sync_artifacts_cross_stages(state, "storyboard", storyboard)
        self.assertIn("reference_generation", state.artifacts)
        self.assertNotIn("video_generation", state.artifacts)

    def test_custom_stage_runs_its_agent_with_scenario_prompts(self):
        self.engine.create_session("s3", {"scenario": "custom"})
        state = self.engine.get_state("s3")
        result = asyncio.run(self.engine.execute_stage(state, "review", {}))
        self.assertEqual(result["payload"], {"text": "场景覆盖的提示词", "scenario": "custom"})
        self.assertEqual(state.status["review"], "waiting")
        with self.assertRaises(ValueError):
            asyncio.run(self.engine.execute_stage(state, "storyboard", {}))

    def test_legacy_session_without_scenario_loads_as_default(self):
        legacy = {
            "session_id": "old",
            "current_stage": "storyboard",
            "status": {"script_generation": "completed", "storyboard": "waiting", "init": "completed"},
            "artifacts": {},
            "meta": {"idea": "old idea"},
        }
        (self.session_dir / "old.json").write_text(json.dumps(legacy), encoding="utf-8")
        engine = WorkflowEngine(self.engine.scenarios)
        snapshot = engine.get_status_snapshot("old")
        self.assertEqual(snapshot["scenario"], "short_film")
        self.assertEqual(snapshot["status"]["storyboard"], "waiting")
        self.assertEqual(len(snapshot["stages"]), 6)
        self.assertTrue(os.path.exists(self.session_dir / "old.json"))


if __name__ == "__main__":
    unittest.main()
