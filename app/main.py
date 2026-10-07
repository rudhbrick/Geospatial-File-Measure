from fastapi import FastAPI

app = FastAPI(title="Geospatial File Measurement API")

@app.get("/health")
def health():
    return {"status": "ok"}