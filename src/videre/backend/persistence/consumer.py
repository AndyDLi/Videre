"""
Kafka to Postgres persistence loop, run as a background task.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiokafka import AIOKafkaConsumer
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from videre.events import TOPIC_MESSAGE_TYPES, Topic

from ..metrics import record_event
from ..settings import Settings
from .event_mapping import apply_event

logger = logging.getLogger("videre.backend.consumer")

CONSUMER_GROUP = "videre-backend"
RECONNECT_DELAY_SECONDS = 5.0


async def run_consumer(session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    while True:
        consumer = AIOKafkaConsumer(
            *[topic.value for topic in Topic],    # subscribe to all topics
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=CONSUMER_GROUP,
            enable_auto_commit=False,        # commit only once the rows are written
            auto_offset_reset="latest",      # start at the tip if there is no bookmark
        )
        try:
            await consumer.start()
            logger.info("consumer connected", extra={"group": CONSUMER_GROUP})
            async for record in consumer:
                await handle_record(session_factory, consumer, record)
        except asyncio.CancelledError:
            logger.info("consumer stopped", extra={"group": CONSUMER_GROUP})
            raise
        except Exception as error:
            logger.warning(
                "consumer failed, reconnecting",
                extra={"error": str(error), "delay_seconds": RECONNECT_DELAY_SECONDS},
            )
        finally:
            await consumer.stop()
        await asyncio.sleep(RECONNECT_DELAY_SECONDS)    # back off once the socket is released


async def handle_record(session_factory: async_sessionmaker[AsyncSession], consumer: Any, record: Any) -> None:
    try:
        topic = Topic(record.topic)
        message = TOPIC_MESSAGE_TYPES[topic].model_validate_json(record.value)
    except (ValueError, ValidationError) as error:
        logger.warning(
            "skipping malformed message",
            extra={"topic": record.topic, "offset": record.offset, "error": str(error)},
        )
        await consumer.commit()
        return
    
    try:
        async with session_factory() as session, session.begin():
            await apply_event(session, topic, message)    # write to Postgres
    except Exception as error:
        logger.error(
            "persistence failed",
            extra={"topic": record.topic, "event_type": message.event_type, "error": str(error)},
        )
        return
    
    record_event(topic, message)    # write to Prometheus registry
    await consumer.commit()
