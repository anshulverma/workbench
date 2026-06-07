from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api", tags=["jobs"])


@router.get("/jobs")
async def list_jobs(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
):
    stores = request.app.state.stores
    jobs = await stores.jobs.list_jobs(limit=limit, offset=offset, status=status)
    total = await stores.jobs.count_jobs(status=status)
    return {"jobs": jobs, "total": total, "limit": limit, "offset": offset}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request):
    stores = request.app.state.stores
    job = await stores.jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job
