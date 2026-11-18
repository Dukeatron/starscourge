"""AgentShield backend: FastAPI app, mock upstream, demo orchestration.

Run with a single worker only: all state lives in this process's memory.
    uvicorn main:app --host 127.0.0.1 --port 8000
"""
import asyncio
import json
import logging
import math
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import Body, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from proxy_engine import add_log, hash_payload, process_proxy_request

# process_proxy_request(state, agent_id, endpoint, payload, forward_target, now) -> tuple[int, dict]
# add_log(state, *, agent_id, endpoint, payload_hash, action, http_code, reason, now) -> dict
# hash_payload(payload: dict) -> str

logger = logging.getLogger("agentshield")

# --------------------------------------------------------------------------- state

STATE: dict[str, Any] = {
    "target_timestamps": [],
    "banned_until": 0.0,
    "proxy_history": {},          # owned by proxy_engine
    "metrics": {
        "total_calls": 0,
        "passed_calls": 0,
        "cached_calls": 0,
        "blocked_calls": 0,
        "bans_prevented": 0,
        "dollars_saved": 0.0,
        "upstream_banned_calls": 0,   # internal only, never in /stats
        "upstream_bans": 0,           # internal only, never in /stats
    },
    "logs": [],                   # oldest first, capped at 500
}

# Created inside the lifespan handler, never at import time.
STATE_LOCK: asyncio.Lock | None = None
DEMO_LOCK: asyncio.Lock | None = None

INDEX_PATH = Path(__file__).with_name("index.html")


def clock() -> float:
    """The single time source. Tests patch this."""
    return time.time()


# --------------------------------------------------------------------------- mock upstream

WINDOW_SEC = 10
MAX_CALLS_PER_WINDOW = 4
BAN_SEC = 60


def target_api_logic(state, payload, now):
    """Synchronous. Touches only upstream rate-limit state. No locks, no I/O, no log or call counters."""
    if now < state["banned_until"]:                       # ban active: do not record, do not extend
        return 403, {"error": "IP_BANNED",
                     "retry_after": math.ceil(state["banned_until"] - now)}
    ts = state["target_timestamps"]
    ts[:] = [t for t in ts if now - t < WINDOW_SEC]       # an entry aged exactly 10.0 s is dropped
    ts.append(now)
    if len(ts) > MAX_CALLS_PER_WINDOW:
        state["banned_until"] = now + BAN_SEC
        state["metrics"]["upstream_bans"] += 1            # the only metric this function may touch
        return 403, {"error": "IP_BANNED", "retry_after": BAN_SEC}
    return 200, {"status": "ok", "data": "order_batch_synced"}


# --------------------------------------------------------------------------- internal handlers

class StaleDemo(Exception):
    """Raised when a demo runner from an older generation tries to act."""


def _ensure_current(generation):
    if generation is not None and generation != DEMO["generation"]:
        raise StaleDemo()


async def handle_direct_request(agent_id: str, payload: dict, generation: int | None = None):
    async with STATE_LOCK:
        _ensure_current(generation)
        now = clock()
        m = STATE["metrics"]
        m["total_calls"] += 1
        bans_before = m["upstream_bans"]
        status, body = target_api_logic(STATE, payload, now)
        if status == 200:
            m["passed_calls"] += 1
            add_log(STATE, agent_id=agent_id, endpoint="/target-api", payload_hash=hash_payload(payload),
                    action="PASSED", http_code=200, reason="Forwarded to upstream", now=now)
        else:
            m["upstream_banned_calls"] += 1
            reason = ("Upstream rate limit exceeded: 60s ban started" if m["upstream_bans"] > bans_before
                      else f"Upstream IP ban active: {body['retry_after']}s remaining")
            add_log(STATE, agent_id=agent_id, endpoint="/target-api", payload_hash=hash_payload(payload),
                    action="UPSTREAM_BANNED", http_code=403, reason=reason, now=now)
        return status, body


async def handle_proxy_request(agent_id, endpoint, payload, generation: int | None = None):
    async with STATE_LOCK:
        _ensure_current(generation)
        now = clock()
        return process_proxy_request(STATE, agent_id, endpoint, payload, forward_target, now)


def forward_target(payload, now):        # callback given to the engine; never an HTTP call
    return target_api_logic(STATE, payload, now)


async def read_stats():
    async with STATE_LOCK:
        now = clock()
        banned_until = STATE["banned_until"]
        m = dict(STATE["metrics"])                 # snapshot
    remaining = max(0.0, banned_until - now)
    return {
        "ip_status": "BANNED" if remaining > 0 else "HEALTHY",
        "ban_remaining_sec": math.ceil(remaining),
        "total_calls": m["total_calls"], "passed_calls": m["passed_calls"],
        "cached_calls": m["cached_calls"], "blocked_calls": m["blocked_calls"],
        "bans_prevented": m["bans_prevented"],
        "dollars_saved": round(m["dollars_saved"], 2),
    }


async def read_logs():
    async with STATE_LOCK:
        entries = [dict(e) for e in reversed(STATE["logs"][-50:])]   # newest first, copied
    return entries


# --------------------------------------------------------------------------- demo orchestration

DEMO_INTERVAL_SEC = 0.2
AGENT_ID = "shopify-sync-agent-01"
ENDPOINT = "/orders/sync"
PAYLOAD = {"shop": "myshopify.com", "cursor": "page_42"}

DEMO: dict[str, Any] = {"name": None, "task": None, "generation": 0}   # name is "protected" or "unprotected"


def _running():
    return DEMO["task"] is not None and not DEMO["task"].done()


