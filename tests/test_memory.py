import asyncio
from server.memory.noop import NoopMemoryLayer


def test_noop_memory_returns_empty():
    async def _test():
        memory = NoopMemoryLayer()
        assert await memory.query_preferences("any context") == []
        assert await memory.query_entity("diff", "D123") is None
        assert await memory.query_relationships("D123") == []
        assert await memory.is_available() is False

    asyncio.run(_test())
