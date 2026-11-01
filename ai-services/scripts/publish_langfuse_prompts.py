"""Publish the shipped prompt texts to the production label once."""

from app.agent.implementations.business_agent import _SYSTEM_PROMPT
from app.agent.memory.langmem_extractor import _INSTRUCTIONS
from app.agent.prompts import MEMORY_PROMPT, SALES_PROMPT, _client
from app.configs import get_settings


def main() -> None:
    settings = get_settings()
    if not all((settings.langfuse_public_key, settings.langfuse_secret_key,
                settings.langfuse_base_url)):
        raise RuntimeError("Set LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and LANGFUSE_BASE_URL")
    client = _client()
    for name, content in ((SALES_PROMPT, _SYSTEM_PROMPT),
                          (MEMORY_PROMPT, _INSTRUCTIONS)):
        try:
            existing = client.get_prompt(name, type="text", label="production",
                                         max_retries=0, fetch_timeout_seconds=3)
        except Exception:
            existing = None
        if existing is not None:
            print(f"Already managed: {name} version {existing.version}")
            continue
        prompt = client.create_prompt(name=name, type="text", prompt=content,
                                      labels=["production"],
                                      commit_message="Migrate current code prompt")
        print(f"Published {name} version {prompt.version}")


if __name__ == "__main__":
    main()
