"""Central place to read settings from environment variables.

Placeholder until the pydantic-settings `Settings` class from the plan (section 5) is built.
"""
import os

from dotenv import load_dotenv

load_dotenv()

NEBIUS_API_KEY = os.getenv("NEBIUS_API_KEY", "")
NEBIUS_BASE_URL = os.getenv("NEBIUS_BASE_URL", "")
NEBIUS_MODEL_ID = os.getenv("NEBIUS_MODEL_ID", "")

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
E2B_API_KEY = os.getenv("E2B_API_KEY", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_OWNER = os.getenv("GITHUB_OWNER", "")
GITHUB_TARGET_REPO = os.getenv("GITHUB_TARGET_REPO", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
ALLOWED_REPO_URL = os.getenv("ALLOWED_REPO_URL", "")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./resolveloop.db")
MAX_PATCH_ATTEMPTS = int(os.getenv("MAX_PATCH_ATTEMPTS", "3"))
MAX_SCENARIOS = int(os.getenv("MAX_SCENARIOS", "4"))
SANDBOX_TIMEOUT_SECONDS = int(os.getenv("SANDBOX_TIMEOUT_SECONDS", "180"))
RUN_DISCOVERY = os.getenv("RUN_DISCOVERY", "true").lower() == "true"
OPEN_PR_ON_VERIFIED = os.getenv("OPEN_PR_ON_VERIFIED", "true").lower() == "true"
