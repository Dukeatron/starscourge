import asyncio
import re
import socket
import time

import pytest

import main
from conftest import T0, assert_invariant, passthrough_engine, wait_idle

STATS_KEYS = {"ip_status", "ban_remaining_sec", "total_calls", "passed_calls", "cached_calls",
              "blocked_calls", "bans_prevented", "dollars_saved"}
LOG_KEYS = {"id", "timestamp", "agent_id", "target_endpoint", "payload_hash", "action",
            "http_code", "reason"}
ACTION_CODES = {"PASSED": 200, "CACHED": 200, "BLOCKED": 429, "UPSTREAM_BANNED": 403}
PROXY_BODY = {"agent_id": "shopify-sync-agent-01", "endpoint": "/orders/sync",
              "payload": {"shop": "myshopify.com", "cursor": "page_42"}}


def metrics():
    return dict(main.STATE["metrics"])


def zero_metrics():
    return {k: (0.0 if k == "dollars_saved" else 0) for k in main.STATE["metrics"]}


def oldest_first_actions(client):
    return [e["action"] for e in reversed(client.get("/logs").json())]


# --------------------------------------------------------------------------- 1. upstream threshold

def test_upstream_threshold(client):
    for _ in range(4):
        r = client.post("/target-api")
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "data": "order_batch_synced"}
    r = client.post("/target-api")
    assert r.status_code == 403
    assert r.json() == {"error": "IP_BANNED", "retry_after": 60}
    assert main.STATE["metrics"]["upstream_bans"] == 1
    assert main.STATE["banned_until"] == T0 + 60
    assert_invariant()


# --------------------------------------------------------------------------- 2. ban semantics

def test_ban_semantics(client, clock):
    for _ in range(5):
        client.post("/target-api")
    assert len(main.STATE["target_timestamps"]) == 5
    banned_until = main.STATE["banned_until"]

    clock.set(T0 + 10.5)
    r = client.post("/target-api")
    assert r.status_code == 403 and r.json()["retry_after"] == 50
    s = client.get("/stats").json()
    assert s["ip_status"] == "BANNED" and s["ban_remaining_sec"] == 50

    clock.set(T0 + 59.5)
    r = client.post("/target-api")
    assert r.status_code == 403 and r.json()["retry_after"] == 1

    # banned calls are not recorded and never extend the ban
    assert len(main.STATE["target_timestamps"]) == 5
    assert main.STATE["banned_until"] == banned_until
    assert main.STATE["metrics"]["upstream_bans"] == 1

    clock.set(T0 + 60)                       # now == banned_until: the ban is over
    s = client.get("/stats").json()
    assert s["ip_status"] == "HEALTHY" and s["ban_remaining_sec"] == 0
    r = client.post("/target-api")
    assert r.status_code == 200
    assert main.STATE["target_timestamps"] == [T0 + 60]
    assert_invariant()


# --------------------------------------------------------------------------- 3. window boundary

def test_window_boundary(client, clock):
    for _ in range(4):
        assert client.post("/target-api").status_code == 200
    clock.set(T0 + 10.0)                     # entries aged exactly 10.0 s are dropped
    assert client.post("/target-api").status_code == 200
    assert main.STATE["target_timestamps"] == [T0 + 10.0]
    assert main.STATE["metrics"]["upstream_bans"] == 0


def test_window_just_inside_boundary_bans():
    state = {"target_timestamps": [], "banned_until": 0.0, "metrics": {"upstream_bans": 0}}
    for _ in range(4):
        assert main.target_api_logic(state, {}, T0)[0] == 200
    assert main.target_api_logic(state, {}, T0 + 9.999)[0] == 403
    assert state["metrics"] == {"upstream_bans": 1}       # the only metric it touches


# --------------------------------------------------------------------------- 4. direct metrics

def test_direct_metrics(client):
    for i in range(1, 5):
        client.post("/target-api")
        m = metrics()
        assert m["total_calls"] == i and m["passed_calls"] == i
    client.post("/target-api")
    client.post("/target-api")
    m = metrics()
    assert m["total_calls"] == 6 and m["passed_calls"] == 4 and m["upstream_banned_calls"] == 2
    assert m["cached_calls"] == m["blocked_calls"] == m["bans_prevented"] == 0

    logs = client.get("/logs").json()
    assert [e["action"] for e in logs] == ["UPSTREAM_BANNED"] * 2 + ["PASSED"] * 4
    newest, ban_start = logs[0], logs[1]
    assert ban_start["http_code"] == 403
    assert ban_start["reason"] == "Upstream rate limit exceeded: 60s ban started"
    assert newest["reason"] == "Upstream IP ban active: 60s remaining"
    assert all(e["agent_id"] == "direct-client" for e in logs)
    assert all(e["target_endpoint"] == "/target-api" for e in logs)
    assert all(e["payload_hash"] == main.hash_payload({}) for e in logs)
    assert_invariant()


