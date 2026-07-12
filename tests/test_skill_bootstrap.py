from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from app.runtime.bootstrap import build_runtime_service
from app.runtime.models import RuntimeRequest
from app.skills.models import SkillDefinition


class SkillBootstrapTest(unittest.TestCase):
    @patch("app.runtime.bootstrap.OpenAIToolCallSelectionClient")
    @patch("app.runtime.bootstrap.SkillSelectionClient")
    def test_bootstrap_discovers_skills_and_builds_default_selection_client(
        self,
        selection_client_type: Any,
        tool_call_client_type: Any,
    ) -> None:
        client = RecordingSelectionClient()
        selection_client_type.return_value = client
        tool_call_client_type.return_value = NoToolCallSelectionClient()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skill_root = root / "skills"
            skill_dir = skill_root / "research"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: research\ndescription: Research sources.\n---\n# Research",
                encoding="utf-8",
            )
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "database": {"path": ":memory:"},
                        "logs": {"root": str(root / "logs")},
                        "skills": {"root": str(skill_root)},
                    }
                ),
                encoding="utf-8",
            )
            runtime = build_runtime_service(config_path)
            try:
                runtime.handle(
                    RuntimeRequest(
                        user_input="把研究资料加入任务",
                        session_id="session_test",
                    )
                )
            finally:
                runtime.close()
                self._close_application_handlers()

        selection_client_type.assert_called_once_with()
        self.assertTrue(client.called)
        self.assertEqual(
            tuple(item.skill_id for item in client.received_metadata),
            ("research",),
        )

    @staticmethod
    def _close_application_handlers() -> None:
        logger = logging.getLogger("lifeops")
        for handler in list(logger.handlers):
            if isinstance(handler, logging.FileHandler):
                handler.close()
                logger.removeHandler(handler)


class RecordingSelectionClient:
    def __init__(self) -> None:
        self.called = False
        self.received_metadata: tuple[SkillDefinition, ...] = ()

    def select(
        self,
        request: RuntimeRequest,
        skill_metadata: tuple[SkillDefinition, ...],
    ) -> dict[str, Any]:
        self.called = True
        self.received_metadata = skill_metadata
        return {
            "selected_skill_ids": ["research"],
            "reason": "Research request.",
        }


class NoToolCallSelectionClient:
    def select(self, request, prompt_contributions, tool_catalog):
        return None


if __name__ == "__main__":
    unittest.main()
