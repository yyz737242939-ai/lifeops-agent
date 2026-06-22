import unittest

from app.skills.skill_state import resolve_skill_state


class SkillStateTests(unittest.TestCase):
    def test_direct_selection_becomes_active_without_inheritance(self) -> None:
        result = resolve_skill_state(
            "检查本周预算",
            directly_selected=("finance",),
            previous_active_skills=("todo",),
        )

        self.assertEqual(result.directly_selected, ("finance",))
        self.assertEqual(result.inherited_skills, ())
        self.assertEqual(result.loaded_skills, ("finance",))
        self.assertEqual(result.next_active_skills, ("finance",))
        self.assertEqual(result.resolution, "direct_selection")

    def test_ambiguous_followup_inherits_previous_skill(self) -> None:
        result = resolve_skill_state(
            "完成第一个",
            directly_selected=(),
            previous_active_skills=("todo",),
        )

        self.assertEqual(result.directly_selected, ())
        self.assertEqual(result.inherited_skills, ("todo",))
        self.assertEqual(result.loaded_skills, ("todo",))
        self.assertEqual(result.next_active_skills, ("todo",))
        self.assertTrue(result.inheritance_used)
        self.assertEqual(result.resolution, "ambiguous_followup_inherited")

    def test_explicit_domain_signal_wins_over_continuation_word(self) -> None:
        result = resolve_skill_state(
            "继续检查预算",
            directly_selected=("finance",),
            previous_active_skills=("todo",),
        )

        self.assertEqual(result.loaded_skills, ("finance",))
        self.assertEqual(result.inherited_skills, ())

    def test_cross_domain_state_is_inherited_as_a_deduplicated_group(self) -> None:
        result = resolve_skill_state(
            "继续刚才那个",
            directly_selected=(),
            previous_active_skills=("todo", "finance", "todo"),
        )

        self.assertEqual(result.inherited_skills, ("todo", "finance"))
        self.assertEqual(result.loaded_skills, ("todo", "finance"))

    def test_context_ref_uses_common_tools_without_loading_domain_skill(self) -> None:
        result = resolve_skill_state(
            "把刚才引用的完整结果展开",
            directly_selected=(),
            previous_active_skills=("finance",),
        )

        self.assertEqual(result.loaded_skills, ())
        self.assertEqual(result.inherited_skills, ())
        self.assertEqual(result.next_active_skills, ("finance",))
        self.assertFalse(result.inheritance_used)
        self.assertEqual(result.resolution, "context_ref_only")

    def test_unrelated_turn_clears_active_state(self) -> None:
        result = resolve_skill_state(
            "你好，介绍一下自己",
            directly_selected=(),
            previous_active_skills=("todo",),
        )

        self.assertEqual(result.loaded_skills, ())
        self.assertEqual(result.next_active_skills, ())
        self.assertTrue(result.state_cleared)
        self.assertEqual(result.resolution, "no_domain_or_continuation")

    def test_followup_without_active_skill_uses_fallback(self) -> None:
        result = resolve_skill_state(
            "继续",
            directly_selected=(),
            previous_active_skills=(),
        )

        self.assertEqual(result.loaded_skills, ())
        self.assertFalse(result.inheritance_used)
        self.assertEqual(result.resolution, "followup_without_active_skill")


if __name__ == "__main__":
    unittest.main()