def test_direct_with_body(client):
    payload = {"shop": "myshopify.com", "n": 1}
    r = client.post("/target-api", json={"agent_id": "agent-x", "payload": payload})
    assert r.status_code == 200
    e = client.get("/logs").json()[0]
    assert e["agent_id"] == "agent-x" and e["payload_hash"] == main.hash_payload(payload)
    assert client.post("/target-api", json={}).status_code == 200
    assert client.get("/logs").json()[0]["agent_id"] == "direct-client"


# --------------------------------------------------------------------------- 5. proxy integration

def test_proxy_integration(client, clock, fake_engine, monkeypatch):
    def no_network(*a, **kw):
        raise AssertionError("the app must never open a network connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)

    upstream_calls = []
    real_logic = main.target_api_logic

    def spy(state, payload, now):
        upstream_calls.append((state, payload, now))
        return real_logic(state, payload, now)

    monkeypatch.setattr(main, "target_api_logic", spy)
    fake_engine.impl = lambda state, a, e, payload, fwd, now: fwd(payload, now)   # no metrics, no logs

    clock.set(T0 + 3.25)
    r = client.post("/proxy", json=PROXY_BODY)
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "data": "order_batch_synced"}

    (call,) = fake_engine.calls
    assert call["state"] is main.STATE
    assert call["now"] == T0 + 3.25
    assert call["agent_id"] == PROXY_BODY["agent_id"]
    assert call["endpoint"] == PROXY_BODY["endpoint"]
    assert call["payload"] == PROXY_BODY["payload"]
    assert call["forward_target"] is main.forward_target
    assert upstream_calls == [(main.STATE, PROXY_BODY["payload"], T0 + 3.25)]
    assert main.STATE["target_timestamps"] == [T0 + 3.25]

    # the route itself touches no metric and writes no log
    assert metrics() == zero_metrics()
    assert main.STATE["logs"] == []


def test_proxy_response_passthrough(client, fake_engine):
    blocked = {"error": "BLOCKED", "reason": "Loop detected", "retry_after": 7}
    fake_engine.impl = lambda *a: (429, blocked)
    r = client.post("/proxy", json=PROXY_BODY)
    assert r.status_code == 429 and r.json() == blocked
    assert r.headers["retry-after"] == "7"

    fake_engine.impl = lambda *a: (403, {"error": "IP_BANNED", "retry_after": 42})
    r = client.post("/proxy", json=PROXY_BODY)
    assert r.status_code == 403 and r.json()["retry_after"] == 42
    assert "retry-after" not in r.headers

    fake_engine.impl = lambda *a: (200, {"status": "ok"})
    r = client.post("/proxy", json=PROXY_BODY)
    assert r.status_code == 200 and "retry-after" not in r.headers


def test_proxy_engine_error_is_500(client, fake_engine):
    def boom(*a):
        raise RuntimeError("engine bug")

    fake_engine.impl = boom
    r = client.post("/proxy", json=PROXY_BODY)
    assert r.status_code == 500 and r.json() == {"error": "INTERNAL_ERROR"}
    # the lock was released: the next request still works
    fake_engine.impl = passthrough_engine
    assert client.post("/proxy", json=PROXY_BODY).status_code == 200


# --------------------------------------------------------------------------- 6. unprotected demo

def test_unprotected_demo(client, clock):
    clock.step = 0.2
    r = client.post("/demo/unprotected")
    assert r.status_code == 202 and r.json() == {"status": "started", "demo": "unprotected"}
    wait_idle(client)

    assert oldest_first_actions(client) == ["PASSED"] * 4 + ["UPSTREAM_BANNED"] * 3
    assert main.STATE["metrics"]["upstream_bans"] == 1
    s = client.get("/stats").json()
    assert s["ip_status"] == "BANNED" and s["ban_remaining_sec"] in (59, 60)
    assert {k: s[k] for k in ("total_calls", "passed_calls", "cached_calls", "blocked_calls",
                              "bans_prevented")} == {"total_calls": 7, "passed_calls": 4,
                                                     "cached_calls": 0, "blocked_calls": 0,
                                                     "bans_prevented": 0}
    logs = client.get("/logs").json()
    assert all(e["agent_id"] == main.AGENT_ID for e in logs)
    assert client.get("/demo/status").json() == {"running": False, "demo": None}
    assert_invariant()


