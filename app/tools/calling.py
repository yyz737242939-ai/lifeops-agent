"""Direct single-Tool selection through an OpenAI-compatible Responses API."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from dotenv import load_dotenv
from openai import OpenAI

from app.runtime.models import RuntimeRequest
from app.skills.models import PromptContribution
from app.tools.errors import ToolGatewayError
from app.tools.models import ToolCall


class ToolCallSelectionClient(Protocol):
    """Port used by Direct Executor to select zero or one ToolCall."""

    def select(
        self,
        request: RuntimeRequest,
        prompt_contributions: Sequence[PromptContribution],
        tool_catalog: Sequence[Mapping[str, Any]],
    ) -> ToolCall | None:
        ...


class OpenAIToolCallSelectionClient:
    """Expose only the supplied catalog and parse one Responses function call."""

    def __init__(self) -> None:
        load_dotenv()
        api_key = os.getenv("OPENROUTER_API_KEY")
        base_url = os.getenv("OPENROUTER_BASE_URL")
        model = os.getenv("MODEL", "deepseek/deepseek-v4-flash")
        if not api_key or not base_url or not model:
            raise ToolGatewayError(
                "Tool calling LLM configuration is incomplete.",
                code="tool_calling_config_invalid",
            )
        self._model = model
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=30,
            max_retries=0,
        )

    def select(
        self,
        request: RuntimeRequest,
        prompt_contributions: Sequence[PromptContribution],
        tool_catalog: Sequence[Mapping[str, Any]],
    ) -> ToolCall | None:
        """Ask the model for at most one function call from the filtered catalog."""

        tools = [
            {
                "type": "function",
                "name": item["name"],
                "description": item["description"],
                "parameters": item["input_schema"],
                "strict": True,
            }
            for item in tool_catalog
        ]
        instructions = "\n\n".join(
            contribution.instructions for contribution in prompt_contributions
        )
        response = self._client.responses.create(
            model=self._model,
            instructions=(
                "Choose at most one supplied function when it can directly satisfy "
                "the request. Never invent a function or argument."
                + (f"\n\nSelected Skill instructions:\n{instructions}" if instructions else "")
            ),
            input=request.user_input,
            tools=tools,
            tool_choice="auto",
            parallel_tool_calls=False,
            max_tool_calls=1,
        )
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            return None
        if len(calls) != 1:
            raise ToolGatewayError(
                "Direct Executor received more than one ToolCall.",
                code="tool_calling_multiple_calls",
            )
        selected = calls[0]
        try:
            arguments = json.loads(selected.arguments)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ToolGatewayError(
                "Tool calling arguments are not valid JSON.",
                code="tool_calling_invalid_arguments",
            ) from exc
        if not isinstance(arguments, dict):
            raise ToolGatewayError(
                "Tool calling arguments must be an object.",
                code="tool_calling_invalid_arguments",
            )
        return ToolCall(
            call_id=selected.call_id,
            tool_name=selected.name,
            arguments=arguments,
        )
