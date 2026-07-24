import os
import signal
import threading

from videre.logging_config import configure_logging

from .materializer import KubernetesJobMaterializer
from .publisher import KafkaEventPublisher
from .simulation import Simulator


def main() -> None:
    configure_logging()
    environ = os.environ
    
    publisher = KafkaEventPublisher(
        bootstrap_servers=environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka.videre.svc.cluster.local:9092")
    )
    materializer = KubernetesJobMaterializer(
        ttl_seconds_after_finished=int(environ.get("MATERIALIZED_JOB_TTL_SECONDS", "120"))
    )
    simulator = Simulator(
        node_count=int(environ.get("NODE_COUNT", "4")),
        gpus_per_node=int(environ.get("GPUS_PER_NODE", "8")),
        telemetry_interval_seconds=float(environ.get("TELEMETRY_INTERVAL_SECONDS", "10")),
        baseline_failure_probability=float(environ.get("BASELINE_FAILURE_PROBABILITY", "0.05")),
        job_arrival_probability=float(environ.get("JOB_ARRIVAL_PROBABILITY", "0.2")),
        job_completion_probability=float(environ.get("JOB_COMPLETION_PROBABILITY", "0.05")),
        node_recovery_probability=float(environ.get("NODE_RECOVERY_PROBABILITY", "0.005")),
        gpu_recovery_probability=float(environ.get("GPU_RECOVERY_PROBABILITY", "0.01")),
        materializer=materializer,
    )
    
    stop_event = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    simulator.run(
        publisher,
        stop_event=stop_event,
        tick_interval_seconds=float(environ.get("TICK_INTERVAL_SECONDS", "1"))
    )


if __name__ == "__main__":
    main()
