import tempfile
import unittest
from pathlib import Path

from pydantic import BaseModel

from app.utils.json_file import (
    load_model_list,
    parse_json_object,
    read_json_file,
    save_model_list,
    write_json_file,
)


class Item(BaseModel):
    id: int
    name: str


class JsonFileUtilsTests(unittest.TestCase):
    def test_round_trips_model_list(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "nested" / "items.json"
            save_model_list(path, [Item(id=1, name="test")])

            loaded = load_model_list(path, Item)

        self.assertEqual(loaded, [Item(id=1, name="test")])

    def test_rejects_wrong_top_level_type(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "value.json"
            write_json_file(path, {"id": 1})

            with self.assertRaisesRegex(ValueError, "must contain a JSON list"):
                read_json_file(path, list)

    def test_parse_json_object_rejects_invalid_or_non_object_json(self) -> None:
        self.assertEqual(parse_json_object('{"ok":true}'), {"ok": True})
        self.assertIsNone(parse_json_object("not-json"))
        self.assertIsNone(parse_json_object("[]"))


if __name__ == "__main__":
    unittest.main()
