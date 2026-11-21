import contextvars
import json
import logging
import random
import time
import uuid

from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

# --- сквозной идентификатор запроса ---
request_id_ctx = contextvars.ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        data = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "msg": record.getMessage(),
            "request_id": request_id_ctx.get(),
        }
        data.update(getattr(record, "fields", {}))
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
log = logging.getLogger("shop")
log.setLevel(logging.INFO)
log.addHandler(handler)
log.propagate = False

app = FastAPI()

REQUESTS = Counter("app_requests_total", "Total HTTP requests", ["path", "status"])
LATENCY = Histogram("app_request_duration_seconds", "Request latency", ["path"])

QUIET_PATHS = {"/health", "/metrics"}  # пробы и скрейп не засоряют логи


@app.middleware("http")
async def observe(request: Request, call_next):
    # берём id из заголовка (если пришёл от другого сервиса) или создаём новый
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    request_id_ctx.set(rid)
    start = time.time()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("unhandled error", extra={"fields": {"path": request.url.path}})
        raise
    duration = time.time() - start

    response.headers["X-Request-ID"] = rid
    if request.url.path != "/metrics":
        LATENCY.labels(request.url.path).observe(duration)
        REQUESTS.labels(request.url.path, str(response.status_code)).inc()
    if request.url.path not in QUIET_PATHS:
        log.info(
            "request finished",
            extra={"fields": {
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round(duration * 1000),
            }},
        )
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
    log.error("simulated failure in /error handler")
    raise HTTPException(status_code=500, detail="simulated failure")


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
