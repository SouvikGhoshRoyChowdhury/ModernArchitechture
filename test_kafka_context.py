"""Tests for the Pattern 2 ``KafkaContext`` refactor.

These exercise only the pure contract/logic that does not require the
``confluent_kafka`` dependency (imported lazily inside methods), so they run in
any environment.
"""

import unittest
import warnings

from kafka_context import AvroMapping, KafkaContext, SubjectNameStrategy


class KafkaContextContractTests(unittest.TestCase):
    def test_avro_schema_id_not_required(self):
        # Pattern 2: a context can be built without any static schema id.
        ctx = KafkaContext(topic="P00176.totem_faas_report_results", cluster_name="hulk")
        self.assertIsNone(ctx.avro_schema_id)

    def test_default_subject_name_strategy_is_record_name(self):
        ctx = KafkaContext(topic="t", cluster_name="hulk")
        self.assertEqual(ctx.subject_name_strategy, SubjectNameStrategy.RECORD_NAME)

    def test_reader_schema_optional_defaults_none(self):
        ctx = KafkaContext(topic="t", cluster_name="hulk")
        self.assertIsNone(ctx.reader_schema)

    def test_encrypt_requires_avro(self):
        with self.assertRaises(ValueError):
            KafkaContext(topic="t", cluster_name="hulk", encrypt_payload=True, use_avro=False)

    def test_invalid_client_type(self):
        with self.assertRaises(ValueError):
            KafkaContext(topic="t", cluster_name="hulk", client_type="bogus")

    def test_avro_schema_id_override_emits_deprecation_warning(self):
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            # Uses logging.warning, so assert via logger capture instead.
            with self.assertLogs("kafka_context", level="WARNING") as cm:
                KafkaContext(
                    topic="t",
                    cluster_name="hulk",
                    avro_schema_id=AvroMapping(dev=1, tst=2, acc=3, prd=4),
                )
        self.assertTrue(any("deprecated" in m.lower() for m in cm.output))

    def test_producer_send_requires_per_message_schema(self):
        ctx = KafkaContext(topic="t", cluster_name="hulk", client_type="producer")
        # Validation happens before any confluent import or client use.
        with self.assertRaises(ValueError):
            ctx.send({"foo": "bar"})

    def test_send_rejected_for_consumer(self):
        ctx = KafkaContext(topic="t", cluster_name="hulk", client_type="consumer")
        with self.assertRaises(RuntimeError):
            ctx.send({"foo": "bar"}, schema_str="{}")

    def test_consume_rejected_for_producer(self):
        ctx = KafkaContext(topic="t", cluster_name="hulk", client_type="producer")
        with self.assertRaises(RuntimeError):
            ctx.consume()

    def test_additional_settings_merged_into_base_conf(self):
        ctx = KafkaContext(
            topic="t",
            cluster_name="hulk",
            additional_settings={"max.poll.interval.ms": 600000},
        )
        conf = ctx._base_conf()
        self.assertEqual(conf["max.poll.interval.ms"], 600000)
        self.assertIn("bootstrap.servers", conf)

    def test_unknown_cluster_name_used_as_bootstrap(self):
        ctx = KafkaContext(topic="t", cluster_name="my-host:9093")
        self.assertEqual(ctx._base_conf()["bootstrap.servers"], "my-host:9093")


if __name__ == "__main__":
    unittest.main()
