from __future__ import annotations

import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.common.config import DEFAULT_CONFIG_PATH, load_app_config
from app.common.errors import AppError, ConfigError, MigrationError, SerializationError, StorageError
from app.common.ids import new_id
from app.common.serialization import from_json, to_json
from app.common.time import utc_now_iso


class CommonHelpersTest(unittest.TestCase):
    def test_new_id_uses_readable_prefix_and_uuid_hex(self) -> None:
        value = new_id("run")

        self.assertRegex(value, r"^run_[0-9a-f]{32}$")

    def test_new_id_rejects_blank_prefix(self) -> None:
        with self.assertRaises(ValueError):
            new_id(" ")

    def test_utc_now_iso_returns_timezone_aware_utc_timestamp(self) -> None:
        value = utc_now_iso()
        parsed = datetime.fromisoformat(value)

        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.utcoffset().total_seconds(), 0)

    def test_to_json_is_deterministic_and_preserves_unicode(self) -> None:
        value = to_json({"b": 2, "a": "中文"})

        self.assertEqual(value, '{"a":"中文","b":2}')

    def test_from_json_parses_payload(self) -> None:
        self.assertEqual(from_json('{"ok":true}'), {"ok": True})

    def test_to_json_wraps_unserializable_values(self) -> None:
        with self.assertRaises(SerializationError) as caught:
            to_json({"bad": re.compile("x")})

        self.assertEqual(caught.exception.code, "json_serialize_failed")
        self.assertEqual(caught.exception.details["data_type"], "dict")

    def test_from_json_wraps_invalid_json(self) -> None:
        with self.assertRaises(SerializationError) as caught:
            from_json("{")

        self.assertEqual(caught.exception.code, "json_parse_failed")
        self.assertIn("position", caught.exception.details)

    def test_project_errors_keep_message_code_and_details(self) -> None:
        error = AppError("boom", code="example", details={"run_id": "run_1"})

        self.assertEqual(str(error), "boom")
        self.assertEqual(error.message, "boom")
        self.assertEqual(error.code, "example")
        self.assertEqual(error.details, {"run_id": "run_1"})

    def test_storage_errors_share_base_type(self) -> None:
        self.assertIsInstance(StorageError("storage failed"), AppError)
        self.assertIsInstance(MigrationError("migration failed"), StorageError)

    def test_default_config_declares_database_path(self) -> None:
        config = load_app_config()

        self.assertEqual(DEFAULT_CONFIG_PATH, Path("config/default.json"))
        self.assertEqual(config.database_path, Path("data/lifeops.sqlite3"))
        self.assertEqual(config.log_root, Path("logs/sessions"))
        self.assertEqual(config.skill_root, Path("app/skills"))

    def test_config_rejects_missing_database_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "default.json"
            config_path.write_text('{"database": {}}', encoding="utf-8")

            with self.assertRaises(ConfigError) as caught:
                load_app_config(config_path)

        self.assertEqual(caught.exception.code, "config_database_path_missing")


if __name__ == "__main__":
    unittest.main()
