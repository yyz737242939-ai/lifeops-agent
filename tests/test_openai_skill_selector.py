from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from app.runtime.models import RuntimeRequest
from app.skills.errors import SkillSelectionError
from app.skills.models import SkillDefinition
from app.skills.selector import SkillSelectionClient


class SkillSelectionClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.request = RuntimeRequest(
            user_input="Research Tokyo and plan the trip.",
            session_id="session_test",
        )
        self.metadata = (
            SkillDefinition("research", "Research sources.", Path("research")),
            SkillDefinition("travel", "Plan travel.", Path("travel")),
        )

    @patch("app.skills.selector.load_dotenv")
    @patch("app.skills.selector.OpenAI")
    def test_reads_provider_config_and_requests_json_selection(
        self,
        openai_type: Any,
        _load_dotenv: Any,
    ) -> None:
        api = FakeOpenAIClient(
            json.dumps(
                {
                    "selected_skill_ids": ["research", "travel"],
                    "reason": "Both domains apply.",
                }
            )
        )
        openai_type.return_value = api
        with patch.dict(
            "os.environ",
            {
                "OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_BASE_URL": "https://example.test/v1",
                "MODEL": "test-model",
            },
            clear=True,
        ):
            client = SkillSelectionClient()

        result = client.select(self.request, self.metadata)

        openai_type.assert_called_once_with(
            api_key="test-key",
            base_url="https://example.test/v1",
            timeout=30,
            max_retries=0,
        )
        self.assertEqual(result["selected_skill_ids"], ["research", "travel"])
        call = api.chat.completions.calls[0]
        self.assertEqual(call["model"], "test-model")
        self.assertEqual(call["response_format"], {"type": "json_object"})
        input_payload = json.loads(call["messages"][1]["content"])
        self.assertEqual(
            [item["skill_id"] for item in input_payload["skills"]],
            ["research", "travel"],
        )
        self.assertNotIn("body", str(input_payload))

    @patch("app.skills.selector.load_dotenv")
    @patch("app.skills.selector.OpenAI")
    def test_empty_provider_output_is_a_typed_failure(
        self,
        openai_type: Any,
        _load_dotenv: Any,
    ) -> None:
        openai_type.return_value = FakeOpenAIClient(None)
        with patch.dict(
            "os.environ",
            {
                "OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_BASE_URL": "https://example.test/v1",
                "MODEL": "test-model",
            },
            clear=True,
        ):
            client = SkillSelectionClient()

        with self.assertRaises(SkillSelectionError) as caught:
            client.select(self.request, self.metadata)

        self.assertEqual(caught.exception.code, "skill_selection_empty_response")


class FakeCompletions:
    def __init__(self, content: str | None) -> None:
        self._content = content
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self._content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeOpenAIClient:
    def __init__(self, content: str | None) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(content))


if __name__ == "__main__":
    unittest.main()
