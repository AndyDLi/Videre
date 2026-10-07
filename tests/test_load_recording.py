"""Recorder checks use local data and fake command boundaries."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def recorder():
    path = ROOT / "scripts/record-load.py"
    if not path.exists():
        pytest.fail("The load recorder has not been implemented")
    spec = importlib.util.spec_from_file_location("record_load", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exposition_handles_escaped_labels_and_ignores_unrelated_metrics(recorder):
    parsed = recorder.parse_metrics(
        "unrelated_total 999\n"
        'videre_database_query_seconds_count{operation="get,\\"node",outcome="ok"} 12\n'
        "videre_database_connections_checked_out 3\n"
    )
    assert len(parsed) == 2
    assert parsed[("videre_database_query_seconds_count", (("operation", 'get,"node'), ("outcome", "ok")))] == 12
    assert parsed[("videre_database_connections_checked_out", ())] == 3


@pytest.mark.parametrize(
    "text",
    [
        'videre_ai_cache_reads_total{result="hit"} NaN',
        "videre_database_query_seconds_count broken",
        'videre_ai_cache_reads_total{result="hit"} 1\nvidere_ai_cache_reads_total{result="hit"} 2',
    ],
)
def test_invalid_known_metrics_reject_collection(recorder, text):
    with pytest.raises(ValueError):
        recorder.parse_metrics(text)


def test_histograms_report_interval_estimates_with_seconds_units(recorder):
    before = recorder.parse_metrics("""videre_database_query_seconds_bucket{operation="select",outcome="ok",le="0.1"} 10
videre_database_query_seconds_bucket{operation="select",outcome="ok",le="0.2"} 10
videre_database_query_seconds_bucket{operation="select",outcome="ok",le="+Inf"} 10
videre_database_query_seconds_count{operation="select",outcome="ok"} 10
videre_database_query_seconds_sum{operation="select",outcome="ok"} 1
""")
    after = recorder.parse_metrics("""videre_database_query_seconds_bucket{operation="select",outcome="ok",le="0.1"} 20
