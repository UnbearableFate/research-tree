"""Model names are normalized at the public configuration boundary."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import project_config


class ModelNamesTest(unittest.TestCase):
    def test_display_names_for_all_current_roles(self):
        for version in (3,):
            for role in ("ui", "worker", "architect", "explorer", "analyst"):
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
                config = project_config.parse(json.dumps({"version": 3, "models": {"ui": {"model": name}}}))
                self.assertEqual(config["models"]["ui"], {"model": name, "effort": None})
        self.assertEqual(project_config.parse("version: 3")["models"], project_config.defaults()["models"])

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
                config = project_config.parse(json.dumps({"version": 3, "models": {"reviewer": {"model": display}}}))
                self.assertEqual(config["models"]["reviewer"]["model"], model)
                self.assertEqual(config["models"]["reviewer"]["thinking"], "high")

    def test_invalid_names_types_and_effort_still_fail_validation(self):
        for spec in (None, {"model": None}, {"model": 5}, {"model": "Unknown Model"},
                     {"model": "Haiku 5; echo bad"}, {"model": ""},
                     {"model": "GPT 6; echo bad"},
                     {"model": "Haiku 5", "effort": "bogus"}):
            with self.subTest(spec=spec):
                with self.assertRaises(project_config.ConfigError):
                    project_config.parse(json.dumps({"version": 3, "models": {"ui": spec}}))


class CurrentConfigTest(unittest.TestCase):
    def test_explicit_current_version_and_single_workflow(self):
        config = project_config.parse("version: 3")
        self.assertEqual(config, project_config.parse(project_config.template_text()))
        for removed in ("workflow", "discovery", "literature", "review", "stage1"):
            self.assertNotIn(removed, config)
        self.assertEqual(set(config["models"]), {"ui", "worker", "architect", "explorer", "analyst", "reviewer"})
        self.assertEqual(project_config.protocol_requirements(config)["profile"], "stage1_confirmed")

    def test_older_missing_and_future_versions_fail_with_migration_notice(self):
        for text in ("", "{}", "version: 1", "version: 2", "version: 4", "version: true", 'version: "3"'):
            with self.subTest(text=text), self.assertRaisesRegex(project_config.ConfigError,
                                                                "UNSUPPORTED_CONFIG_VERSION.*new project"):
                project_config.parse(text)

    def test_removed_modes_and_inactive_knobs_are_rejected(self):
        sections = {"workflow": {"mode": "strict"}, "discovery": {"mode": "full"},
                    "stage1": {"gate_seeds": 3}, "literature": {"min_related_work": 3},
                    "review": {"trigger": "candidate_ready"}, "models": {"lens_assistant": {"model": "inherit"}},
                    "design": {"max_primary_claims": 2}, "evidence_policy": {"profile": "screening"},
                    "verification": {"allow_inconclusive_at_limit": False},
                    "budget": {"reserve_from_scheduler_limits": False}, "memory": {"cross_project": False}}
        for section, fields in sections.items():
            with self.subTest(section=section), self.assertRaisesRegex(project_config.ConfigError, "unsupported"):
                project_config.parse(json.dumps({"version": 3, section: fields}))
        for mode in ("strict", "fast_screening"):
            with self.subTest(mode=mode), self.assertRaises(project_config.ConfigError):
                project_config.parse(json.dumps({"version": 3, "workflow": {"mode": mode}}))
        for mode in ("off", "precheck", "full", "incremental"):
            with self.subTest(mode=mode), self.assertRaises(project_config.ConfigError):
                project_config.parse(json.dumps({"version": 3, "discovery": {"mode": mode}}))

    def test_active_advanced_verification_and_zero_repair_budget_survive(self):
        config = project_config.parse(json.dumps({"version": 3, "search": {"max_repairs_per_root_cause": 0},
            "verification": {"independence_fields": ["training_seed"],
                             "repetition": {"enabled": True, "seed_pool": [43, 44], "batch": 1}}}))
        fields = project_config.protocol_requirements(config)
        self.assertEqual(fields["independence_fields"], ["training_seed"])
        self.assertEqual(fields["repetition"], {"enabled": True, "seed_pool": [43, 44], "batch": 1,
                                                "se_multiple": 2.0})
        self.assertEqual(project_config.db_fields(config)["max_repairs_per_root_cause"], 0)

    def test_bad_advanced_verification_fails_before_project_creation(self):
        for fields in ({"repetition": {"enabled": True, "seed_pool": [9000]}},
                       {"repetition": {"enabled": True, "seed_pool": [43, 43]}},
                       {"repetition": {"enabled": True, "auto": True}},
                       {"confirmation_seeds": [42, 43, 44]}, {"independence_fields": [""]}):
            with self.subTest(fields=fields), self.assertRaises(project_config.ConfigError):
                project_config.parse(json.dumps({"version": 3, "verification": fields}))

    def test_metric_and_budget_integrity_still_checked(self):
        for fields in ({"metric_specs": [{"name": "acc"}]},
                       {"verification": {"screening_seeds": [42], "replication_seeds": [42]}},
                       {"budget": {"search_limit": 100}},
                       {"budget": {"total_limit": 100, "search_limit": 80, "confirmation_limit": 30}}):
            with self.subTest(fields=fields), self.assertRaises(project_config.ConfigError):
                project_config.parse(json.dumps({"version": 3, **fields}))


if __name__ == "__main__":
    unittest.main()
