"""
FastAPI application entrypoint for Phase 6 dashboard.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import dashboard_router
from config import setup_logging
from data.models import init_db

setup_logging()
init_db()

app = FastAPI(
    title="Apex API",
    version="0.1.0",
    description="Apex dashboard and paper trading read-only API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}


app.include_router(dashboard_router)
