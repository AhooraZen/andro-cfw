import threading
import time
from datetime import datetime, timezone

from andro_cfw.store import UsageStore, utc_day

DAY = 86400.0

# A UTC midnight with no ambiguity about which calendar day it belongs to.
MIDNIGHT = datetime(2024, 3, 10, 0, 0, 0, tzinfo=timezone.utc).timestamp()


def make_store(tmp_path, **kwargs):
    return UsageStore(path=tmp_path / "usage.db", **kwargs)


# --------------------------------------------------------------------------- #
# Day keys
# --------------------------------------------------------------------------- #

def test_utc_day_returns_the_utc_calendar_date():
    assert utc_day(MIDNIGHT) == "2024-03-10"
    assert utc_day(MIDNIGHT + 12 * 3600) == "2024-03-10"


def test_utc_day_changes_at_utc_midnight_not_local_midnight():
    """
    Cloudflare's free-tier quota resets at UTC midnight. An off-by-one here means
    the balancer keeps treating an account as exhausted for a whole extra day.
    """
    assert utc_day(MIDNIGHT - 1) == "2024-03-09"
    assert utc_day(MIDNIGHT + 1) == "2024-03-10"
    assert utc_day(MIDNIGHT - 1) != utc_day(MIDNIGHT + 1)


def test_utc_day_defaults_to_now():
    assert utc_day() == utc_day(time.time())


# --------------------------------------------------------------------------- #
# Recording requests
# --------------------------------------------------------------------------- #

def test_record_request_counts_one_request(tmp_path):
    store = make_store(tmp_path)
    assert store.requests_today("w1", at=MIDNIGHT) == 0

    store.record_request("w1", at=MIDNIGHT)

    assert store.requests_today("w1", at=MIDNIGHT) == 1


def test_repeated_records_accumulate_rather_than_overwrite(tmp_path):
    """The upsert has to add to the existing row, not replace it."""
    store = make_store(tmp_path)
    for _ in range(5):
        store.record_request("w1", at=MIDNIGHT + 60)

    assert store.requests_today("w1", at=MIDNIGHT) == 5


def test_counters_are_kept_per_worker(tmp_path):
    store = make_store(tmp_path)
    store.record_request("w1", at=MIDNIGHT)
    store.record_request("w1", at=MIDNIGHT)
    store.record_request("w2", at=MIDNIGHT)

    assert store.requests_today("w1", at=MIDNIGHT) == 2
    assert store.requests_today("w2", at=MIDNIGHT) == 1


def test_requests_from_an_earlier_day_do_not_count_towards_today(tmp_path):
    """Each UTC day gets its own allowance, so yesterday's traffic must not carry over."""
    store = make_store(tmp_path)
    store.record_request("w1", at=MIDNIGHT - 2 * DAY)
    store.record_request("w1", at=MIDNIGHT + 3600)

    assert store.requests_today("w1", at=MIDNIGHT) == 1
    assert store.requests_today("w1", at=MIDNIGHT - 2 * DAY) == 1


def test_usage_summary_reports_every_worker_seen_today(tmp_path):
    store = make_store(tmp_path)
    store.record_request("w1", at=MIDNIGHT)
    store.record_request("w1", at=MIDNIGHT)
    store.record_request("w2", at=MIDNIGHT)
    store.record_request("w3", at=MIDNIGHT - DAY)

    assert store.usage_summary(at=MIDNIGHT) == {"w1": 2, "w2": 1}


def test_usage_summary_is_empty_before_any_traffic(tmp_path):
    assert make_store(tmp_path).usage_summary(at=MIDNIGHT) == {}


# --------------------------------------------------------------------------- #
# Latency
# --------------------------------------------------------------------------- #

