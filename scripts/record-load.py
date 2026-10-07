#!/usr/bin/env python3
"""Record one fixed-RPS k6 run and interval service/resource evidence using the stdlib."""

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HISTOGRAMS = (
    "videre_database_query_seconds",
    "videre_database_acquisition_seconds",
    "videre_ai_cache_get_seconds",
)
GAUGE = "videre_database_connections_checked_out"
KNOWN = {GAUGE, "videre_ai_cache_reads_total", "process_start_time_seconds"}
KNOWN.update(base + suffix for base in HISTOGRAMS for suffix in ("_bucket", "_sum", "_count"))
LINE = re.compile(r"([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})?\s+(\S+)(?:\s+\S+)?")
LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"(?:,|$)')


def parse_metrics(text):
    result = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[\s{]", line, maxsplit=1)[0]
        if name not in KNOWN:
            continue
        match = LINE.fullmatch(line)
        if not match:
            raise ValueError(f"Malformed metric: {name}")
        labels, offset = {}, 0
        raw = match[2] or ""
        while offset < len(raw):
            item = LABEL.match(raw, offset)
            if not item or item[1] in labels:
                raise ValueError(f"Malformed labels: {name}")
            labels[item[1]] = json.loads('"' + item[2] + '"')
            offset = item.end()
        value = float(match[3])
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"Invalid metric value: {name}")
        key = (name, tuple(sorted(labels.items())))
        if key in result:
            raise ValueError(f"Duplicate metric: {key}")
        result[key] = value
    if not result:
        raise ValueError("No supported backend metrics found")
    return result


def quantile(buckets, count, fraction):
    if count <= 0:
        return None
    target, previous_bound, previous_count = count * fraction, 0.0, 0.0
    for bound, cumulative in sorted(buckets):
        if cumulative < previous_count or bound < 0:
            raise ValueError("Invalid cumulative histogram")
        if cumulative >= target:
            if not math.isfinite(bound):
                return None  # The open-ended bucket cannot give a finite latency estimate.
            if cumulative == previous_count:
                return bound
            return previous_bound + (bound - previous_bound) * (target - previous_count) / (cumulative - previous_count)
        previous_bound, previous_count = bound, cumulative
    return None


def summarize_metrics(samples):
    if not samples:
        raise ValueError("No backend samples")
    starts = [sample.get(("process_start_time_seconds", ())) for sample in samples]
    restarted = len({value for value in starts if value is not None}) > 1
    keys = set().union(*samples)
    resets, missing, deltas = [], [], {}
    for key in sorted(keys):
        name, labels = key
        if name in (GAUGE, "process_start_time_seconds"):
            continue
        values = [sample.get(key) for sample in samples]
        disappeared = any(values[i - 1] is not None and values[i] is None for i in range(1, len(values)))
        reset = any(a is not None and b is not None and b < a for a, b in zip(values, values[1:], strict=False))
        detail = {"metric": name, "labels": dict(labels)}
        if disappeared:
            missing.append(detail)
        if reset:
            resets.append(detail)
        deltas[key] = None if reset or disappeared or restarted else (values[-1] or 0) - (values[0] or 0)
    histograms = []
    for key, count in deltas.items():
        name, labels = key
        if not name.endswith("_count"):
            continue
        base = name[:-6]
        if base not in HISTOGRAMS:
            continue
        total = deltas.get((base + "_sum", labels))
        buckets = []
        valid = count is not None and total is not None
        for (bucket_name, bucket_labels), value in deltas.items():
            attributes = dict(bucket_labels)
            le = attributes.pop("le", None)
            if bucket_name == base + "_bucket" and tuple(sorted(attributes.items())) == labels:
                if le is None or value is None:
                    valid = False
                else:
                    buckets.append((float(le), value))
        valid = valid and bool(buckets) and any(math.isinf(bound) and value == count for bound, value in buckets)
        histograms.append(
            {
                "metric": base,
                "labels": dict(labels),
                "unit": "seconds",
                "count": count,
                "mean": total / count if valid and count else None,
                "p95_bucket_estimate": quantile(buckets, count, 0.95) if valid else None,
                "p99_bucket_estimate": quantile(buckets, count, 0.99) if valid else None,
                "bucket_estimates_available": bool(valid),
            }
        )
    return {
        "histograms": histograms,
        "counters": [
            {"metric": name, "labels": dict(labels), "delta": value}
            for (name, labels), value in deltas.items()
            if name.endswith("_total")
        ],
        "connections_checked_out_max": max(
            (sample[(GAUGE, ())] for sample in samples if (GAUGE, ()) in sample), default=None
        ),
        "counter_resets": resets,
        "missing_series": missing,
        "backend_process_restarted": restarted,
        "unavailable_metric_families": [
            base
            for base in (*HISTOGRAMS, GAUGE, "videre_ai_cache_reads_total")
            if (
                not all(any(name == base + suffix for name, _ in keys) for suffix in ("_count", "_sum", "_bucket"))
                if base in HISTOGRAMS
                else not any(name == base for name, _ in keys)
            )
        ],
        "histogram_note": "Interval bucket interpolation estimates in seconds; k6 route latency is in milliseconds.",
    }


