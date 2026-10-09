"""Central place to read settings from environment variables."""
import os

from dotenv import load_dotenv

load_dotenv()

NEBIUS_API_KEY = os.getenv("NEBIUS_API_KEY", "")
NEBIUS_BASE_URL = os.getenv("NEBIUS_BASE_URL", "")
NEBIUS_MODEL_REASONING = os.getenv("NEBIUS_MODEL_REASONING", "")
NEBIUS_MODEL_FAST = os.getenv("NEBIUS_MODEL_FAST", "")

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
E2B_API_KEY = os.getenv("E2B_API_KEY", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

MAX_AGENT_ITERATIONS = 5
