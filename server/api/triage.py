from fastapi import APIRouter, HTTPException, Request
from server.models import TriageResponse

router = APIRouter(prefix="/api", tags=["triage"])


@router.get("/triage/pending")
async def get_pending(request: Request):
    stores = request.app.state.stores
    return await stores.triage.get_pending()


@router.post("/triage/respond")
async def respond_to_triage(response: TriageResponse, request: Request):
    stores = request.app.state.stores
    card = await stores.triage.get_card(response.card_id)
    if not card:
        raise HTTPException(404, "Triage card not found")
    await stores.triage.record_response(response.card_id, response)
    return {"status": "recorded"}