videre_database_query_seconds_bucket{operation="select",outcome="ok",le="0.2"} 110
videre_database_query_seconds_bucket{operation="select",outcome="ok",le="+Inf"} 110
videre_database_query_seconds_count{operation="select",outcome="ok"} 110
videre_database_query_seconds_sum{operation="select",outcome="ok"} 16
""")
    summary = recorder.summarize_metrics([before, after])
    histogram = summary["histograms"][0]
    assert histogram["unit"] == "seconds"
    assert histogram["count"] == 100
    assert histogram["mean"] == pytest.approx(0.15)
    assert histogram["p95_bucket_estimate"] == pytest.approx(0.1944444444)
    assert histogram["p99_bucket_estimate"] == pytest.approx(0.1988888889)
    assert summary["counter_resets"] == []


def test_intermediate_counter_reset_invalidates_histogram_delta(recorder):
    samples = [
        recorder.parse_metrics(f'videre_ai_cache_reads_total{{result="hit"}} {value}') for value in (100, 2, 150)
    ]
    summary = recorder.summarize_metrics(samples)
    assert summary["counter_resets"]
    assert summary["counters"][0]["delta"] is None


def test_new_series_start_at_zero_and_removed_series_are_flagged(recorder):
    empty = recorder.parse_metrics("videre_database_connections_checked_out 0")
    added = recorder.parse_metrics('videre_ai_cache_reads_total{result="miss"} 4')
    assert recorder.summarize_metrics([empty, added])["counters"][0]["delta"] == 4
    assert recorder.summarize_metrics([added, empty])["missing_series"]


def test_checked_out_max_tracks_intermediate_samples(recorder):
    samples = [recorder.parse_metrics(f"videre_database_connections_checked_out {value}") for value in (1, 7, 2)]
    assert recorder.summarize_metrics(samples)["connections_checked_out_max"] == 7


def test_docker_stats_units_and_cpu_are_normalized(recorder):
    parsed = recorder.parse_docker_stats('{"Name":"db","CPUPerc":"150.50%","MemUsage":"2.5MiB / 1GiB"}\n')
    assert parsed["db"]["cpu_cores"] == 1.505
    assert parsed["db"]["memory_bytes"] == 2621440
    assert parsed["db"]["memory_limit_bytes"] == 1073741824


def test_proc_stat_counts_threads_cpu_and_handles_spaces_in_comm(recorder):
    fields = ["R"] + ["0"] * 21
    fields[11] = "120"
    fields[12] = "80"
    fields[19] = "1234"
    fields[21] = "5"
    parsed = recorder.parse_process_stat("42 (k6 worker) " + " ".join(fields), 100, 4096)
    assert parsed == {"cpu_seconds": 2, "start_ticks": 1234, "rss_bytes": 20480}


def test_cgroup_reset_and_oom_are_inconclusive(recorder):
    first = {"db": {"cpu": {"usage_usec": 100, "nr_throttled": 1}, "memory": {"oom_kill": 0}}}
    last = {"db": {"cpu": {"usage_usec": 1, "nr_throttled": 2}, "memory": {"oom_kill": 1}}}
    flags = recorder.cgroup_flags([first, last])
    assert any("reset" in flag for flag in flags)
    assert any("oom_kill" in flag for flag in flags)
    assert not any("throttled" in flag for flag in flags)


def test_collection_error_saves_failure_and_returns_nonzero(recorder, monkeypatch, tmp_path):
    def broken(*_args, **_kwargs):
        raise RuntimeError("metrics endpoint unavailable")

    monkeypatch.setattr(recorder, "inspect_containers", broken)
    status = recorder.main(
        [
            "--api-base-url",
            "http://127.0.0.1:1",
            "--environment",
            "test",
            "--containers",
            "backend,db,redis",
            "--rps",
            "5",
            "--duration-seconds",
            "10",
            "--output",
            str(tmp_path),
            "--node-id",
            "n",
            "--ai-entity-type",
            "node",
            "--ai-entity-id",
            "n",
            "--idle",
        ]
    )
    assert status != 0
    import json

    summary = json.loads((tmp_path / "report.json").read_text())
    assert summary["status"] == "collection_failed"
    assert "metrics endpoint unavailable" in summary["errors"][0]


def test_native_k6_exit_is_preserved_and_artifacts_are_recorded(recorder, monkeypatch, tmp_path):
    import json
    import os

    binary = tmp_path / "fake-k6"
    binary.write_text(
        "#!/usr/bin/env python3\nimport os,json,time\ntime.sleep(0.4)\n"
        "json.dump({'passed':False,'load_generator_limited':False},open(os.environ['SUMMARY_PATH'],'w'))\n"
        "print('failed fixture')\nraise SystemExit(7)\n"
    )
    binary.chmod(0o755)
    output = tmp_path / "artifacts"
    output.mkdir()
    inspected = {
        name: {
            "id": name,
            "started_at": "before",
            "restart_count": 0,
            "image_id": "sha256:image",
            "resources": {},
            "oom_killed": False,
            "image_revision": "fixture",
        }
        for name in ("backend", "db", "redis")
    }
    monkeypatch.setattr(recorder, "inspect_containers", lambda _names: inspected)
    monkeypatch.setattr(recorder, "git_metadata", lambda: {"head": "fixture", "backend_source_sha256": "fixture"})
    monkeypatch.setattr(
        recorder,
        "backend_metrics",
        lambda _url: (
            "videre_database_connections_checked_out 0\n",
            recorder.parse_metrics(
                'videre_database_connections_checked_out 0\nvidere_ai_cache_reads_total{result="hit"} 0\n'
                + "".join(
                    base + "_count 0\n" + base + "_sum 0\n" + base + '_bucket{le="+Inf"} 0\n'
                    for base in recorder.HISTOGRAMS
                )
            ),
        ),
    )
    monkeypatch.setattr(
        recorder,
        "cgroup_sample",
        lambda _names: {name: {"cpu": {"usage_usec": 1}, "memory": {"oom_kill": 0}} for name in inspected},
    )
    monkeypatch.setattr(
        recorder,
        "command",
        lambda _args: "\n".join(
            json.dumps({"Name": name, "CPUPerc": "0.0%", "MemUsage": "1MiB / 1GiB"}) for name in inspected
        ),
    )
    status = recorder.main(
        [
            "--api-base-url",
            "http://127.0.0.1:1",
            "--environment",
            "test",
            "--containers",
            "backend,db,redis",
            "--rps",
            "5",
            "--duration-seconds",
            "10",
            "--output",
            str(output),
            "--node-id",
            "n",
            "--ai-entity-type",
            "node",
            "--ai-entity-id",
            "n",
            "--k6-binary",
            str(binary),
        ]
    )
    assert status == 7
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "failed"
    assert report["k6_exit_code"] == 7
    assert (output / "k6-stdout.log").read_text().strip() == "failed fixture"
    sample = json.loads((output / "samples.jsonl").read_text().splitlines()[0])
    assert sample["generator"]["rss_bytes"] >= 0
    assert sample["generator"]["cpu_seconds"] >= 0
    assert not Path(f"/proc/{sample['generator']['pid']}").exists()
    assert json.loads((output / "environment.json").read_text())["generator_shares_host"] is True
    assert (output / "backend-before.prom").exists() and (output / "backend-after.prom").exists()
    assert os.path.exists(output / "k6-summary.json")


def test_backend_restart_invalidates_counter_deltas_even_if_final_values_grow(recorder):
    samples = [
        recorder.parse_metrics('process_start_time_seconds 100\nvidere_ai_cache_reads_total{result="hit"} 10'),
        recorder.parse_metrics('process_start_time_seconds 200\nvidere_ai_cache_reads_total{result="hit"} 20'),
    ]
    result = recorder.summarize_metrics(samples)
    assert result["backend_process_restarted"] is True
    assert result["counters"][0]["delta"] is None


def test_cpu_throttling_is_capacity_evidence_without_invalidating_run(recorder):
    before = {"db": {"cpu": {"usage_usec": 100, "nr_throttled": 1}, "memory": {"oom_kill": 0}}}
    after = {"db": {"cpu": {"usage_usec": 200, "nr_throttled": 3}, "memory": {"oom_kill": 0}}}
    assert recorder.cgroup_flags([before, after]) == []
    assert recorder.cgroup_deltas(before, after)["db"]["cpu"]["nr_throttled"] == 2


def test_docker_inspect_accepts_null_image_labels(recorder, monkeypatch):
    import json

    inspected = [
        {
            "Name": "/backend",
            "Id": "id",
            "Image": "sha256:image",
            "RestartCount": 0,
            "State": {"Running": True, "StartedAt": "time", "OOMKilled": False},
            "HostConfig": {},
            "Config": {"Image": "backend:fixture", "Labels": None},
        }
    ]
    monkeypatch.setattr(recorder, "command", lambda _args: json.dumps(inspected))
    assert recorder.inspect_containers(["backend"])["backend"]["image_revision"] is None
