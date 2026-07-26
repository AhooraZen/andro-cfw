"""
Tests for the shared proxy daemon.

The behaviour that matters here is the one the old in-process load balancer got
wrong: knowing how much quota an account has already spent, and moving off it
before Cloudflare starts refusing requests.
"""

import http.client
import json
import time
from unittest.mock import patch

import pytest

from andro_cfw.daemon import (
    CONTROL_PREFIX,
    Daemon,
    clear_daemon_file,
    daemon_status,
    find_running_daemon,
    read_daemon_file,
)
from andro_cfw.session import CFWSession, WorkerEntry
from andro_cfw.store import FREE_PLAN_DAILY_REQUESTS, UsageStore


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Keep every daemon artefact out of the real ~/.andro_cfw."""
    from andro_cfw import daemon as daemon_module

    monkeypatch.setattr(daemon_module, "DAEMON_FILE", tmp_path / "daemon.json")
    return tmp_path


def make_daemon(tmp_path, *labels, headroom=0.95, port=0):
    workers = [
        WorkerEntry(f"w{i}", f"https://w{i}.workers.dev", label)
        for i, label in enumerate(labels, start=1)
    ]
    session = CFWSession(workers=workers)
    session._session_path = tmp_path / "cfw.session"
    store = UsageStore(path=tmp_path / "usage.db")
    return Daemon(session, store=store, port=port, headroom=headroom), session, store


# --------------------------------------------------------------------------- #
# Quota-aware selection
# --------------------------------------------------------------------------- #

def test_worker_is_abandoned_before_it_runs_out_of_quota(isolated):
    """
    The whole point of counting: leave an account at the headroom threshold so
    the bot never experiences the 429 that used to be the only signal.
    """
    daemon, _session, store = make_daemon(isolated, "acc1", "acc2", headroom=0.5)
    ceiling = daemon.quota_ceiling()
    assert ceiling == FREE_PLAN_DAILY_REQUESTS // 2

    assert daemon._pick_active_worker() == 0

    for _ in range(3):
        store.record_request("w1", latency_ms=10.0)
    # Push w1 over its ceiling without any 429 ever occurring.
    with patch.object(store, "requests_today", side_effect=lambda name, at=None: ceiling if name == "w1" else 0):
        assert daemon._pick_active_worker() == 1

    store.close()


def test_fastest_available_worker_wins(isolated):
    """Chosen by measured latency, not by position in the list."""
    daemon, _session, store = make_daemon(isolated, "acc1", "acc2", "acc3")

    for _ in range(5):
        store.record_request("w1", latency_ms=400.0)
        store.record_request("w2", latency_ms=45.0)
        store.record_request("w3", latency_ms=120.0)

    assert daemon._pick_active_worker() == 1
    store.close()


def test_an_unmeasured_worker_is_tried_so_it_can_earn_a_sample(isolated):
    """Otherwise a newly added account could never win and would stay unused."""
    daemon, _session, store = make_daemon(isolated, "acc1", "acc2")

    for _ in range(5):
        store.record_request("w1", latency_ms=20.0)

    assert daemon._pick_active_worker() == 1
    store.close()


def test_exhausted_workers_are_skipped(isolated):
    daemon, session, store = make_daemon(isolated, "acc1", "acc2")
    session.workers[0].exhausted_until = time.time() + 3600

    assert daemon._pick_active_worker() == 1
    store.close()


def test_all_workers_over_quota_falls_back_instead_of_crashing(isolated):
    """
    With nothing eligible the daemon must still answer with *something*; the
    base policy picks whichever account resets soonest.
    """
    daemon, session, store = make_daemon(isolated, "acc1", "acc2")
    for worker in session.workers:
        worker.exhausted_until = time.time() + 3600
    session.workers[1].exhausted_until = time.time() + 60

    assert daemon._pick_active_worker() == 1
    store.close()


# --------------------------------------------------------------------------- #
# Accounting
# --------------------------------------------------------------------------- #

def test_every_proxied_request_is_counted(isolated):
    daemon, session, store = make_daemon(isolated, "acc1")
    worker = session.workers[0]

    daemon._record_result(worker, 51.0, 200, ok=True)
    daemon._record_result(worker, 63.0, 200, ok=True)

    assert store.requests_today("w1") == 2
    assert store.recent_latency("w1") == 57.0
    store.close()


def test_failover_is_written_to_the_event_log(isolated):
    daemon, _session, store = make_daemon(isolated, "acc1", "acc2")

    with patch.object(daemon.session, "_persist"):
        daemon._mark_exhausted(0, "HTTP 429")

    kinds = [event["kind"] for event in store.recent_events()]
    assert "failover" in kinds
    store.close()


def test_retries_are_logged_so_a_flapping_edge_is_visible(isolated):
    daemon, session, store = make_daemon(isolated, "acc1")
    daemon._note_retry(session.workers[0], 502, 0)

    event = store.recent_events()[0]
    assert event["kind"] == "retry"
    assert "502" in event["detail"]
    store.close()


# --------------------------------------------------------------------------- #
# Control endpoints
# --------------------------------------------------------------------------- #

def test_api_state_matches_the_dashboard_contract(isolated):
    daemon, _session, store = make_daemon(isolated, "acc1", "acc2")
    store.record_request("w1", latency_ms=50.0, status=200)

    state = daemon.api_state()

    assert set(state) >= {
        "daemon", "quota", "workers", "latency_series", "series_meta", "events", "totals"
    }
    assert state["totals"]["requests_today"] == 1
    assert state["totals"]["workers"] == 2

    first = state["workers"][0]
    assert set(first) >= {
        "index", "worker_name", "worker_url", "account_label", "active", "state",
        "requests_today", "quota_fraction", "latency_ms", "exhausted_until", "last_error",
    }
    assert first["requests_today"] == 1
    assert first["state"] == "available"
    store.close()


def test_api_state_reports_quota_state_without_an_exhaustion_flag(isolated):
    """A worker over its ceiling reads as 'quota' even though nothing 429'd."""
    daemon, _session, store = make_daemon(isolated, "acc1", headroom=0.0)
    store.record_request("w1", latency_ms=10.0)

    state = daemon.api_state()
    assert state["workers"][0]["state"] == "quota"
    assert state["totals"]["available"] == 0
    store.close()