def test_recent_latency_is_the_median_so_one_timeout_cannot_skew_it(tmp_path):
    """
    A single 30-second timeout would drag the mean far above every real sample and
    disqualify an otherwise healthy account from ever being picked again.
    """
    store = make_store(tmp_path)
    samples = [40.0, 45.0, 50.0, 55.0, 30000.0]
    for index, latency in enumerate(samples):
        store.record_request("w1", latency_ms=latency, at=MIDNIGHT + index)

    mean = sum(samples) / len(samples)
    assert store.recent_latency("w1") == 50.0
    assert abs(store.recent_latency("w1") - mean) > 1000


def test_recent_latency_averages_the_middle_pair_for_an_even_count(tmp_path):
    store = make_store(tmp_path)
    for index, latency in enumerate([10.0, 20.0, 30.0, 100.0]):
        store.record_request("w1", latency_ms=latency, at=MIDNIGHT + index)

    assert store.recent_latency("w1") == 25.0


def test_recent_latency_is_none_without_any_samples(tmp_path):
    assert make_store(tmp_path).recent_latency("w1") is None


def test_recent_latency_ignores_failed_requests(tmp_path):
    """A failure's latency is the time until the error, which says nothing about health."""
    store = make_store(tmp_path)
    store.record_request("w1", latency_ms=50.0, at=MIDNIGHT)
    store.record_request("w1", latency_ms=9000.0, ok=False, status=502, at=MIDNIGHT + 1)
    store.record_request("w1", latency_ms=60.0, at=MIDNIGHT + 2)

    assert store.recent_latency("w1") == 55.0


def test_recent_latency_ignores_samples_without_a_measurement(tmp_path):
    store = make_store(tmp_path)
    store.record_request("w1", at=MIDNIGHT)
    store.record_request("w1", latency_ms=None, at=MIDNIGHT + 1)
    store.record_request("w1", latency_ms=70.0, at=MIDNIGHT + 2)

    assert store.recent_latency("w1") == 70.0


def test_recent_latency_only_looks_at_the_last_window_samples(tmp_path):
    store = make_store(tmp_path)
    for index in range(10):
        store.record_request("w1", latency_ms=1000.0, at=MIDNIGHT + index)
    for index in range(10, 14):
        store.record_request("w1", latency_ms=10.0, at=MIDNIGHT + index)

    assert store.recent_latency("w1", window=4) == 10.0


def test_recent_latency_is_kept_per_worker(tmp_path):
    store = make_store(tmp_path)
    store.record_request("w1", latency_ms=10.0, at=MIDNIGHT)
    store.record_request("w2", latency_ms=900.0, at=MIDNIGHT)

    assert store.recent_latency("w1") == 10.0
    assert store.recent_latency("w2") == 900.0


def test_latency_series_buckets_samples_per_worker(tmp_path):
    store = make_store(tmp_path)
    since = time.time() - 100

    store.record_request("w1", latency_ms=10.0, at=since + 1)
    store.record_request("w1", latency_ms=20.0, at=since + 2)
    store.record_request("w1", latency_ms=80.0, at=since + 99)
    store.record_request("w2", latency_ms=40.0, at=since + 1)

    series = store.latency_series(since, buckets=10)

    assert set(series) == {"w1", "w2"}
    assert [point["bucket"] for point in series["w1"]] == [0, 9]
    assert series["w1"][0]["latency_ms"] == 15.0
    assert series["w1"][1]["latency_ms"] == 80.0
    assert series["w2"] == [{"bucket": 0, "latency_ms": 40.0}]


def test_latency_series_excludes_samples_older_than_the_window(tmp_path):
    store = make_store(tmp_path)
    since = time.time() - 100
    store.record_request("w1", latency_ms=10.0, at=since - 500)
    store.record_request("w2", latency_ms=20.0, at=since + 10)

    assert set(store.latency_series(since, buckets=10)) == {"w2"}


def test_latency_series_is_empty_for_a_range_with_no_samples(tmp_path):
    store = make_store(tmp_path)
    store.record_request("w1", latency_ms=10.0)

    assert store.latency_series(time.time() + 3600) == {}


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #

def test_events_are_returned_newest_first(tmp_path):
    store = make_store(tmp_path)
    store.record_event("failover", worker_name="w1", detail="HTTP 429", at=MIDNIGHT)
    store.record_event("quota", worker_name="w2", detail="exhausted", at=MIDNIGHT + 10)

    events = store.recent_events()

    assert [event["kind"] for event in events] == ["quota", "failover"]
    assert events[0] == {
        "at": MIDNIGHT + 10,
        "worker_name": "w2",
        "kind": "quota",
        "detail": "exhausted",
    }


def test_recent_events_respects_the_limit(tmp_path):
    store = make_store(tmp_path)
    for index in range(10):
        store.record_event("failover", worker_name="w1", detail=str(index), at=MIDNIGHT + index)

    events = store.recent_events(limit=3)

    assert [event["detail"] for event in events] == ["9", "8", "7"]


def test_an_event_may_omit_the_worker_and_detail(tmp_path):
    store = make_store(tmp_path)
    store.record_event("daemon-start", at=MIDNIGHT)

    event = store.recent_events()[0]
    assert event["worker_name"] is None
    assert event["detail"] is None


def test_recent_events_is_empty_on_a_fresh_store(tmp_path):
    assert make_store(tmp_path).recent_events() == []


# --------------------------------------------------------------------------- #
# Housekeeping
# --------------------------------------------------------------------------- #

def test_prune_drops_history_past_the_retention_window(tmp_path):
    """
    Without pruning the samples table grows by one row per proxied request
    forever -- a long-polling bot writes roughly one per second.
    """
    store = make_store(tmp_path, retention_days=2)
    old = MIDNIGHT - 5 * DAY

    store.record_request("w1", latency_ms=999.0, at=old)
    store.record_event("failover", worker_name="w1", detail="ancient", at=old)

    store.prune(at=MIDNIGHT)

    assert store.usage_summary(at=old) == {}
    assert store.requests_today("w1", at=old) == 0
    assert store.recent_latency("w1") is None
    assert store.recent_events() == []


def test_prune_keeps_history_inside_the_retention_window(tmp_path):
    store = make_store(tmp_path, retention_days=7)
    recent = MIDNIGHT - DAY

    store.record_request("w1", latency_ms=42.0, at=recent)
    store.record_event("failover", worker_name="w1", detail="yesterday", at=recent)

    store.prune(at=MIDNIGHT)

    assert store.requests_today("w1", at=recent) == 1
    assert store.recent_latency("w1") == 42.0
    assert [event["detail"] for event in store.recent_events()] == ["yesterday"]


def test_prune_keeps_todays_rows_while_dropping_old_ones(tmp_path):
    store = make_store(tmp_path, retention_days=2)
    store.record_request("w1", latency_ms=10.0, at=MIDNIGHT - 5 * DAY)
    store.record_request("w2", latency_ms=20.0, at=MIDNIGHT + 60)
    store.record_event("old", at=MIDNIGHT - 5 * DAY)
    store.record_event("fresh", at=MIDNIGHT + 60)

    store.prune(at=MIDNIGHT)

    assert store.usage_summary(at=MIDNIGHT) == {"w2": 1}
    assert store.recent_latency("w1") is None
    assert store.recent_latency("w2") == 20.0
    assert [event["kind"] for event in store.recent_events()] == ["fresh"]


# --------------------------------------------------------------------------- #
# Concurrency
# --------------------------------------------------------------------------- #

def test_concurrent_recording_loses_no_requests(tmp_path):
    """
    The daemon is threaded and every request handler shares one store, so an
    unguarded connection would either miscount or raise from SQLite itself.
    """
    store = make_store(tmp_path)
    failures = []
    start = threading.Barrier(8)

    def worker():
        try:
            start.wait()
            for _ in range(50):
                store.record_request("w1", latency_ms=10.0, at=MIDNIGHT)
        except Exception as exc:
            failures.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert store.requests_today("w1", at=MIDNIGHT) == 400
