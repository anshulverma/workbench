"""Feedback API — corrections and filter tuning tasks.

GET  /api/feedback/corrections          — list all corrections (optionally by item_id)
POST /api/feedback/corrections          — add a new correction
DELETE /api/feedback/corrections/{id}   — delete a correction

GET  /api/feedback/tasks                — list tuning tasks (optionally by status)
POST /api/feedback/tasks                — create a tuning task
PATCH /api/feedback/tasks/{id}          — update task status
DELETE /api/feedback/tasks/{id}         — delete a tuning task
"""

from fastapi import APIRouter, HTTPException, Query, Request

from workbench.domain import FeedbackCorrection, FilterTuningTask

router = APIRouter(prefix="/api", tags=["feedback"])


def _get_feedback_store(request: Request):
    stores = request.app.state.stores
    if stores.feedback is None:
        raise HTTPException(503, "Feedback store not configured")
    return stores.feedback


@router.get("/feedback/corrections")
async def list_corrections(
    request: Request,
    item_id: int | None = Query(None),
):
    store = _get_feedback_store(request)
    return await store.get_corrections(item_id=item_id)


@router.post("/feedback/corrections")
async def add_correction(correction: FeedbackCorrection, request: Request):
    store = _get_feedback_store(request)
    return await store.add_correction(correction)


@router.delete("/feedback/corrections/{correction_id}")
async def delete_correction(correction_id: int, request: Request):
    store = _get_feedback_store(request)
    await store.delete_correction(correction_id)
    return {"status": "deleted"}


@router.get("/feedback/tasks")
async def list_tasks(
    request: Request,
    status: str | None = Query(None),
):
    store = _get_feedback_store(request)
    return await store.get_tasks(status=status)


@router.post("/feedback/tasks")
async def add_task(task: FilterTuningTask, request: Request):
    store = _get_feedback_store(request)
    return await store.add_task(task)


@router.patch("/feedback/tasks/{task_id}")
async def update_task_status(task_id: int, request: Request, status: str = Query(...)):
    store = _get_feedback_store(request)
    return await store.update_task(task_id, status)


@router.delete("/feedback/tasks/{task_id}")
async def delete_task(task_id: int, request: Request):
    store = _get_feedback_store(request)
    await store.delete_task(task_id)
    return {"status": "deleted"}
