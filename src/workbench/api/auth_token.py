from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/token")
async def get_token(request: Request):
    """Return the API token for the React UI.

    The React app calls this on mount to get the token for subsequent
    API calls. This endpoint itself is behind the auth middleware,
    so the caller must already have a valid token (e.g. via cookie
    or the initial page load). In dev mode the Vite proxy forwards
    the request with the same auth header.
    """
    config = request.app.state.config
    return {"token": config.server.api_token}
