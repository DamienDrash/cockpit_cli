import json
import unittest

from cockpit.infrastructure.persistence.snapshot_codec import (
    decode_snapshot,
    encode_snapshot,
)
from cockpit.shared.enums import SnapshotKind


class SnapshotCodecTests(unittest.TestCase):
    def test_round_trip_snapshot_payload(self) -> None:
        raw_payload = encode_snapshot(
            SnapshotKind.RESUME,
            {"cwd": "/tmp/project", "focus_path": ["work", "work-panel"]},
        )

        result = decode_snapshot(raw_payload)

        self.assertTrue(result.success)
        self.assertIsNotNone(result.envelope)
        assert result.envelope is not None
        self.assertEqual(result.envelope.snapshot_kind, SnapshotKind.RESUME)
        self.assertEqual(result.envelope.payload["cwd"], "/tmp/project")

    def test_incompatible_schema_version_is_recoverable(self) -> None:
        raw_payload = json.dumps(
            {
                "schema_version": 999,
                "snapshot_kind": "resume",
                "created_at": "2026-03-22T00:00:00+00:00",
                "payload": {"cwd": "/tmp/project"},
            }
        )

        result = decode_snapshot(raw_payload)

        self.assertFalse(result.success)
        self.assertIn("schema version", result.error or "")

    def test_invalid_json_returns_controlled_failure(self) -> None:
        result = decode_snapshot("{not-json")

        self.assertFalse(result.success)
        self.assertEqual(result.error, "Snapshot payload is not valid JSON.")


if __name__ == "__main__":
    unittest.main()
