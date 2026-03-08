"""Event-bus trigger adapters (Kafka/SQS-style).

This module intentionally keeps external dependencies optional:
- SQS uses boto3 when available
- Kafka uses aiokafka when available

When a dependency is unavailable or a source is malformed, adapters return no
messages and log a warning instead of crashing the trigger loops.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("langorch.event_bus")


@dataclass
class EventEnvelope:
    payload: dict[str, Any]
    message_id: str | None = None
    ack_token: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


class BaseEventAdapter:
    scheme: str = ""

    def can_handle(self, source: str) -> bool:
        return _source_scheme(source) == self.scheme

    async def poll(self, source: str, max_messages: int = 5) -> list[EventEnvelope]:
        raise NotImplementedError()

    async def ack(self, source: str, event: EventEnvelope) -> None:
        return None


class SqsEventAdapter(BaseEventAdapter):
    scheme = "sqs"

    async def poll(self, source: str, max_messages: int = 5) -> list[EventEnvelope]:
        try:
            import boto3  # type: ignore[import-not-found]
        except Exception:
            logger.warning("SQS adapter unavailable: boto3 is not installed")
            return []

        queue_url, region = _parse_sqs_source(source)
        if not queue_url:
            logger.warning("SQS adapter source is missing queue URL/name: %s", source)
            return []

        client = boto3.client("sqs", region_name=region)

        def _recv() -> dict[str, Any]:
            return client.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=max(1, min(int(max_messages), 10)),
                WaitTimeSeconds=1,
                MessageAttributeNames=["All"],
                AttributeNames=["All"],
            )

        response = await asyncio.to_thread(_recv)
        messages = response.get("Messages") or []

        envelopes: list[EventEnvelope] = []
        for message in messages:
            body = message.get("Body")
            payload: dict[str, Any]
            if isinstance(body, str):
                try:
                    parsed = json.loads(body)
                    payload = parsed if isinstance(parsed, dict) else {"value": parsed}
                except Exception:
                    payload = {"raw_body": body}
            else:
                payload = {"raw_body": body}

            envelopes.append(
                EventEnvelope(
                    payload=payload,
                    message_id=message.get("MessageId"),
                    ack_token=message.get("ReceiptHandle"),
                    attributes={"queue_url": queue_url},
                )
            )

        return envelopes

    async def ack(self, source: str, event: EventEnvelope) -> None:
        if not event.ack_token:
            return
        try:
            import boto3  # type: ignore[import-not-found]
        except Exception:
            return

        queue_url, region = _parse_sqs_source(source)
        queue_url = event.attributes.get("queue_url") or queue_url
        if not queue_url:
            return

        client = boto3.client("sqs", region_name=region)

        def _delete() -> None:
            client.delete_message(QueueUrl=queue_url, ReceiptHandle=event.ack_token)

        await asyncio.to_thread(_delete)


class KafkaEventAdapter(BaseEventAdapter):
    scheme = "kafka"

    async def poll(self, source: str, max_messages: int = 5) -> list[EventEnvelope]:
        try:
            from aiokafka import AIOKafkaConsumer  # type: ignore[import-not-found]
        except Exception:
            logger.warning("Kafka adapter unavailable: aiokafka is not installed")
            return []

        topic, bootstrap_servers, group_id = _parse_kafka_source(source)
        if not topic:
            logger.warning("Kafka adapter source is missing topic: %s", source)
            return []

        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            enable_auto_commit=True,
            auto_offset_reset="latest",
        )

        envelopes: list[EventEnvelope] = []
        await consumer.start()
        try:
            records_map = await consumer.getmany(timeout_ms=250, max_records=max_messages)
            for records in records_map.values():
                for record in records:
                    payload: dict[str, Any]
                    raw = record.value
                    if isinstance(raw, (bytes, bytearray)):
                        try:
                            decoded = raw.decode("utf-8")
                            parsed = json.loads(decoded)
                            payload = parsed if isinstance(parsed, dict) else {"value": parsed}
                        except Exception:
                            payload = {"raw_body": raw.decode("utf-8", errors="replace")}
                    else:
                        payload = {"raw_body": raw}

                    envelopes.append(
                        EventEnvelope(
                            payload=payload,
                            message_id=f"{record.topic}:{record.partition}:{record.offset}",
                            attributes={
                                "topic": record.topic,
                                "partition": record.partition,
                                "offset": record.offset,
                            },
                        )
                    )
        finally:
            await consumer.stop()

        return envelopes


_ADAPTERS: tuple[BaseEventAdapter, ...] = (
    SqsEventAdapter(),
    KafkaEventAdapter(),
)


def resolve_event_adapter(source: str | None) -> BaseEventAdapter | None:
    if not source:
        return None
    for adapter in _ADAPTERS:
        if adapter.can_handle(source):
            return adapter
    return None


async def poll_events(source: str | None, max_messages: int = 5) -> list[EventEnvelope]:
    adapter = resolve_event_adapter(source)
    if not adapter:
        return []
    return await adapter.poll(source or "", max_messages=max_messages)


async def ack_event(source: str | None, event: EventEnvelope) -> None:
    adapter = resolve_event_adapter(source)
    if not adapter:
        return
    await adapter.ack(source or "", event)


def _source_scheme(source: str) -> str:
    src = source.strip().lower()
    if "://" not in src:
        return "kafka"
    return src.split("://", 1)[0]


def _parse_sqs_source(source: str) -> tuple[str | None, str | None]:
    """Parse sqs source forms:

    - sqs://<queue_name>
    - sqs://<queue_name>?region=us-east-1
    - sqs://?queue_url=https://sqs.us-east-1.amazonaws.com/1234/my-queue&region=us-east-1
    """
    parsed = urlparse(source)
    query = parse_qs(parsed.query)

    queue_url = (query.get("queue_url") or [None])[0]
    queue_name = (parsed.netloc + parsed.path).strip("/")
    region = (query.get("region") or [None])[0]

    if queue_url:
        return queue_url, region

    if not queue_name:
        return None, region

    # Support explicit queue URL passed as path-like text
    if queue_name.startswith("http://") or queue_name.startswith("https://"):
        return queue_name, region

    # Resolve queue name lazily at poll-time with boto3 get_queue_url
    # by converting to canonical queue_url query form.
    try:
        import boto3  # type: ignore[import-not-found]
        client = boto3.client("sqs", region_name=region)
        queue_url = client.get_queue_url(QueueName=queue_name)["QueueUrl"]
        return queue_url, region
    except Exception:
        logger.warning("SQS adapter could not resolve queue URL for '%s'", queue_name)
        return None, region


def _parse_kafka_source(source: str) -> tuple[str | None, str, str]:
    """Parse kafka source forms:

    - kafka://orders.created
    - kafka://orders.created?bootstrap_servers=localhost:9092&group_id=langorch
    - orders.created (treated as kafka topic shorthand)
    """
    if "://" not in source:
        source = f"kafka://{source}"
    parsed = urlparse(source)
    query = parse_qs(parsed.query)

    topic = (parsed.netloc + parsed.path).strip("/")
    bootstrap = (query.get("bootstrap_servers") or [""])[0] or "localhost:9092"
    group_id = (query.get("group_id") or [""])[0] or "langorch-trigger"
    return (topic or None), bootstrap, group_id