# --------------------------------------------------------------------------- 7. protected demo (real engine)

def assert_protected_result(client):
    assert oldest_first_actions(client) == ["PASSED", "CACHED"] + ["BLOCKED"] * 5
    assert main.STATE["metrics"]["upstream_bans"] == 0
    s = client.get("/stats").json()
    assert s["ip_status"] == "HEALTHY" and s["ban_remaining_sec"] == 0
    assert {k: s[k] for k in ("total_calls", "passed_calls", "cached_calls", "blocked_calls",
                              "bans_prevented")} == {"total_calls": 7, "passed_calls": 1,
                                                     "cached_calls": 1, "blocked_calls": 5,
                                                     "bans_prevented": 1}
    logs = client.get("/logs").json()
    assert all(e["target_endpoint"] == main.ENDPOINT for e in logs)
    assert all(e["http_code"] == ACTION_CODES[e["action"]] for e in logs)
    assert_invariant()


def test_protected_demo_real_engine(real_engine, client, clock):
    clock.step = 0.2
    r = client.post("/demo/protected")
    assert r.status_code == 202 and r.json() == {"status": "started", "demo": "protected"}
    wait_idle(client)
    assert_protected_result(client)


# --------------------------------------------------------------------------- 8. demo independence

def test_demo_independence_real_engine(real_engine, client, clock):
    clock.step = 0.2
    assert client.post("/demo/unprotected").status_code == 202
    wait_idle(client)
    assert client.get("/stats").json()["ip_status"] == "BANNED"
    assert client.post("/demo/protected").status_code == 202        # no reset in between
    wait_idle(client)
    assert_protected_result(client)


def test_demo_independence_clean_slate(client, clock):
    """With the pass-through fake engine: the second demo must not inherit the first's ban or counts."""
    clock.step = 0.2
    assert client.post("/demo/unprotected").status_code == 202
    wait_idle(client)
    assert client.post("/demo/protected").status_code == 202
    wait_idle(client)
    logs = client.get("/logs").json()
    assert len(logs) == 7
    assert all(e["target_endpoint"] == main.ENDPOINT for e in logs)   # nothing left from /target-api
    assert oldest_first_actions(client) == ["PASSED"] * 4 + ["UPSTREAM_BANNED"] * 3
    m = metrics()
    assert m["total_calls"] == 7 and m["passed_calls"] == 4 and m["upstream_bans"] == 1
    assert_invariant()


# --------------------------------------------------------------------------- 9. concurrency control

def gate_demo(monkeypatch, client, after: int):
    """Let `after` demo requests through, then hold the runner until the returned event is set."""
    gate = client.portal.call(asyncio.Event)
    real = main.handle_direct_request
    seen = {"n": 0}

    async def gated(*args, **kwargs):
        seen["n"] += 1
        if seen["n"] > after:
            await gate.wait()
        return await real(*args, **kwargs)

    monkeypatch.setattr(main, "handle_direct_request", gated)
    return gate


def test_demo_concurrency(client, monkeypatch):
    gate = gate_demo(monkeypatch, client, after=0)
    assert client.post("/demo/unprotected").status_code == 202
    assert client.get("/demo/status").json() == {"running": True, "demo": "unprotected"}

    for path in ("/demo/unprotected", "/demo/protected"):
        r = client.post(path)
        assert r.status_code == 409
        assert r.json() == {"error": "DEMO_ALREADY_RUNNING", "demo": "unprotected"}

    client.portal.call(gate.set)
    wait_idle(client)
    assert client.get("/demo/status").json() == {"running": False, "demo": None}
    assert len(main.STATE["logs"]) == 7

    assert client.post("/demo/unprotected").status_code == 202      # idle again: accepted
    wait_idle(client)
    assert metrics()["total_calls"] == 7                            # fresh slate, not 14
    assert_invariant()


# --------------------------------------------------------------------------- 10. reset during a demo

def test_reset_during_demo(client, monkeypatch):
    gate = gate_demo(monkeypatch, client, after=5)        # 5 requests land (ban active), then hold
    assert client.post("/demo/unprotected").status_code == 202
    deadline = time.monotonic() + 5
    while len(main.STATE["logs"]) < 5 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(main.STATE["logs"]) == 5
    assert main.STATE["banned_until"] > 0
    task = main.DEMO["task"]

    r = client.post("/demo/reset")
    assert r.status_code == 200 and r.json() == {"status": "reset"}
    assert task.done()
    assert client.get("/demo/status").json() == {"running": False, "demo": None}

    def assert_clean():
        assert metrics() == zero_metrics()
        assert main.STATE["logs"] == [] and client.get("/logs").json() == []
        assert main.STATE["banned_until"] == 0.0
        assert main.STATE["target_timestamps"] == []
        assert main.STATE["proxy_history"] == {}
        s = client.get("/stats").json()
        assert s["ip_status"] == "HEALTHY" and s["ban_remaining_sec"] == 0 and s["total_calls"] == 0

    assert_clean()
    client.portal.call(gate.set)                           # the old runner must not resume
    time.sleep(0.1)
    assert_clean()