def memory_bytes(value):
    match = re.fullmatch(r"\s*([0-9.]+)\s*([KMGT]?i?B)\s*", value)
    if not match:
        raise ValueError(f"Invalid Docker memory value: {value}")
    units = {
        "B": 1,
        **{prefix + "B": 1000**i for i, prefix in enumerate("KMGT", 1)},
        **{prefix + "iB": 1024**i for i, prefix in enumerate("KMGT", 1)},
    }
    return float(match[1]) * units[match[2]]


def parse_docker_stats(text):
    result = {}
    for line in text.splitlines():
        item = json.loads(line)
        used, limit = item["MemUsage"].split("/")
        result[item["Name"]] = {
            "cpu_cores": float(item["CPUPerc"].rstrip("%")) / 100,
            "memory_bytes": memory_bytes(used),
            "memory_limit_bytes": memory_bytes(limit),
            "raw": item,
        }
    return result


def parse_process_stat(text, ticks, page_size):
    fields = text[text.rindex(")") + 2 :].split()
    return {
        "cpu_seconds": (int(fields[11]) + int(fields[12])) / ticks,
        "start_ticks": int(fields[19]),
        "rss_bytes": int(fields[21]) * page_size,
    }


def process_sample(process):
    if process is None or process.poll() is not None:
        return None
    try:
        directory = Path(f"/proc/{process.pid}")
        result = parse_process_stat(
            directory.joinpath("stat").read_text(), os.sysconf("SC_CLK_TCK"), os.sysconf("SC_PAGE_SIZE")
        )
        result["pid"] = process.pid
        result["status"] = directory.joinpath("status").read_text()
        result["cgroup"] = directory.joinpath("cgroup").read_text()
        return result
    except FileNotFoundError:
        if process.poll() is not None:
            return None
        raise


def command(args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=15).stdout


def inspect_containers(containers):
    inspected = json.loads(command(["docker", "inspect", *containers]))
    result = {}
    for item in inspected:
        name = item["Name"].lstrip("/")
        config, state = item["HostConfig"], item["State"]
        if name not in containers or not state["Running"]:
            raise ValueError(f"Selected container is not running: {name}")
        result[name] = {
            "id": item["Id"],
            "image_id": item["Image"],
            "image": item["Config"]["Image"],
            "started_at": state["StartedAt"],
            "restart_count": item["RestartCount"],
            "oom_killed": state["OOMKilled"],
            "resources": {
                key: config.get(key)
                for key in ("Memory", "MemorySwap", "NanoCpus", "CpuQuota", "CpuPeriod", "CpusetCpus", "CpuShares")
            },
            "image_revision": (item["Config"].get("Labels") or {}).get("org.opencontainers.image.revision"),
            "mounts": [
                {key: mount.get(key) for key in ("Type", "Source", "Destination", "RW")}
                for mount in item.get("Mounts", [])
            ],
        }
    if set(result) != set(containers):
        raise ValueError("Docker inspection did not return all selected containers")
    return result


def cgroup_sample(containers):
    return {
        name: {
            "cpu": parse_key_values(command(["docker", "exec", name, "cat", "/sys/fs/cgroup/cpu.stat"])),
            "memory": parse_key_values(command(["docker", "exec", name, "cat", "/sys/fs/cgroup/memory.events"])),
        }
        for name in containers
    }


def parse_key_values(text):
    return {key: int(value) for key, value in (line.split() for line in text.splitlines())}


