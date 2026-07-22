"""
Confluent Kafka publisher: serializes each EventMessage to JSON
and produces it to its topic with the partition key.
"""

from __future__ import annotations

import logging
import time

from confluent_kafka import KafkaError, Message, Producer

from .generators import GeneratedEvent

logger = logging.getLogger("videre.simulator.publisher")


class KafkaEventPublisher:
    def __init__(self, *, bootstrap_servers: str) -> None:
        self._producer = Producer(
            {
                "bootstrap.servers": bootstrap_servers,    # comma-separated list of Kafka brokers to connect to
                "acks": "all",    # wait for the leader and all replicas to acknowledge the message
                "enable.idempotence": True,    # prevent duplicate events from this producer session
                "retries": 5,
                "linger.ms": 50,
                "compression.type": "lz4",
                "message.timeout.ms": 30000,
            }
        )
    
    def publish(self, event: GeneratedEvent) -> None:
        value = event.message.model_dump_json().encode()
        deadline = time.monotonic() + 5.0
        
        while True:
            try:
                self._producer.produce(
                    event.topic.value,
                    key=event.key.encode(),
                    value=value,
                    on_delivery=self._on_delivery,
                )
                break
            except BufferError as buffer_error:   # local producer queue is full; drain it and retry
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        "Kafka producer queue stayed full for 5 seconds; event was not queued: "
                        f"topic={event.topic.value} key={event.key} "
                        f"event_type={getattr(event.message, 'event_type', '')}"
                    ) from buffer_error
                self._producer.poll(min(1.0, remaining))    # allow the producer to complete sends and runs delivery
        
        self._producer.poll(0)
        logger.info(
            "published",
            extra={
                "topic": event.topic.value,
                "key": event.key,
                "event_type": getattr(event.message, "event_type", "")
            },
        )
    
    def _on_delivery(self, error: KafkaError | None, message: Message) -> None:
        if error is not None:
            logger.error("delivery failed", extra={"topic": message.topic(), "error": str(error)})
    
    def flush(self, timeout: float = 10.0) -> None:
        self._producer.flush(timeout)
