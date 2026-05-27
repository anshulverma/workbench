from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api", tags=["jobs"])


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request):
    stores = request.app.state.stores
    job = await stores.jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job