def cgroup_flags(samples):
    flags = set()
    for previous, current in zip(samples, samples[1:], strict=False):
        for name in previous:
            for family in ("cpu", "memory"):
                for key, value in previous[name][family].items():
                    after = current[name][family].get(key)
                    if after is None or after < value:
                        flags.add(f"{name} cgroup {family}.{key} reset or disappeared")
                    elif after > value and (key in ("oom", "oom_kill", "max", "high")):
                        flags.add(f"{name} cgroup {family}.{key} increased (resource safeguard)")
    return sorted(flags)


def cgroup_deltas(before, after):
    return {
        name: {
            family: {
                key: after[name][family][key] - value
                if key in after[name][family] and after[name][family][key] >= value
                else None
                for key, value in counters.items()
            }
            for family, counters in families.items()
        }
        for name, families in before.items()
    }


def backend_metrics(url):
    with urllib.request.urlopen(url.rstrip("/") + "/metrics", timeout=10) as response:
        data = response.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024:
        raise ValueError("Metrics exposition exceeds 4 MiB")
    text = data.decode()
    return text, parse_metrics(text)


def host_sample():
    stat = Path("/proc/stat").read_text()
    fields = [int(value) for value in stat.splitlines()[0].split()[1:]]
    return {
        "cpu_total_ticks": sum(fields[:8]),
        "cpu_idle_ticks": fields[3] + fields[4],
        "proc_stat": stat,
        "loadavg": Path("/proc/loadavg").read_text().strip(),
    }


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def git_metadata():
    files = ["scripts/k6-requests.js", "scripts/record-load.py"]
    source_files = sorted(ROOT.joinpath("src").rglob("*.py"))
    source_hash = hashlib.sha256()
    for path in source_files:
        source_hash.update(str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes() + b"\0")
    fixture = ROOT / "tests/load_environment.py"
    return {
        "backend_source_sha256": source_hash.hexdigest(),
        "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest() if fixture.exists() else None,
        "head": command(["git", "-C", str(ROOT), "rev-parse", "HEAD"]).strip(),
        "status": command(["git", "-C", str(ROOT), "status", "--porcelain"]),
        "file_sha256": {file: hashlib.sha256(ROOT.joinpath(file).read_bytes()).hexdigest() for file in files},
    }


def arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("api-base-url", "environment", "containers", "output"):
        parser.add_argument("--" + option, required=True)
    parser.add_argument("--rps", type=int, required=True)
    parser.add_argument("--duration-seconds", type=int, default=300)
    parser.add_argument("--k6-binary", default="tasks/load-tests/k6")
    parser.add_argument("--backend-revision", help="Override source digest for an explicitly identified backend")
    parser.add_argument("--node-id")
    parser.add_argument("--ai-entity-type", choices=("node", "gpu", "job"))
    parser.add_argument("--ai-entity-id")
    parser.add_argument("--max-vus", type=int, default=100)
    parser.add_argument("--p95-ms", type=float)
    parser.add_argument("--p99-ms", type=float)
    parser.add_argument("--idle", action="store_true", help="Record an idle reference without launching k6")
    args = parser.parse_args(argv)
    args.output = Path(args.output).resolve()
    args.containers = args.containers.split(",")
    if not args.output.is_dir() or any(
        args.output.joinpath(file).exists()
        for file in (
            "environment.json",
            "report.json",
            "samples.jsonl",
            "k6-summary.json",
            "k6-stdout.log",
            "backend-before.prom",
            "backend-after.prom",
        )
    ):
        parser.error("--output must be an existing directory without recorder artifacts")
    if not 1 <= args.rps <= 500 or not 10 <= args.duration_seconds <= 600 or not 1 <= args.max_vus <= 500:
        parser.error("RPS must be 1..500, duration 10..600 seconds, and max VUs 1..500")
    if (
        len(args.containers) != 3
        or len(set(args.containers)) != 3
        or any(not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", name) for name in args.containers)
    ):
        parser.error("--containers must name exactly three distinct Docker containers (backend,postgres,redis)")
    if not re.fullmatch(r"https?://[^/?#\s]+(?:/[^?#\s]*)?", args.api_base_url):
        parser.error("--api-base-url must be an explicit HTTP(S) URL without query or fragment")
    if not args.environment.strip() or (
        not args.idle and not all((args.node_id, args.ai_entity_type, args.ai_entity_id))
    ):
        parser.error("Environment and workload node/AI entity identifiers are required")
    if any(value is not None and (not math.isfinite(value) or value <= 0) for value in (args.p95_ms, args.p99_ms)):
        parser.error("Latency thresholds must be finite positive milliseconds")
    return args


def main(argv=None):
    args = arguments(argv)
    process, errors, flags, samples, metric_samples = None, [], [], [], []
    environment = {
        "started_at": datetime.now(UTC).isoformat(),
        "idle": args.idle,
        "config": {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
        "generator_shares_host": True,
        "host_cpu_count": os.cpu_count(),
        "generator_available_cpu_cores": len(os.sched_getaffinity(0)),
        "sampling_interval_seconds": 5,
        "resource_note": "Native k6 CPU sums all threads; shares the Docker/WSL host. Samples can miss brief peaks.",
    }
    report = {"status": "collection_failed", "errors": errors, "inconclusive_reasons": flags}
    k6_status = None
    try:
        environment["containers_before"] = inspect_containers(args.containers)
        environment["cgroups_before"] = cgroup_sample(args.containers)
        environment["git"] = git_metadata()
        environment["workload_revision"] = os.environ.get("WORKLOAD_REVISION", environment["git"]["head"])
        environment["backend_revision"] = (
            args.backend_revision
            or os.environ.get("BACKEND_REVISION")
            or "source-sha256:" + environment["git"]["backend_source_sha256"]
        )
        write_json(args.output / "environment.json", environment)
        raw, metrics = backend_metrics(args.api_base_url)
        args.output.joinpath("backend-before.prom").write_text(raw)
        metric_samples.append(metrics)
        with (
            args.output.joinpath("samples.jsonl").open("w") as stream,
            args.output.joinpath("k6-stdout.log").open("w") as log,
        ):
            if not args.idle:
                env = {
                    "PATH": os.environ.get("PATH", ""),
                    "HOME": os.environ.get("HOME", "/tmp"),
                    "RPS": str(args.rps),
                    "DURATION_SECONDS": str(args.duration_seconds),
                    "API_BASE_URL": args.api_base_url,
                    "ENVIRONMENT": args.environment,
                    "NODE_ID": args.node_id,
                    "AI_ENTITY_TYPE": args.ai_entity_type,
                    "AI_ENTITY_ID": args.ai_entity_id,
                    "SUMMARY_PATH": str(args.output / "k6-summary.json"),
                    "MAX_VUS": str(args.max_vus),
                    "WORKLOAD_REVISION": environment["workload_revision"],
                    "BACKEND_REVISION": environment["backend_revision"],
                    "K6_NO_USAGE_REPORT": "true",
                }
                for key in ("p95_ms", "p99_ms"):
                    if getattr(args, key) is not None:
                        env[key.upper()] = str(getattr(args, key))
                process = subprocess.Popen(
                    [str(Path(args.k6_binary).resolve()), "run", "--quiet", str(ROOT / "scripts/k6-requests.js")],
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            started, next_sample = time.monotonic(), time.monotonic()
            while True:
                now = time.monotonic()
                if (process is not None and process.poll() is not None) or (
                    args.idle and now - started >= args.duration_seconds
                ):
                    break
                if now < next_sample:
                    time.sleep(min(0.2, next_sample - now))
                    continue
                generator = process_sample(process)
                host = host_sample()
                raw, metrics = backend_metrics(args.api_base_url)
                metric_samples.append(metrics)
                resources = parse_docker_stats(
                    command(["docker", "stats", "--no-stream", "--format", "{{json .}}", *args.containers])
                )
                if set(resources) != set(args.containers):
                    raise ValueError("Docker stats omitted a selected container")
                sample = {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "elapsed_seconds": now - started,
                    "host": host,
                    "generator": generator,
                    "containers": resources,
                    "cgroups": cgroup_sample(args.containers),
                    "backend_exposition": raw,
                }
                samples.append(sample)
                stream.write(json.dumps(sample, allow_nan=False) + "\n")
                stream.flush()
                for name, resource in resources.items():
                    if (
                        resource["memory_limit_bytes"]
                        and resource["memory_bytes"] >= 0.9 * resource["memory_limit_bytes"]
                    ):
                        flags.append(f"{name} memory reached 90% of container limit (resource safeguard)")
                if flags:
                    break
                if time.monotonic() - started > args.duration_seconds + 30:
                    raise RuntimeError("k6 did not exit within duration plus 30 seconds")
                next_sample += 5
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                k6_status = process.wait(timeout=15)
            raw, metrics = backend_metrics(args.api_base_url)
            args.output.joinpath("backend-after.prom").write_text(raw)
            metric_samples.append(metrics)
        environment["containers_after"] = inspect_containers(args.containers)
        terminal_cgroups = cgroup_sample(args.containers)
        flags.extend(
            cgroup_flags(
                [environment["cgroups_before"]] + [sample["cgroups"] for sample in samples] + [terminal_cgroups]
            )
        )
        environment["cgroups_after"] = terminal_cgroups
        report["cgroup_deltas"] = cgroup_deltas(environment["cgroups_before"], terminal_cgroups)
        for name, before in environment["containers_before"].items():
            after = environment["containers_after"][name]
            if any(before[key] != after[key] for key in ("id", "started_at", "restart_count", "image_id", "resources")):
                flags.append(f"{name} container identity/restart/resources changed")
            if after["oom_killed"]:
                flags.append(f"{name} Docker OOMKilled")
        report["backend"] = summarize_metrics(metric_samples)
        if not args.idle and report["backend"]["unavailable_metric_families"]:
            flags.append(
                "Required backend metric families unavailable: "
                + ", ".join(report["backend"]["unavailable_metric_families"])
            )
        if (
            report["backend"]["counter_resets"]
            or report["backend"]["missing_series"]
            or report["backend"]["backend_process_restarted"]
        ):
            flags.append("Backend counters reset, disappeared, or process restarted")
        for previous, current in zip(samples, samples[1:], strict=False):
            total = current["host"]["cpu_total_ticks"] - previous["host"]["cpu_total_ticks"]
            idle = current["host"]["cpu_idle_ticks"] - previous["host"]["cpu_idle_ticks"]
            current["host"]["cpu_busy_fraction"] = (total - idle) / total if total > 0 else None
            a, b = previous["generator"], current["generator"]
            if a and b:
                elapsed = current["elapsed_seconds"] - previous["elapsed_seconds"]
                current["generator"]["cpu_cores"] = (b["cpu_seconds"] - a["cpu_seconds"]) / elapsed
                if b["start_ticks"] != a["start_ticks"] or b["cpu_seconds"] < a["cpu_seconds"]:
                    flags.append("Native generator process identity/counter changed")
                if current["generator"]["cpu_cores"] >= 0.9 * environment["generator_available_cpu_cores"]:
                    flags.append("Native generator CPU approached available host cores")
            if current["host"]["cpu_busy_fraction"] is not None and current["host"]["cpu_busy_fraction"] >= 0.95:
                flags.append("Shared host CPU reached 95% busy; generator/service contention possible")
        report["resource_samples"] = samples
        report["k6_exit_code"] = k6_status
        if not args.idle:
            report["k6"] = json.loads(args.output.joinpath("k6-summary.json").read_text())
            if report["k6"]["load_generator_limited"]:
                flags.append("k6 dropped iterations; available VUs/generator could not sustain offered rate")
        report["status"] = (
            "inconclusive"
            if flags
            else "idle_reference"
            if args.idle
            else ("passed" if k6_status == 0 and report["k6"]["passed"] else "failed")
        )
    except (Exception, KeyboardInterrupt) as error:
        errors.append(
            f"{type(error).__name__}: {error}"
            + (
                f"; stderr: {error.stderr.strip()}"
                if isinstance(error, subprocess.CalledProcessError) and error.stderr
                else ""
            )
        )
        report["status"] = "collection_failed"
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        report["inconclusive_reasons"] = sorted(set(flags))
        environment["finished_at"] = datetime.now(UTC).isoformat()
        write_json(args.output / "environment.json", environment)
        write_json(args.output / "report.json", report)
    print(json.dumps({"status": report["status"], "errors": errors, "inconclusive_reasons": sorted(set(flags))}))
    return k6_status if k6_status else 2 if report["status"] in ("inconclusive", "collection_failed", "failed") else 0


if __name__ == "__main__":
    sys.exit(main())
