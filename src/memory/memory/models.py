from datetime import datetime, timezone
from pydantic import BaseModel, Field


class Fact(BaseModel):
    content: str
    source: str = "graphiti"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TriageRecordRequest(BaseModel):
    card: dict
    response: dict


class PreferenceQueryResponse(BaseModel):
    facts: list[Fact] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    neo4j: str
    postgres: str
    graphiti: str


class FactsListResponse(BaseModel):
    facts: list[Fact] = Field(default_factory=list)
    total: int = 0
