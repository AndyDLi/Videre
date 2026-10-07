"""Opt-in fixed-arrival-rate checks against a private HTTP fixture, never the live app."""

import json
import os
import subprocess
import threading
from collections import Counter
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import monotonic, sleep

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("VIDERE_RUN_K6_TESTS") != "1", reason="set VIDERE_RUN_K6_TESTS=1 to run private k6 fixtures"
)
ROOT = Path(__file__).resolve().parents[1]
NODE = {
    "id": "node-0", "cluster_id": "cluster-a", "cpu_cores": 4, "memory_gb": 16,
    "gpu_count": 0, "health_state": "READY", "updated_at": "2026-10-06T00:00:00Z",
}
JOB = {
    "id": "job-0", "cluster_id": "cluster-a", "lifecycle_state": "RUNNING",
    "requested_cpu_cores": 1, "requested_memory_gb": 1, "requested_gpu_count": 0,
    "priority": 0, "pod_name": None, "failure_reason": None,
    "created_at": "2026-10-06T00:00:00Z", "started_at": None, "completed_at": None,
}
CAPACITY = {
    "cluster_id": "cluster-a", "total_gpus": 4, "unavailable_gpus": 1,
    "degraded_gpus": 1, "idle_gpus": 1, "active_gpus": 1, "idle_reserved_gpus": 1,
    "drained_node_count": 0, "unschedulable_node_count": 0, "queued_job_count": 0,
    "queueing_delay_event_count": 0, "fragmentation_event_count": 0,
}
AI = {
    "entity_type": "node", "entity_id": "node-0", "summary": "Node is ready.",
    "next_steps": ["Inspect telemetry."], "from_cache": True, "cache_age_seconds": 1,
}


@contextmanager
def fixture_server(*, bad_path=None, replacement=None, status=200, delay=0):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.command, self.path, None, monotonic()))
            self.respond()

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.command, self.path, body, monotonic()))
            self.respond()

        def respond(self):
            sleep(delay)
            body = {
                "/capacity": [CAPACITY],
                "/nodes?limit=50&offset=0": {"items": [NODE], "total": 1, "limit": 50, "offset": 0},
                "/jobs?limit=10&offset=0": {"items": [JOB], "total": 1, "limit": 10, "offset": 0},
                "/nodes/node-0": {**NODE, "gpus": []},
                "/ai/analyze": AI,
            }.get(self.path)
            affected = self.path == bad_path
            if affected and replacement is not None:
                body = replacement
            encoded = json.dumps(body).encode()
            self.send_response(status if affected else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            try:
                self.wfile.write(encoded)
            except (BrokenPipeError, ConnectionResetError):
                pass  # An intentionally aborted k6 request can close the fixture connection.

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def run_k6(tmp_path, url, *, script=None, **overrides):
    summary_path = tmp_path / "summary.json"
    env = {
        "PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"),
        "API_BASE_URL": url, "ENVIRONMENT": "private-fixture", "RPS": "5",
        "DURATION_SECONDS": "10", "NODE_ID": "node-0", "AI_ENTITY_TYPE": "node",
        "AI_ENTITY_ID": "node-0", "SUMMARY_PATH": str(summary_path), "MAX_VUS": "10",
        "K6_NO_USAGE_REPORT": "true", "WORKLOAD_REVISION": "fixture-harness",
        "BACKEND_REVISION": "fixture-backend", **overrides,
    }
    result = subprocess.run(
        [os.environ.get("VIDERE_K6_BINARY", "k6"), "run", "--quiet", str(script or ROOT / "scripts/k6-requests.js")],
        env=env, text=True, capture_output=True, timeout=35,
    )
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else None
    return result, summary


