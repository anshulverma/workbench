import asyncio
from fastapi import APIRouter, Request
from pydantic import BaseModel
from server.models import JobTrigger

router = APIRouter(prefix="/api", tags=["process"])


class ProcessRequest(BaseModel):
    text: str
    source_type: str = "manual"


@router.post("/process")
async def process(req: ProcessRequest, request: Request):
    pipeline = request.app.state.pipeline
    # Run pipeline in background so the endpoint returns immediately
    job = await pipeline.process(req.text, req.source_type, JobTrigger.MANUAL)
    return {"job_id": job.id, "status": job.status.value}