def test_api_state_is_json_serialisable_when_empty(isolated):
    """The dashboard polls immediately at startup, before any traffic exists."""
    daemon, _session, store = make_daemon(isolated, "acc1")
    json.dumps(daemon.api_state())
    store.close()


# --------------------------------------------------------------------------- #
# Discovery & end to end
# --------------------------------------------------------------------------- #

def test_daemon_advertises_itself_and_answers_the_ping(isolated):
    daemon, _session, store = make_daemon(isolated, "acc1")
    daemon.start()
    try:
        advertised = read_daemon_file()
        assert advertised["port"] == daemon.port

        assert find_running_daemon() == f"http://127.0.0.1:{daemon.port}"

        status = daemon_status()
        assert status["running"] is True
        assert status["port"] == daemon.port
    finally:
        daemon.stop()
        store.close()


def test_a_stale_advertisement_is_not_trusted(isolated):
    """
    A daemon killed with SIGKILL leaves the file behind, and its port may since
    have been taken by something else. Only a successful ping counts.
    """
    from andro_cfw import daemon as daemon_module

    daemon_module.DAEMON_FILE.write_text(
        json.dumps({"host": "127.0.0.1", "port": 9, "pid": 1, "started_at": 0}),
        encoding="utf-8",
    )
    assert find_running_daemon(timeout=0.3) is None
    assert daemon_status()["running"] is False


def test_stopping_removes_the_advertisement(isolated):
    daemon, _session, store = make_daemon(isolated, "acc1")
    daemon.start()
    assert read_daemon_file() is not None
    daemon.stop()
    assert read_daemon_file() is None
    store.close()


def test_clear_daemon_file_is_safe_when_absent(isolated):
    clear_daemon_file()   # must not raise


def test_dashboard_and_api_are_served_over_a_real_socket(isolated):
    daemon, _session, store = make_daemon(isolated, "acc1", "acc2")
    daemon.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", daemon.port, timeout=10)

        conn.request("GET", f"{CONTROL_PREFIX}/api/state")
        resp = conn.getresponse()
        state = json.loads(resp.read())
        assert resp.status == 200
        assert len(state["workers"]) == 2

        conn.request("GET", f"{CONTROL_PREFIX}/")
        resp = conn.getresponse()
        page = resp.read()
        assert resp.status == 200
        assert b"<" in page

        conn.request("GET", f"{CONTROL_PREFIX}/api/nope")
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 404

        conn.close()
    finally:
        daemon.stop()
        store.close()


def test_control_prefix_cannot_swallow_a_bot_api_call(isolated):
    """
    Bot API paths begin with /bot or /file/bot. If the control prefix ever
    started matching loosely, real traffic would be answered with the dashboard.
    """
    daemon, _session, store = make_daemon(isolated, "acc1")
    seen = {}

    def fake_super(handler):
        seen["path"] = handler.path

    with patch("andro_cfw.loadbalancer.LoadBalancer._proxy_request", side_effect=fake_super):
        class Handler:
            path = "/bot123:ABC/getMe"
            command = "GET"
        daemon._proxy_request(Handler())

    assert seen["path"] == "/bot123:ABC/getMe"
    store.close()