@pytest.mark.parametrize("rps", [1, 5, 7])
def test_fixed_rate_route_mix_and_one_request_per_iteration(tmp_path, rps):
    with fixture_server() as (url, requests):
        result, summary = run_k6(tmp_path, url, RPS=str(rps))
    assert result.returncode == 0, result.stdout + result.stderr
    expected = rps * 10
    actual = len(requests)
    assert abs(actual - expected) <= 1
    route_counts = Counter(path for _, path, _, _ in requests)
    assert set(route_counts) == {
        "/capacity", "/nodes?limit=50&offset=0", "/jobs?limit=10&offset=0", "/nodes/node-0", "/ai/analyze",
    }
    assert max(route_counts.values()) - min(route_counts.values()) <= 1
    assert all(body == {"entity_type": "node", "entity_id": "node-0"}
               for method, _, body, _ in requests if method == "POST")
    times = [request[3] for request in requests]
    assert 8.5 <= times[-1] - times[0] <= 11
    # Center buckets between scheduled arrivals and exclude partly observed boundary seconds.
    buckets = Counter(int(timestamp - times[0] + 0.5) for timestamp in times)
    interior_seconds = range(1, int(times[-1] - times[0] + 0.5))
    assert all(max(1, rps - 2) <= buckets[second] <= rps + 2 for second in interior_seconds)
    assert summary["passed"] is True
    assert summary["config"]["offered_rps"] == rps
    assert summary["config"]["workload_revision"] == "fixture-harness"
    assert summary["config"]["backend_revision"] == "fixture-backend"
    assert summary["counts"] == {
        "expected_iterations": expected, "started_iterations": actual, "completed_iterations": actual,
        "iterations": actual, "http_requests": actual, "successful_requests": actual, "dropped_iterations": 0,
    }
    assert summary["successful_rps"] == actual / 10
    for route, path in {
        "capacity": "/capacity", "nodes": "/nodes?limit=50&offset=0", "jobs": "/jobs?limit=10&offset=0",
        "node_detail": "/nodes/node-0", "ai_cached": "/ai/analyze",
    }.items():
        assert set(summary["routes"][route]["duration_ms"]) >= {"med", "p(95)", "p(99)", "max"}
        assert summary["routes"][route]["successful_requests"] == route_counts[path]


@pytest.mark.parametrize(("path", "body"), [
    ("/ai/analyze", {**AI, "from_cache": False}),
    ("/ai/analyze", {**AI, "summary": " "}),
    ("/ai/analyze", {**AI, "next_steps": []}),
    ("/ai/analyze", {**AI, "entity_id": "wrong-node"}),
    ("/capacity", {}),
    ("/capacity", [{**CAPACITY, "idle_reserved_gpus": 2}]),
    ("/capacity", [{**CAPACITY, "total_gpus": 5}]),
    ("/nodes?limit=50&offset=0", {"items": [{}], "total": 1, "limit": 50, "offset": 0}),
    ("/jobs?limit=10&offset=0", {"items": [{}], "total": 1, "limit": 10, "offset": 0}),
    ("/nodes/node-0", {**NODE, "gpus": [{}]}),
])
def test_malformed_200_or_uncached_ai_aborts(tmp_path, path, body):
    with fixture_server(bad_path=path, replacement=body) as (url, requests):
        result, summary = run_k6(tmp_path, url)
    assert result.returncode != 0
    assert summary["passed"] is False
    assert summary["check_failure_rate"] > 0
    assert len(requests) < 50
    assert "Invalid " in result.stdout + result.stderr


@pytest.mark.parametrize("status", [302, 404, 429, 503])
def test_http_errors_fail_without_retry_or_redirect(tmp_path, status):
    with fixture_server(bad_path="/capacity", status=status) as (url, requests):
        result, summary = run_k6(tmp_path, url)
    assert result.returncode != 0
    assert summary["passed"] is False
    assert requests and len(requests) < 50
    assert summary["counts"]["http_requests"] == len(requests)


