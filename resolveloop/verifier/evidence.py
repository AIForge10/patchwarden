import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


def build_manifest(result, hashes: dict, commands: list[dict]) -> dict:
    patch = result.patch.unified_diff if result.patch else ""
    return {
        "run_id": result.run_id,
        "baseline_sha": result.patch.base_sha if result.patch else "",
        "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
        "protected_test_sha256": hashes,
        "commands": commands,
        "status": result.status.value,
        "verified_at": datetime.now(UTC).isoformat(),
        "limitations": ["Controlled seeded checkout demo"],
    }


def write_evidence_bundle(run_id: str, manifest: dict, directory: str = "evidence") -> str:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{run_id}.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return str(path)


def verify_manifest_integrity(manifest: dict) -> bool:
    expected = manifest.get("patch_sha256")
    patch = manifest.get("patch", "")
    return bool(expected) and (not patch or hashlib.sha256(patch.encode()).hexdigest() == expected)
