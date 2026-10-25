"""Send a signed, local demo alert to a running ResolveLoop API."""

import argparse
import hashlib
import hmac
from pathlib import Path

import httpx

from resolveloop import config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8000/webhooks/incident")
    args = parser.parse_args()
    body = args.fixture.read_bytes()
    signature = hmac.new(config.WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    response = httpx.post(
        args.url,
        content=body,
        headers={"X-ResolveLoop-Signature": f"sha256={signature}"},
        timeout=10,
    )
    response.raise_for_status()
    print(response.json())


if __name__ == "__main__":
    main()