@pytest.mark.parametrize("overrides", [
    {"RPS": ""}, {"RPS": "0"}, {"RPS": "501"}, {"RPS": "1.5"},
    {"DURATION_SECONDS": "9"}, {"DURATION_SECONDS": "601"},
    {"API_BASE_URL": ""}, {"API_BASE_URL": "ftp://localhost"},
    {"ENVIRONMENT": ""}, {"NODE_ID": ""}, {"AI_ENTITY_ID": ""},
    {"AI_ENTITY_TYPE": "cluster"}, {"MAX_VUS": "0"}, {"MAX_VUS": "501"},
    {"P95_MS": "NaN"}, {"P99_MS": "-1"}, {"SUMMARY_PATH": ""},
])
def test_invalid_configuration_sends_no_requests(tmp_path, overrides):
    with fixture_server() as (url, requests):
        result, _ = run_k6(tmp_path, url, **overrides)
    assert result.returncode != 0
    assert not requests


def test_slow_responses_expose_generator_drops(tmp_path):
    with fixture_server(delay=0.3) as (url, requests):
        result, summary = run_k6(tmp_path, url, RPS="20", MAX_VUS="1")
    assert result.returncode != 0
    assert summary["passed"] is False
    assert summary["load_generator_limited"] is True
    assert summary["counts"]["dropped_iterations"] > 0
    assert 0 < summary["counts"]["completed_iterations"] < 200
    assert summary["counts"]["http_requests"] == len(requests)
    assert summary["counts"]["successful_requests"] == len(requests)
    assert "load generator could not sustain offered rate" in result.stdout


def test_supplied_latency_threshold_can_fail_correct_responses(tmp_path):
    with fixture_server(delay=0.03) as (url, _):
        result, summary = run_k6(tmp_path, url, P95_MS="1", P99_MS="1")
    assert result.returncode != 0
    assert summary["passed"] is False
    assert abs(summary["counts"]["successful_requests"] - 50) <= 1
    assert any("p(95)<=1" in failure for failure in summary["failed_thresholds"])
    assert any("p(99)<=1" in failure for failure in summary["failed_thresholds"])


@pytest.mark.parametrize(("delta", "mismatch", "passed"), [
    (-1, False, True), (0, False, True), (1, False, True),
    (-2, False, False), (2, False, False), (0, True, False),
])
def test_summary_bounds_nominal_count_and_keeps_actual_accounting(tmp_path, delta, mismatch, passed):
    actual = 1500 + delta
    metrics = {
        name: {"values": {"count": actual}}
        for name in ("started_iterations", "completed_iterations", "iterations", "http_reqs", "successful_requests")
    }
    if mismatch:
        metrics["http_reqs"]["values"]["count"] -= 1
    metrics["dropped_iterations"] = {"values": {"count": 0}}
    metrics["checks"] = {"values": {"rate": 1}}
    metrics["http_req_failed"] = {"values": {"rate": 0}}
    probe = tmp_path / "summary-probe.js"
    workload_path = json.dumps(str(ROOT / "scripts/k6-requests.js"))
    probe.write_text(
        "import {handleSummary as summarize, options as workloadOptions} from " + workload_path + ";\n"
        "import exec from 'k6/execution';\n"
        "import {Counter} from 'k6/metrics';\n"
        "const actualSuccesses = new Counter('successful_requests');\n"
        "export const options = {vus: 1, iterations: 1, "
        "thresholds: {successful_requests: workloadOptions.thresholds.successful_requests}};\n"
        "export default function() {\n"
        "actualSuccesses.add(" + str(actual) + ");\n"
        "const result = JSON.parse(summarize(" + json.dumps({"metrics": metrics}) + ")[__ENV.SUMMARY_PATH]);\n"
        "if (result.passed !== " + json.dumps(passed) + ") exec.test.abort('Wrong boundary/accounting decision');\n"
        "if (result.counts.http_requests !== " + str(actual - int(mismatch)) +
        " || result.successful_rps !== " + str(actual / 300) + ") exec.test.abort('Lost actual accounting');\n"
        "}\n"
    )
    with fixture_server() as (url, requests):
        result, _ = run_k6(tmp_path, url, script=probe, DURATION_SECONDS="300")
    assert (result.returncode == 0) == (abs(delta) <= 1), result.stdout + result.stderr
    assert not requests
