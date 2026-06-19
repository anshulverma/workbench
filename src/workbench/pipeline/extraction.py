from workbench.providers.llm.base import LLMProvider
from workbench.providers.llm.context import llm_call_context
from workbench.domain import ExtractedItem


async def extract_items(
    llm: LLMProvider, raw_text: str, source_type: str, *, root_path: str | None = None
) -> list[ExtractedItem]:
    if not raw_text or len(raw_text.strip()) < 10:
        return []
    with llm_call_context(
        origin="extract",
        purpose="extract",
        stage="extract",
        item_paths=((root_path,) if root_path else ()),
    ):
        return await llm.extract(raw_text, source_type)
