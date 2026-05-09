"""FastAPI entrypoint for Maatru. Mounts kid + parent UIs and exposes API endpoints."""

from fastapi import FastAPI

app = FastAPI(title="Maatru", version="0.1.0")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
