# server/main.py
from fastapi import FastAPI
from server.config import Settings
from server.auth import BearerTokenMiddleware

settings = Settings()
app = FastAPI(title="Workbench", version="0.1.0")
app.add_middleware(BearerTokenMiddleware, token=settings.api_token)

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
