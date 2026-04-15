from fastapi import FastAPI

app = FastAPI(
    title="plana-ai backend",
    version="0.1.0",
)


@app.get("/")
def read_root() -> dict[str, str]:
    return {"message": "plana-ai backend is running"}


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
