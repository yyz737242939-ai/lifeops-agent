import os

from dotenv import load_dotenv


load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL")

LLM_MODEL = os.getenv("MODEL", "deepseek/deepseek-v4-flash")
LLM_TEMPERATURE = 0.3
LLM_MAX_OUTPUT_TOKENS = 1000
LLM_REQUEST_TIMEOUT = 30
LLM_MAX_RETRIES = 3