def test_stale_generation_is_rejected(client):
    async def stale_call():
        old = main.DEMO["generation"]
        main.DEMO["generation"] += 1
        with pytest.raises(main.StaleDemo):
            await main.handle_direct_request(main.AGENT_ID, main.PAYLOAD, generation=old)
        with pytest.raises(main.StaleDemo):
            await main.handle_proxy_request(main.AGENT_ID, main.ENDPOINT, main.PAYLOAD, generation=old)

    client.portal.call(stale_call)
    assert metrics() == zero_metrics() and main.STATE["logs"] == []


def test_reset_is_idempotent(client):
    for _ in range(2):
        r = client.post("/demo/reset")
        assert r.status_code == 200 and r.json() == {"status": "reset"}
    assert client.get("/demo/status").json() == {"running": False, "demo": None}


# --------------------------------------------------------------------------- 11. metric invariant

def test_metric_invariant_mixed_traffic(client, clock, fake_engine):
    def outcome_engine(action, code, counter):
        def impl(state, agent_id, endpoint, payload, forward_target, now):
            m = state["metrics"]
            m["total_calls"] += 1
            m[counter] += 1
            main.add_log(state, agent_id=agent_id, endpoint=endpoint,
                         payload_hash=main.hash_payload(payload), action=action,
                         http_code=code, reason=f"{action} by fake engine", now=now)
            return code, ({"error": "BLOCKED", "reason": "x", "retry_after": 1} if code == 429
                          else {"status": "ok"})
        return impl

    steps = [
        lambda: client.post("/target-api"),
        lambda: client.post("/proxy", json=PROXY_BODY),                          # pass-through
        lambda: setattr(fake_engine, "impl", outcome_engine("CACHED", 200, "cached_calls")),
        lambda: client.post("/proxy", json=PROXY_BODY),
        lambda: setattr(fake_engine, "impl", outcome_engine("BLOCKED", 429, "blocked_calls")),
        lambda: client.post("/proxy", json=PROXY_BODY),
        lambda: setattr(fake_engine, "impl", passthrough_engine),
        lambda: client.post("/target-api"),
        lambda: client.post("/target-api"),
        lambda: client.post("/target-api"),                                      # 5th upstream: ban
        lambda: client.post("/proxy", json=PROXY_BODY),                          # forwarded, banned
        lambda: client.post("/proxy", json={"agent_id": "a"}),                   # 422, no change
    ]
    for step in steps:
        step()
        assert_invariant()
    m = metrics()
    assert m["total_calls"] == 8
    assert (m["passed_calls"], m["cached_calls"], m["blocked_calls"], m["upstream_banned_calls"]) == (4, 1, 1, 2)
    assert len(main.STATE["logs"]) == 8


# --------------------------------------------------------------------------- 12. contracts

def test_stats_contract(client):
    s = client.get("/stats").json()
    assert set(s) == STATS_KEYS
    assert s == {"ip_status": "HEALTHY", "ban_remaining_sec": 0, "total_calls": 0,
                 "passed_calls": 0, "cached_calls": 0, "blocked_calls": 0,
                 "bans_prevented": 0, "dollars_saved": 0.0}
    assert all(type(s[k]) is int for k in STATS_KEYS - {"ip_status", "dollars_saved"})
    assert isinstance(s["dollars_saved"], float)

    main.STATE["metrics"]["dollars_saved"] = 500.4549
    s = client.get("/stats").json()
    assert set(s) == STATS_KEYS and s["dollars_saved"] == 500.45
    assert "upstream_bans" not in s and "upstream_banned_calls" not in s


