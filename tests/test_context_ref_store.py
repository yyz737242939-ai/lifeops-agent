from datetime import datetime, timedelta
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.runtime.context_ref_store import read_context_ref, save_context_ref


class ContextRefStoreTests(unittest.TestCase):
    def test_saved_ref_includes_metadata_and_payload_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch("app.runtime.context_ref_store.REF_DIR", Path(temporary_directory)):
                ref_id = save_context_ref(
                    tool_name="list_todos",
                    full_result={"ok": True, "todos": [{"id": 1}]},
                    summary={"count": 1},
                )

                payload = read_context_ref(ref_id)

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["ref_id"], ref_id)
        self.assertEqual(payload["tool_name"], "list_todos")
        self.assertIn("created_at", payload)
        self.assertIn("expires_at", payload)
        self.assertEqual(len(payload["payload_hash"]), 64)

    def test_expired_ref_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch("app.runtime.context_ref_store.REF_DIR", Path(temporary_directory)):
                ref_id = save_context_ref(
                    tool_name="list_todos",
                    full_result={"ok": True},
                    summary={"count": 0},
                    ttl_days=1,
                )
                ref_file = Path(temporary_directory) / f"{ref_id}.json"
                payload = read_context_ref(ref_id)
                assert payload is not None
                payload["expires_at"] = (
                    datetime.now() - timedelta(seconds=1)
                ).isoformat(timespec="seconds")
                ref_file.write_text(
                    json.dumps(payload, ensure_ascii=False),
                    encoding="utf-8",
                )

                expired = read_context_ref(ref_id)

        self.assertIsNone(expired)


if __name__ == "__main__":
    unittest.main()
