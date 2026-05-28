from fastapi import APIRouter, Request
from pydantic import BaseModel
from workbench.models import JobTrigger

router = APIRouter(prefix="/api", tags=["process"])


class ProcessRequest(BaseModel):
    text: str
    source_type: str = "manual"


@router.post("/process")
async def process(req: ProcessRequest, request: Request):
    pipeline = request.app.state.pipeline
    job = await pipeline.enqueue(req.text, req.source_type, trigger=JobTrigger.MANUAL)
    return {"job_id": job.id, "status": job.status.value}
