"""Test setup.

A fake `proxy_engine` module goes into `sys.modules` BEFORE `main` is imported,
so tests never depend on the real engine or on a temporary stub. Tests that need
the real engine use the `real_engine` fixture, which loads `proxy_engine.py`
from disk under a different module name and skips when it is absent or a stub.
"""
import hashlib
import importlib.util
import json
import sys
import time
import types
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# --------------------------------------------------------------------------- fake engine

def _hash_payload(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _add_log(state, *, agent_id, endpoint, payload_hash, action, http_code, reason, now) -> dict:
    logs = state["logs"]
    taken = {e["id"] for e in logs}
    log_id = "req_" + uuid.uuid4().hex[:8]
    while log_id in taken:
        log_id = "req_" + uuid.uuid4().hex[:8]
    entry = {
        "id": log_id,
        "timestamp": datetime.fromtimestamp(now, tz=timezone.utc).strftime("%H:%M:%S.%f")[:-3],
        "agent_id": agent_id,
        "target_endpoint": endpoint,
        "payload_hash": payload_hash,
        "action": action,
        "http_code": http_code,
        "reason": reason,
    }
    logs.append(entry)
    if len(logs) > 500:
        del logs[:-500]
    return entry


def passthrough_engine(state, agent_id, endpoint, payload, forward_target, now):
    """A minimal contract-following engine: forwards everything, never caches or blocks."""
    m = state["metrics"]
    m["total_calls"] += 1
    status, body = forward_target(payload, now)
    if status == 200:
        m["passed_calls"] += 1
        action, reason = "PASSED", "Forwarded to upstream"
    else:
        m["upstream_banned_calls"] += 1
        action, reason = "UPSTREAM_BANNED", "Upstream IP ban active"
    _add_log(state, agent_id=agent_id, endpoint=endpoint, payload_hash=_hash_payload(payload),
             action=action, http_code=status, reason=reason, now=now)
    return status, body


class _FakeEngine:
    """Records every call and delegates to a swappable implementation."""

    def __init__(self):
        self.calls = []
        self.impl = passthrough_engine

    def reset(self):
        self.calls = []
        self.impl = passthrough_engine

    def __call__(self, state, agent_id, endpoint, payload, forward_target, now):
        self.calls.append({"state": state, "agent_id": agent_id, "endpoint": endpoint,
                           "payload": payload, "forward_target": forward_target, "now": now})
        return self.impl(state, agent_id, endpoint, payload, forward_target, now)


FAKE_ENGINE = _FakeEngine()

_fake_module = types.ModuleType("proxy_engine")
_fake_module.__doc__ = "Fake proxy engine injected by tests/conftest.py"
_fake_module.hash_payload = _hash_payload
_fake_module.add_log = _add_log
_fake_module.process_proxy_request = FAKE_ENGINE
sys.modules["proxy_engine"] = _fake_module

import main  # noqa: E402  (must come after the fake engine is injected)
from fastapi.testclient import TestClient  # noqa: E402

T0 = 1_000_000.0   # exactly representable, so boundary arithmetic is exact


class FakeClock:
    """Frozen by default; `step` makes every read advance time (simulates demo spacing)."""

    def __init__(self, t: float = T0):
        self.t = t
        self.step = 0.0

    def __call__(self) -> float:
        now = self.t
        self.t += self.step
        return now

    def advance(self, dt: float) -> None:
        self.t += dt

    def set(self, t: float) -> None:
        self.t = t


def _clear_state():
    s = main.STATE
    s["target_timestamps"].clear()
    s["banned_until"] = 0.0
    s["proxy_history"].clear()
    s["logs"].clear()
    for k in s["metrics"]:
        s["metrics"][k] = 0.0 if k == "dollars_saved" else 0


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    """Clean state, patched clock and zero demo interval for every test."""
    _clear_state()
    main.DEMO.update({"name": None, "task": None, "generation": 0})
    FAKE_ENGINE.reset()
    clk = FakeClock()
    monkeypatch.setattr(main, "clock", clk)
    monkeypatch.setattr(main, "DEMO_INTERVAL_SEC", 0)
    yield clk
    _clear_state()
    main.DEMO.update({"name": None, "task": None, "generation": 0})


@pytest.fixture
def clock(fresh_state):
    return fresh_state


@pytest.fixture
def fake_engine():
    return FAKE_ENGINE


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def _load_real_engine():
    path = ROOT / "proxy_engine.py"
    if not path.is_file():
        return None, "proxy_engine.py is not present"
    spec = importlib.util.spec_from_file_location("_real_proxy_engine", path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:  # not importable
        return None, f"proxy_engine.py is not importable: {exc!r}"
    for name in ("process_proxy_request", "add_log", "hash_payload"):
        if not callable(getattr(mod, name, None)):
            return None, f"proxy_engine.py has no callable {name}"
    probe = {
        "target_timestamps": [], "banned_until": 0.0, "proxy_history": {}, "logs": [],
        "metrics": {k: (0.0 if k == "dollars_saved" else 0) for k in main.STATE["metrics"]},
    }
    try:
        mod.process_proxy_request(probe, "probe", "/probe", {"probe": True},
                                  lambda p, now: (200, {"status": "ok"}), T0)
    except NotImplementedError:
        return None, "proxy_engine.py is the temporary stub"
    return mod, ""


@pytest.fixture
def real_engine(monkeypatch):
    """Swap the real engine into `main`; skip when it is absent, unimportable or a stub."""
    mod, why = _load_real_engine()
    if mod is None:
        pytest.skip(f"real proxy engine unavailable: {why}")
    monkeypatch.setattr(main, "process_proxy_request", mod.process_proxy_request)
    monkeypatch.setattr(main, "add_log", mod.add_log)
    monkeypatch.setattr(main, "hash_payload", mod.hash_payload)
    return mod


def wait_idle(client, timeout: float = 5.0) -> None:
    """Poll /demo/status until the demo has finished."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not client.get("/demo/status").json()["running"]:
            return
        time.sleep(0.01)
    raise AssertionError("demo did not finish in time")


def assert_invariant() -> None:
    m = main.STATE["metrics"]
    assert m["total_calls"] == (m["passed_calls"] + m["cached_calls"]
                                + m["blocked_calls"] + m["upstream_banned_calls"]), m
