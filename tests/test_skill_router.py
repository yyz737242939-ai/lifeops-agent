import unittest

from app.skills.skill_loader import discover_skills
from app.skills.skill_router import route_skills


class SkillRouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skills = discover_skills()

    def assert_routes(self, user_input: str, expected: set[str]) -> None:
        decision = route_skills(user_input, self.skills)
        self.assertEqual(set(decision.selected), expected)
        self.assertFalse(decision.fallback_used)

    def test_routes_single_domain(self) -> None:
        self.assert_routes("提醒我明天完成 Agent 笔记", {"todo"})
        self.assert_routes("我昨晚只睡了 5 小时，今天能量低", {"wellbeing"})
        self.assert_routes("我今天花了 35 元吃饭，记一笔", {"finance"})
        self.assert_routes("推荐一个不花钱的恢复活动", {"activity"})

    def test_routes_cross_domain_request(self) -> None:
        decision = route_skills(
            "我昨晚只睡了5小时，今天能量低。这周餐饮预算紧，还有重要任务。"
            "帮我安排今天计划，并推荐一个不花钱的恢复活动。",
            self.skills,
        )

        self.assertEqual(
            set(decision.selected),
            {"wellbeing", "finance", "todo", "activity"},
        )
        self.assertTrue(all(decision.reasons.values()))

    def test_does_not_treat_budget_report_task_as_finance(self) -> None:
        self.assert_routes("提醒我明天完成预算报告任务", {"todo"})

    def test_uses_core_fallback_when_no_skill_matches(self) -> None:
        decision = route_skills("你好，介绍一下自己", self.skills)

        self.assertEqual(decision.selected, ())
        self.assertTrue(decision.fallback_used)


if __name__ == "__main__":
    unittest.main()
