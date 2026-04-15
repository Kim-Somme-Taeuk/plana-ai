from fastapi import FastAPI

from app.db.session import check_db_connection

app = FastAPI(
    title="plana-ai backend",
    version="0.1.0",
)


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
