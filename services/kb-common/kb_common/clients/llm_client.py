from openai import AsyncOpenAI
from kb_common.config import get_settings

def _client(base_url: str | None = None, api_key: str | None = None) -> AsyncOpenAI:
    s = get_settings()
    return AsyncOpenAI(base_url=base_url or s.llm_base_url,
                       api_key=api_key or s.llm_api_key or "empty")

async def chat(messages: list[dict], model: str | None = None,
               base_url: str | None = None, api_key: str | None = None) -> str:
    s = get_settings()
    resp = await _client(base_url, api_key).chat.completions.create(
        model=model or s.llm_model, messages=messages, temperature=0.2)
    return resp.choices[0].message.content or ""
