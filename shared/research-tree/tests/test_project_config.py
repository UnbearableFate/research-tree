"""Model names are normalized at the public configuration boundary."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import project_config


class ModelNamesTest(unittest.TestCase):
    def test_display_names_in_both_config_versions(self):
        for version in (1, 2):
            for role in (("ui", "worker") if version == 1 else ("ui", "worker", "lens_assistant")):
                for display, model in (
                    ("Haiku 5", "claude-haiku-5-5"),
                    ("  cLaUdE   hAiKu 5.5  ", "claude-haiku-5-5"),
                    ("Sonnet 5.5", "claude-sonnet-5-5"),
                    ("Opus 4.1", "claude-opus-4-1"),
                    ("Claude Sonnet 3.5", "claude-3-5-sonnet"),
                    ("Haiku", "haiku"),
                    ("GPT 6 Sol", "gpt-6-sol"),
                    ("  GPT-6   LuNa  ", "gpt-6-luna"),
                    ("GPT 6.1 Sol", "gpt-6.1-sol"),
                ):
                    with self.subTest(version=version, role=role, display=display):
                        config = project_config.parse(json.dumps({
                            "version": version, "models": {role: {"model": display, "effort": "high"}}}))
                        self.assertEqual(config["models"][role], {"model": model, "effort": "high"})

    def test_ids_and_defaults_are_preserved(self):
        for name in ("inherit", "claude-haiku-5-5", "claude-sonnet-5-5", "gpt-6-sol", "custom-model:v2"):
            with self.subTest(name=name):
                config = project_config.parse(json.dumps({"models": {"ui": {"model": name}}}))
                self.assertEqual(config["models"]["ui"], {"model": name, "effort": None})
        self.assertEqual(project_config.parse("{}")["models"], project_config.defaults()["models"])

    def test_reviewer_provider_is_preserved_or_resolved_for_claude_names(self):
        for display, model in (
            ("Haiku 5", "anthropic/claude-haiku-5-5"),
            ("anthropic/Claude Sonnet 5.5", "anthropic/claude-sonnet-5-5"),
            ("anthropic/claude-sonnet-5-5", "anthropic/claude-sonnet-5-5"),
            ("openai/gpt-6-astra", "openai/gpt-6-astra"),
            ("GPT 6 Astra", "openai/gpt-6-astra"),
            ("openai/GPT 6 Astra", "openai/gpt-6-astra"),
        ):
            with self.subTest(display=display):
                config = project_config.parse(json.dumps({"models": {"reviewer": {"model": display}}}))
                self.assertEqual(config["models"]["reviewer"]["model"], model)
                self.assertEqual(config["models"]["reviewer"]["thinking"], "high")

    def test_invalid_names_types_and_effort_still_fail_validation(self):
        for spec in (None, {"model": None}, {"model": 5}, {"model": "Unknown Model"},
                     {"model": "Haiku 5; echo bad"}, {"model": ""},
                     {"model": "GPT 6; echo bad"},
                     {"model": "Haiku 5", "effort": "bogus"}):
            with self.subTest(spec=spec):
                with self.assertRaises(project_config.ConfigError):
                    project_config.parse(json.dumps({"models": {"ui": spec}}))


if __name__ == "__main__":
    unittest.main()
