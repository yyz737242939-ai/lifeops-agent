from openai import OpenAI

from app.config import (
    LLM_MAX_RETRIES,
    LLM_REQUEST_TIMEOUT,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
)

client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url=OPENROUTER_BASE_URL,
    timeout=LLM_REQUEST_TIMEOUT,
    max_retries=LLM_MAX_RETRIES,
)
