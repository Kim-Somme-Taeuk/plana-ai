from fastapi import FastAPI

from app.api.routes.ranking_entries import router as ranking_entries_router
from app.api.routes.ranking_snapshots import router as ranking_snapshots_router
from app.api.routes.seasons import router as seasons_router
from app.db.session import check_db_connection

app = FastAPI(
    title="plana-ai backend",
    version="0.1.0",
)

app.include_router(seasons_router)
app.include_router(ranking_snapshots_router)
app.include_router(ranking_entries_router)


@app.get("/")
def read_root() -> dict[str, str]:
    return {"message": "plana-ai backend is running"}


@app.get("/health")
def health_check() -> dict[str, str | bool]:
    db_ok = check_db_connection()

    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
    }
