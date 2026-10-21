"""Step 1: list the models your Nebius key can use, then send one test message.
 
Run from the project root:  python scripts/model_probe.py
"""
import sys
from pathlib import Path
 
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
 
from openai import OpenAI
 
import config
 
 
def main() -> None:
    if not config.NEBIUS_API_KEY or not config.NEBIUS_BASE_URL:
        sys.exit("Fill NEBIUS_API_KEY and NEBIUS_BASE_URL in .env first.")
 
    client = OpenAI(api_key=config.NEBIUS_API_KEY, base_url=config.NEBIUS_BASE_URL)
 
    print("Models available to your key:")
    for model in client.models.list():
        print("  ", model.id)
 
    model_id = config.NEBIUS_MODEL_REASONING
    if not model_id:
        sys.exit("\nNow copy one NVIDIA Nemotron ID from the list above into "
                 "NEBIUS_MODEL_REASONING in .env, then run this again.")
 
    print(f"\nSending one test message to {model_id} ...")
    reply = client.chat.completions.create(
        model=model_id,
        messages=[{"role": "user", "content": "Reply with the single word: ready"}],
        max_tokens=20,
    )
    print("Model replied:", reply.choices[0].message.content)
 
 
if __name__ == "__main__":
    main()
 