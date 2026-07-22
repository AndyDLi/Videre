import os
import signal
import threading

from .logging_config import configure_logging
from .publisher import KafkaEventPublisher
from .simulation import Simulator


def main() -> None:
    configure_logging()
    bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "kafka.videre.svc.cluster.local:9092")
    publisher = KafkaEventPublisher(bootstrap_servers=bootstrap_servers)
    simulator = Simulator()
    
    stop_event = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    simulator.run(publisher, stop_event=stop_event)


if __name__ == "__main__":
    main()
