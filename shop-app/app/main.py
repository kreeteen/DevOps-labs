import random
import time

from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

app = FastAPI()

# Counter: только растёт. Считаем запросы по пути и статусу.
REQUESTS = Counter("app_requests_total", "Total HTTP requests", ["path", "status"])
# Histogram: раскладывает время ответа по «корзинам», нужен для перцентилей.
LATENCY = Histogram("app_request_duration_seconds", "Request latency", ["path"])


@app.middleware("http")
async def collect_metrics(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    if request.url.path != "/metrics":
        LATENCY.labels(request.url.path).observe(time.time() - start)
        REQUESTS.labels(request.url.path, str(response.status_code)).inc()
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/items")
def items():
    return [{"id": 1, "name": "book"}, {"id": 2, "name": "pen"}]


@app.get("/slow")
def slow():
    time.sleep(random.uniform(0.5, 2.0))
    return {"status": "slow but ok"}


@app.get("/error")
def error():
    raise HTTPException(status_code=500, detail="simulated failure")


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
