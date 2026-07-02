"""Reference implementation of the MAPPS ``KafkaContext`` refactored to
support **Pattern 2** — many Avro record types coexisting on a single Kafka
topic via ``RecordNameStrategy`` / ``TopicRecordNameStrategy``.

Background
----------
The original platform interface pinned each context to a single static schema
per environment (``avro_schema_id: AvroMapping``). That is a Pattern 1
(``TopicNameStrategy``) model: one subject ``<topic>-value`` = one evolving
schema per topic.

The concrete implementation already proved the hard part of Pattern 2: in the
original ``deserialize_avro_data`` helper the writer schema is resolved *at
runtime* from the 4-byte schema id embedded in every Confluent wire payload
(magic byte + id). The only gap was the ``KafkaContext`` *contract*, which
still forced a single schema. This module closes that gap.

What changed (maps 1:1 to the platform plan)
---------------------------------------------
1. The static ``avro_schema_id`` binding is removed from the contract. It is
   kept only as an optional, deprecated override for backwards compatibility.
   Consumers no longer pass any fixed schema id; producers choose the schema
   per message (see :meth:`KafkaContext.send`).
2. Both serializer and deserializer are configured with a configurable
   subject-name strategy, defaulting to :attr:`SubjectNameStrategy.RECORD_NAME`
   so multiple record types can share one topic.
3. The producer accepts the schema per publish rather than at construction.
4. Subjects are resolved by record name (identical across environments)
   instead of brittle per-environment integer ids.
5. :class:`SerializationContext` is built from the context's own ``topic``
   rather than a hardcoded literal.
6. The consumer reader schema is optional; by default the writer schema is
   resolved from the wire id, which also enables schema evolution.
7. ``encrypt_payload``, ``cluster_name``, ``client_type``, ``auto_commit`` and
   ``additional_settings`` keep their original semantics.

Adding a new report type therefore becomes: register one new subject in the
Schema Registry. No interface change, no id table to maintain, and unrelated
consumers are untouched.

Note: ``confluent_kafka`` is imported lazily inside methods (as in the original
implementation) so this module can be imported without the dependency present.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Toggle to target a local docker Schema Registry instead of the shared one.
USE_LOCAL_KAFKA = False

# Bootstrap servers per named cluster. Values are placeholders for the real
# platform endpoints; ``additional_settings`` can override any of these.
CLUSTER_BOOTSTRAP_SERVERS: Dict[str, str] = {
    "hulk": "hulk-kafka.ing.net:9093",
    "odin": "odin-kafka.ing.net:9093",
    "stark": "stark-kafka.ing.net:9093",
}


class SubjectNameStrategy(str, Enum):
    """Confluent subject-name strategies.

    ``RECORD_NAME`` and ``TOPIC_RECORD_NAME`` enable Pattern 2 (multiple record
    types per topic); ``TOPIC_NAME`` is the legacy Pattern 1 default.
    """

    RECORD_NAME = "record_name"
    TOPIC_RECORD_NAME = "topic_record_name"
    TOPIC_NAME = "topic_name"


@dataclass
class AvroMapping:
    """Per-environment Avro schema ids.

    Deprecated under Pattern 2 and retained only as an optional override. Prefer
    subject resolution by record name, which is identical across environments.
    """

    dev: int
    tst: int
    acc: int
    prd: int


def _get_schema_registry_client():
    import os

    from confluent_kafka.schema_registry import SchemaRegistryClient

    if not USE_LOCAL_KAFKA:
        schema_registry_conf = {
            "url": "https://sr1-global-tst.ing.net:8443",
            "ssl.ca.location": os.getenv("REQUESTS_CA_BUNDLE", "/etc/ssl/certs/ca-bundle.crt"),
            "ssl.key.location": os.getenv("SSL_KEY_LOCATION", "/mapps/certs/kafka.key"),
            "ssl.certificate.location": os.getenv("SSL_CERTIFICATE_LOCATION", "/mapps/certs/kafka.pem"),
        }
    else:
        schema_registry_conf = {"url": "http://schema-registry:8082"}

    return SchemaRegistryClient(schema_registry_conf)


def _resolve_subject_name_strategy(strategy: "SubjectNameStrategy") -> Callable:
    """Map a :class:`SubjectNameStrategy` to the confluent callable."""

    from confluent_kafka.schema_registry import (
        record_subject_name_strategy,
        topic_record_subject_name_strategy,
        topic_subject_name_strategy,
    )

    mapping = {
        SubjectNameStrategy.RECORD_NAME: record_subject_name_strategy,
        SubjectNameStrategy.TOPIC_RECORD_NAME: topic_record_subject_name_strategy,
        SubjectNameStrategy.TOPIC_NAME: topic_subject_name_strategy,
    }
    return mapping[SubjectNameStrategy(strategy)]


class KafkaContext:
    """Context manager used to communicate with a Kafka topic.

    Pattern 2 aware: a single topic can carry many Avro record types. Consumers
    resolve the writer schema per message from the wire id; producers pick the
    schema per :meth:`send`.
    """

    def __init__(
        self,
        topic: str,
        cluster_name: str,
        client_type: str = "consumer",
        auto_commit: bool = True,
        additional_settings: Optional[dict] = None,
        encrypt_payload: bool = False,
        use_avro: bool = True,
        subject_name_strategy: SubjectNameStrategy = SubjectNameStrategy.RECORD_NAME,
        reader_schema: Optional[str] = None,
        payload_encryptor: Optional[Callable[[bytes], bytes]] = None,
        payload_decryptor: Optional[Callable[[bytes], bytes]] = None,
        avro_schema_id: Optional[AvroMapping] = None,
    ):
        """Create a Kafka context.

        Args:
            topic: Name of the topic.
            cluster_name: Kafka cluster name (``hulk``, ``odin`` or ``stark``).
            client_type: ``"consumer"`` or ``"producer"``. Defaults to
                ``"consumer"``.
            auto_commit: Enable auto commit for consumers. Defaults to ``True``.
            additional_settings: Custom Kafka settings using dotted keys (Kafka
                format), e.g. ``max.poll.interval.ms``.
            encrypt_payload: If ``True`` the payload is encrypted/decrypted via
                ``payload_encryptor`` / ``payload_decryptor``. Avro is required.
            use_avro: Use Avro (de)serialization. When ``False`` a string
                (de)serializer is used. Defaults to ``True``.
            subject_name_strategy: Subject-name strategy. Defaults to
                :attr:`SubjectNameStrategy.RECORD_NAME` (Pattern 2). Applies to
                both producer and consumer.
            reader_schema: Optional reader schema for the consumer. When ``None``
                (default) the writer schema is resolved from the wire id,
                allowing any record type and schema evolution.
            payload_encryptor: Callable used to encrypt the serialized payload
                when ``encrypt_payload`` is ``True``.
            payload_decryptor: Callable used to decrypt the payload when
                ``encrypt_payload`` is ``True``.
            avro_schema_id: Deprecated. Optional per-environment id override kept
                for backwards compatibility only; prefer subject resolution by
                record name.
        """
        if client_type not in ("consumer", "producer"):
            raise ValueError(f"client_type must be 'consumer' or 'producer', got {client_type!r}")

        if encrypt_payload and not use_avro:
            raise ValueError("encrypt_payload=True requires use_avro=True (Avro serializer).")

        if avro_schema_id is not None:
            logger.warning(
                "avro_schema_id/AvroMapping is deprecated under Pattern 2; schemas are resolved "
                "by record name (producer) and by wire id (consumer). Ignoring the static id "
                "except as an explicit legacy override."
            )

        self.topic = topic
        self.cluster_name = cluster_name
        self.client_type = client_type
        self.auto_commit = auto_commit
        self.additional_settings = dict(additional_settings or {})
        self.encrypt_payload = encrypt_payload
        self.use_avro = use_avro
        self.subject_name_strategy = SubjectNameStrategy(subject_name_strategy)
        self.reader_schema = reader_schema
        self.payload_encryptor = payload_encryptor
        self.payload_decryptor = payload_decryptor
        self.avro_schema_id = avro_schema_id

        self._schema_registry_client = None
        self._deserializer = None
        self._serializer_cache: Dict[str, Any] = {}
        self._string_serializer = None
        self._string_deserializer = None
        self._client = None  # Producer or Consumer

    # -- Schema registry / serializers ------------------------------------

    def _registry_client(self):
        if self._schema_registry_client is None:
            self._schema_registry_client = _get_schema_registry_client()
        return self._schema_registry_client

    def _get_avro_serializer(self, schema_str: str):
        """Return a cached ``AvroSerializer`` for ``schema_str``.

        Configured with the selected subject-name strategy so that the subject
        is derived from the record's fully-qualified name (Pattern 2).
        """
        if schema_str not in self._serializer_cache:
            from confluent_kafka.schema_registry.avro import AvroSerializer

            conf = {"subject.name.strategy": _resolve_subject_name_strategy(self.subject_name_strategy)}
            self._serializer_cache[schema_str] = AvroSerializer(
                schema_registry_client=self._registry_client(),
                schema_str=schema_str,
                conf=conf,
            )
        return self._serializer_cache[schema_str]

    def _get_avro_deserializer(self):
        """Return the consumer ``AvroDeserializer``.

        With ``reader_schema=None`` (default) the writer schema is resolved from
        the wire id per message, so any record type on the topic can be read.
        """
        if self._deserializer is None:
            from confluent_kafka.schema_registry.avro import AvroDeserializer

            self._deserializer = AvroDeserializer(
                schema_registry_client=self._registry_client(),
                schema_str=self.reader_schema,
            )
        return self._deserializer

    def _get_string_serializer(self):
        if self._string_serializer is None:
            from confluent_kafka.serialization import StringSerializer

            self._string_serializer = StringSerializer("utf_8")
        return self._string_serializer

    def _get_string_deserializer(self):
        if self._string_deserializer is None:
            from confluent_kafka.serialization import StringDeserializer

            self._string_deserializer = StringDeserializer("utf_8")
        return self._string_deserializer

    def _serialization_context(self, field=None):
        """Build a ``SerializationContext`` bound to this context's topic."""
        from confluent_kafka.serialization import MessageField, SerializationContext

        return SerializationContext(topic=self.topic, field=field or MessageField.VALUE)

    # -- Client configuration ---------------------------------------------

    def _base_conf(self) -> dict:
        bootstrap = CLUSTER_BOOTSTRAP_SERVERS.get(self.cluster_name, self.cluster_name)
        conf: dict = {"bootstrap.servers": bootstrap}
        # additional_settings already uses dotted Kafka keys; merge last so it
        # can override defaults.
        conf.update(self.additional_settings)
        return conf

    # -- Context manager --------------------------------------------------

    def __enter__(self) -> "KafkaContext":
        if self.client_type == "producer":
            from confluent_kafka import Producer

            self._client = Producer(self._base_conf())
        else:
            from confluent_kafka import Consumer

            conf = self._base_conf()
            conf.setdefault("group.id", f"{self.topic}-consumer")
            conf["enable.auto.commit"] = self.auto_commit
            self._client = Consumer(conf)
            self._client.subscribe([self.topic])
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self._client is None:
            return False
        try:
            if self.client_type == "producer":
                self._client.flush()
            else:
                self._client.close()
        finally:
            self._client = None
        return False

    # -- Producer ---------------------------------------------------------

    def send(
        self,
        value: Any,
        schema_str: Optional[str] = None,
        key: Optional[bytes] = None,
        headers: Optional[dict] = None,
        on_delivery: Optional[Callable] = None,
    ) -> None:
        """Publish a message, choosing the schema per message (Pattern 2).

        Args:
            value: The record to serialize (a ``dict`` for Avro).
            schema_str: Avro schema for *this* message. Required when
                ``use_avro`` is ``True``; the subject is derived from the
                record name via the configured subject-name strategy.
            key: Optional message key bytes.
            headers: Optional Kafka headers.
            on_delivery: Optional delivery callback.
        """
        if self.client_type != "producer":
            raise RuntimeError("send() is only available for a producer KafkaContext.")

        if self.use_avro and not schema_str:
            raise ValueError(
                "A per-message schema_str is required for Avro producers under Pattern 2. "
                "Pass the schema for the record type being published."
            )

        if self._client is None:
            raise RuntimeError("KafkaContext must be entered (use 'with') before send().")

        ctx = self._serialization_context()
        if self.use_avro:
            payload = self._get_avro_serializer(schema_str)(value, ctx)
        else:
            payload = self._get_string_serializer()(value, ctx)

        if self.encrypt_payload:
            payload = self._encrypt(payload)

        self._client.produce(
            topic=self.topic,
            value=payload,
            key=key,
            headers=headers,
            on_delivery=on_delivery,
        )
        self._client.poll(0)

    # -- Consumer ---------------------------------------------------------

    def consume(self, timeout: float = 1.0) -> Optional[Any]:
        """Poll one message and deserialize it.

        The writer schema is resolved per message from the wire id, so any
        record type present on the topic can be consumed (Pattern 2).
        Returns ``None`` when no message is available within ``timeout``.
        """
        if self.client_type != "consumer":
            raise RuntimeError("consume() is only available for a consumer KafkaContext.")
        if self._client is None:
            raise RuntimeError("KafkaContext must be entered (use 'with') before consume().")

        msg = self._client.poll(timeout)
        if msg is None:
            return None
        if msg.error():
            raise RuntimeError(f"Kafka consume error: {msg.error()}")

        raw = msg.value()
        if raw is None:
            return None
        if self.encrypt_payload:
            raw = self._decrypt(raw)

        ctx = self._serialization_context()
        if self.use_avro:
            return self._get_avro_deserializer()(raw, ctx)
        return self._get_string_deserializer()(raw, ctx)

    # -- Payload encryption hooks -----------------------------------------

    def _encrypt(self, payload: bytes) -> bytes:
        if self.payload_encryptor is None:
            raise NotImplementedError(
                "encrypt_payload=True but no payload_encryptor was provided."
            )
        return self.payload_encryptor(payload)

    def _decrypt(self, payload: bytes) -> bytes:
        if self.payload_decryptor is None:
            raise NotImplementedError(
                "encrypt_payload=True but no payload_decryptor was provided."
            )
        return self.payload_decryptor(payload)