def test_logs_contract(client, clock):
    assert client.get("/logs").json() == []
    for i in range(60):
        client.post("/target-api", json={"agent_id": f"agent-{i}", "payload": {"i": i}})
        clock.advance(3)                    # 4 per 10 s window at most: never banned
    logs = client.get("/logs").json()
    assert len(logs) == 50
    assert [e["agent_id"] for e in logs] == [f"agent-{i}" for i in range(59, 9, -1)]  # newest first
    assert len({e["id"] for e in logs}) == 50
    for e in logs:
        assert set(e) == LOG_KEYS
        assert re.fullmatch(r"req_[0-9a-f]{8}", e["id"])
        assert re.fullmatch(r"\d{2}:\d{2}:\d{2}\.\d{3}", e["timestamp"])
        assert re.fullmatch(r"[0-9a-f]{64}", e["payload_hash"])
        assert e["http_code"] == ACTION_CODES[e["action"]]
        assert isinstance(e["http_code"], int) and e["reason"]
    assert logs[-1]["payload_hash"] == main.hash_payload({"i": 10})
    # T0 = 1_000_000 s after the epoch = 13:46:40 UTC; entry i was logged at T0 + 3*i
    assert logs[-1]["timestamp"] == "13:47:10.000"


def test_logs_expose_only_contract_fields(client, fake_engine):
    def leaky(state, agent_id, endpoint, payload, forward_target, now):
        state["metrics"]["total_calls"] += 1
        state["metrics"]["passed_calls"] += 1
        entry = main.add_log(state, agent_id=agent_id, endpoint=endpoint,
                             payload_hash=main.hash_payload(payload), action="PASSED",
                             http_code=200, reason="ok", now=now)
        entry["internal_debug"] = "must not leak"
        return 200, {"status": "ok"}

    fake_engine.impl = leaky
    client.post("/proxy", json=PROXY_BODY)
    (e,) = client.get("/logs").json()
    assert set(e) == LOG_KEYS


def test_demo_status_contract(client):
    assert client.get("/demo/status").json() == {"running": False, "demo": None}


# --------------------------------------------------------------------------- 13. validation

@pytest.mark.parametrize("body", [
    {**PROXY_BODY, "extra": 1},                                   # extra field
    {"endpoint": "/orders/sync", "payload": {}},                  # missing agent_id
    {"agent_id": "a", "payload": {}},                             # missing endpoint
    {"agent_id": "a", "endpoint": "/orders/sync"},                # missing payload
    {**PROXY_BODY, "payload": ["not", "an", "object"]},           # non-object payload
    {**PROXY_BODY, "payload": "string"},
    {**PROXY_BODY, "payload": 42},
    {**PROXY_BODY, "payload": None},
    {**PROXY_BODY, "agent_id": ""},
    {**PROXY_BODY, "agent_id": "a" * 101},
    {**PROXY_BODY, "agent_id": 123},
    {**PROXY_BODY, "endpoint": "orders/sync"},                    # no leading slash
    {**PROXY_BODY, "endpoint": "/orders?x=1"},                    # disallowed character
    {**PROXY_BODY, "endpoint": "/" + "a" * 200},                  # too long
    {**PROXY_BODY, "payload": {"blob": "x" * 10_240}},            # over 10 KB serialized
])
def test_proxy_validation(client, fake_engine, body):
    r = client.post("/proxy", json=body)
    assert r.status_code == 422
    assert fake_engine.calls == []
    assert metrics() == zero_metrics() and main.STATE["logs"] == []


def test_proxy_validation_non_json(client, fake_engine):
    r = client.post("/proxy", content=b"not json", headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert fake_engine.calls == [] and metrics() == zero_metrics()


def test_proxy_payload_at_size_limit_is_accepted(client, fake_engine):
    payload = {"blob": "x" * (10_240 - len('{"blob":""}'))}       # exactly 10 KB serialized
    assert client.post("/proxy", json={**PROXY_BODY, "payload": payload}).status_code == 200


@pytest.mark.parametrize("body", [
    {"extra": 1},
    {"payload": [1, 2]},
    {"agent_id": ""},
])
def test_direct_validation(client, body):
    assert client.post("/target-api", json=body).status_code == 422
    assert metrics() == zero_metrics() and main.STATE["target_timestamps"] == []


# --------------------------------------------------------------------------- 14. frontend route

def test_frontend_missing(client, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "INDEX_PATH", tmp_path / "index.html")
    r = client.get("/")
    assert r.status_code == 404 and r.json() == {"error": "FRONTEND_NOT_FOUND"}


def test_frontend_served(client, tmp_path, monkeypatch):
    page = tmp_path / "index.html"
    page.write_text("<!doctype html><title>AgentShield</title>")
    monkeypatch.setattr(main, "INDEX_PATH", page)
    r = client.get("/")
    assert r.status_code == 200
    assert r.text == "<!doctype html><title>AgentShield</title>"
    assert r.headers["content-type"].startswith("text/html")


def test_index_path_is_next_to_main():
    assert main.INDEX_PATH == main.Path(main.__file__).with_name("index.html")
