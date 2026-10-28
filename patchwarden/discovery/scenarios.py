"""Model-chosen challenge scenarios, constrained to the trusted catalog. Owner: Satyabrata."""

import json

from pydantic import ValidationError

from patchwarden.agent.nebius_client import chat_full
from patchwarden.agent.prompts import SCENARIO_SYSTEM, build_scenario_prompt
from patchwarden.models import ScenarioSpec

from .catalog import validate_scenario


def parse_scenarios(reply_text: str) -> list[dict]:
    """The last JSON array in the reply (models sometimes quote an example first)."""
    decoder, found, start = json.JSONDecoder(), [], reply_text.find("[")
    while start != -1:
        try:
            items, end = decoder.raw_decode(reply_text, start)
        except json.JSONDecodeError:
            start = reply_text.find("[", start + 1)
            continue
        if isinstance(items, list):
            found = [item for item in items if isinstance(item, dict)]
        start = reply_text.find("[", end)
    return found


def propose_scenarios(
    incident, patch, catalog: dict, max_count: int
) -> tuple[list[ScenarioSpec], list[str]]:
    """LLM selects catalog scenarios; deterministic validation and dedupe decide what runs.

    Returns (accepted specs, reasons for each rejected proposal). Nothing the model
    writes is executed: only a catalog ID plus bounded parameters reach the trusted runner.
    """
    if max_count <= 0:
        return [], []
    reply = chat_full(
        build_scenario_prompt(incident, patch, catalog), system=SCENARIO_SYSTEM, max_tokens=2000
    )
    accepted, rejected, seen = [], [], set()
    for item in parse_scenarios(reply.text):
        try:
            spec = ScenarioSpec.model_validate(item)
            validate_scenario(spec, catalog)
        except (ValidationError, ValueError, TypeError) as error:
            rejected.append(f"{item.get('scenario_id', '?')}: {error}")
            continue
        key = (spec.scenario_id, spec.invariant_id, json.dumps(spec.params, sort_keys=True))
        if key not in seen:
            seen.add(key)
            accepted.append(spec)
    return accepted[:max_count], rejected
