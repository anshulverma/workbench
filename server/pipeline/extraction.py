from server.providers.llm.base import LLMProvider
from server.models import ExtractedItem

async def extract_items(llm: LLMProvider, raw_text: str, source_type: str) -> list[ExtractedItem]:
    if not raw_text or len(raw_text.strip()) < 10:
        return []
    return await llm.extract(raw_text, source_type)
