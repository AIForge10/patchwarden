"""List configured Nebius models, then send one cheap test message.

    python -m patchwarden.scripts.model_probe
    make probe
"""

import sys

from patchwarden import config
from patchwarden.agent.nebius_client import ModelUnavailable, chat, healthcheck_model


def main() -> None:
    if not config.NEBIUS_API_KEY or not config.NEBIUS_BASE_URL:
        sys.exit("Fill NEBIUS_API_KEY and NEBIUS_BASE_URL in .env first.")
    try:
        check = healthcheck_model()
    except ModelUnavailable as error:
        sys.exit(str(error))

    print("Configured models:")
    for name, info in check["models"].items():
        mark = "available" if info["available"] else "MISSING"
        print(f"  {name}: {info['id']} ({mark})")
    if not check["ok"]:
        sys.exit("A configured model ID is not available to this key.")
    if not config.NEBIUS_MODEL_REASONING:
        sys.exit("Set NEBIUS_MODEL_REASONING in .env first.")

    print(f"\nSending one test message to {config.NEBIUS_MODEL_REASONING} ...")
    reply = chat("Reply with the single word: ready", max_tokens=20, use_cache=False)
    print("Model replied:", reply)


if __name__ == "__main__":
    main()