async def start_demo(name):
    async with DEMO_LOCK:
        if _running():
            return JSONResponse({"error": "DEMO_ALREADY_RUNNING", "demo": DEMO["name"]}, 409)
        DEMO["generation"] += 1
        gen = DEMO["generation"]
        await _reset_state()                              # every demo starts from a clean slate
        task = asyncio.create_task(_run_demo(name, gen))
        DEMO["name"], DEMO["task"] = name, task
        task.add_done_callback(lambda t, g=gen: _demo_done(g))
    return JSONResponse({"status": "started", "demo": name}, 202)


async def _run_demo(name, gen):
    try:
        for i in range(7):
            if i:
                await asyncio.sleep(DEMO_INTERVAL_SEC)
            if name == "unprotected":
                await handle_direct_request(AGENT_ID, PAYLOAD, generation=gen)
            else:
                await handle_proxy_request(AGENT_ID, ENDPOINT, PAYLOAD, generation=gen)
    except (asyncio.CancelledError, StaleDemo):
        pass                                              # reset won; stop silently
    except Exception:
        logging.exception("demo failed")                  # never leave status stuck on running


def _demo_done(gen):                                      # runs on the event loop, no await
    if DEMO["generation"] == gen:
        DEMO["name"] = DEMO["task"] = None


async def reset():
    async with DEMO_LOCK:
        DEMO["generation"] += 1                           # invalidates the old runner immediately
        task = DEMO["task"]
        if task is not None and not task.done():
            task.cancel()
            await asyncio.wait({task}, timeout=2)         # wait for it to actually stop
        DEMO["name"] = DEMO["task"] = None
        await _reset_state()
    return {"status": "reset"}


async def _reset_state():
    async with STATE_LOCK:
        STATE["target_timestamps"].clear()
        STATE["banned_until"] = 0.0
        STATE["proxy_history"].clear()
        STATE["logs"].clear()
        for k in STATE["metrics"]:
            STATE["metrics"][k] = 0.0 if k == "dollars_saved" else 0


# --------------------------------------------------------------------------- app

@asynccontextmanager
async def lifespan(app: FastAPI):
    global STATE_LOCK, DEMO_LOCK
    STATE_LOCK = asyncio.Lock()
    DEMO_LOCK = asyncio.Lock()
    try:
        yield
    finally:
        task = DEMO["task"]                               # don't leave a demo running past shutdown
        if task is not None and not task.done():
            task.cancel()
            await asyncio.wait({task}, timeout=2)


app = FastAPI(title="AgentShield", lifespan=lifespan)


# --------------------------------------------------------------------------- models

PAYLOAD_MAX_BYTES = 10 * 1024


class ProxyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(min_length=1, max_length=100)
    endpoint: str = Field(pattern=r"^/[A-Za-z0-9_\-./]*$", max_length=200)
    payload: dict[str, Any]                      # free-form JSON object, max 10 KB serialized

    @field_validator("payload")
    @classmethod
    def _payload_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        size = len(json.dumps(v, separators=(",", ":"), ensure_ascii=False).encode())
        if size > PAYLOAD_MAX_BYTES:
            raise ValueError(f"payload must be at most {PAYLOAD_MAX_BYTES} bytes serialized")
        return v


class DirectRequest(BaseModel):                  # POST /target-api; the whole body is optional
    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(default="direct-client", min_length=1, max_length=100)
    payload: dict[str, Any] = {}


class StatsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ip_status: Literal["HEALTHY", "BANNED"]
    ban_remaining_sec: int
    total_calls: int
    passed_calls: int
    cached_calls: int
    blocked_calls: int
    bans_prevented: int
    dollars_saved: float


class LogEntry(BaseModel):
    id: str
    timestamp: str
    agent_id: str
    target_endpoint: str
    payload_hash: str
    action: str
    http_code: int
    reason: str


class DemoStatus(BaseModel):
    running: bool
    demo: str | None


def _internal_error() -> JSONResponse:
    return JSONResponse({"error": "INTERNAL_ERROR"}, status_code=500)


# --------------------------------------------------------------------------- routes

@app.get("/")
async def index():
    if not INDEX_PATH.is_file():
        return JSONResponse({"error": "FRONTEND_NOT_FOUND"}, status_code=404)
    return FileResponse(INDEX_PATH)


@app.post("/target-api")
async def target_api(body: DirectRequest | None = Body(default=None)):
    req = body if body is not None else DirectRequest()
    try:
        status, resp = await handle_direct_request(req.agent_id, req.payload)
        return JSONResponse(content=resp, status_code=status)
    except Exception:
        logger.exception("direct request failed")
        return _internal_error()


@app.post("/proxy")
async def proxy(req: ProxyRequest):
    try:
        status, body = await handle_proxy_request(req.agent_id, req.endpoint, req.payload)
        headers = None
        if status == 429 and isinstance(body, dict) and "retry_after" in body:
            headers = {"Retry-After": str(body["retry_after"])}
        return JSONResponse(content=body, status_code=status, headers=headers)
    except Exception:
        logger.exception("proxy engine failed")
        return _internal_error()


@app.post("/demo/unprotected", status_code=202)
async def demo_unprotected():
    return await start_demo("unprotected")


@app.post("/demo/protected", status_code=202)
async def demo_protected():
    return await start_demo("protected")


@app.post("/demo/reset")
async def demo_reset():
    return JSONResponse(await reset(), status_code=200)


@app.get("/demo/status", response_model=DemoStatus)
async def demo_status():
    running = _running()
    return JSONResponse({"running": running, "demo": DEMO["name"] if running else None})


@app.get("/stats", response_model=StatsResponse)
async def stats():
    return JSONResponse(StatsResponse(**(await read_stats())).model_dump())


@app.get("/logs", response_model=list[LogEntry])
async def logs():
    entries = await read_logs()
    return JSONResponse([LogEntry.model_validate(e).model_dump() for e in entries])
