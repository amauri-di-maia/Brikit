from fastapi import FastAPI

app = FastAPI(title="Brikit API")


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}
