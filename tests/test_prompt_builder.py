import unittest

from app.prompts.prompt_builder import build_system_prompt
from app.skills.skill_loader import discover_skills


class PromptBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skills = discover_skills()

    def test_loads_only_selected_skill_body(self) -> None:
        result = build_system_prompt("列出我的待办任务", self.skills)

        self.assertEqual(result.loaded_skills, ("todo",))
        self.assertIn("Loaded skill: todo", result.instructions)
        self.assertNotIn("Loaded skill: finance", result.instructions)
        self.assertIn("Available skills (metadata only):", result.instructions)

    def test_core_fallback_still_exposes_ref_behavior(self) -> None:
        result = build_system_prompt("把刚才引用的明细展开", self.skills)

        self.assertEqual(result.loaded_skills, ())
        self.assertTrue(result.routing.fallback_used)
        self.assertIn("Call read_context_ref", result.instructions)

    def test_finance_skill_adds_domain_ref_guidance(self) -> None:
        result = build_system_prompt("列出所有消费明细", self.skills)

        self.assertEqual(result.loaded_skills, ("finance",))
        self.assertIn("exact dates, descriptions, ids", result.instructions)


if __name__ == "__main__":
    unittest.main()
