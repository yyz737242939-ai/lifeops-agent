from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
import unittest
from dataclasses import fields
from pathlib import Path

from app.runtime.bootstrap import _build_tool_runtime
from app.tools.gateway import ToolGateway
from app.tools.models import ExecutionEvidence, GuardrailDecision


EXPECTED_TOOL_CONTRACTS = {
    "research.append_revision": ("write", "medium", ("research",), "cf3de9e9e46e98efbd174668f0f7abfa559f2cb5731b7289302fea155e604701"),
    "research.build_brief": ("external_read", "low", ("research",), "f9bc5597911a3eb622aa9255e4cbe378ea18b0b57f9583fe333b4a0c3eae4f55"),
    "research.create_note": ("write", "medium", ("research",), "23bdc899780b70aa56017c777fcacbe461aeb1343b0ff82174e3860bb1e69e21"),
    "research.create_topic": ("write", "medium", ("research",), "64c0ae3c6a4509b3e49740377814ca6636a64bc2b6543b6d101d2ba518f86135"),
    "research.link_items": ("write", "medium", ("research",), "67fb77798db815e5a936ab25b77e4de7e75bde5669497bd74bda1c794f487e1b"),
    "research.save_brief": ("write", "medium", ("research",), "6222a558a7a7ae4a9189b6b7660630089200ce04a1dea36f183f1f6db2f6d568"),
    "research.save_source": ("write", "medium", ("research",), "d184920e9702ce8617af946616ce4257f880051d56ed8cd136aeaf804db8129c"),
    "research.search_knowledge": ("read", "low", ("research",), "d9368858ea8b2e240d17ff8f097adcc5375dece2c8b65356a278165b2b4d6f1c"),
    "research.search_papers": ("external_read", "low", ("research",), "a993ffc48fe071d12020a32fd7a1ece320bf32058c59479bdb4ebe17aacc7b9f"),
    "travel.archive_trip": ("write", "medium", ("travel",), "ce0b1bb432ab0fe76236b84049a265fcc66cf42215633bc7a4c376978a71cf9b"),
    "travel.build_itinerary_draft": ("read", "low", ("travel",), "03d71634d2a0bb089559840f2d610f76a50c92f07730261fcc559832808a4546"),
    "travel.check_calendar_availability": ("external_read", "low", ("travel",), "459e4e47c0bc9713e01ec233d1a5097fdfbfccb890ef2dacde04f6e6761bd9bb"),
    "travel.compare_options": ("read", "low", ("travel",), "e455ce6ed26b7f63b7f10cd0bff4cb5403f9f43d517dd1b05cca3a831fd3cf9d"),
    "travel.create_trip": ("write", "medium", ("travel",), "fca792c818588e9a509fd98c70731aa0125db9f94c84ce223f44ca8e300e64d2"),
    "travel.get_trip": ("read", "low", ("travel",), "bcac37486134f5cd07874b0dd5d75e90a5ae0cb1e019438ea61f5104c698ec7b"),
    "travel.get_weather": ("external_read", "low", ("travel",), "b27c362bcf9366b5103aa6a76b97ed48223740ce854960cf4d596f89fd5f0d42"),
    "travel.list_trips": ("read", "low", ("travel",), "0b57bcacafd48dbca092b7b9e946a85b4fdbcdd4afd25a479ecf215fc3704613"),
    "travel.save_itinerary": ("write", "medium", ("travel",), "8c14ee451afbd4c33c83d001a01c8e259c24f17a68c9848c20decb51273f2a82"),
    "travel.search_lodging": ("external_read", "low", ("travel",), "6b0cd2283eae5bec4b3a19bb87c6b3ee4e162a37df425d7566b0fd3c1cff18d4"),
    "travel.search_places": ("external_read", "low", ("travel",), "d4fd4557f4e6f869471898bbe5721cacfc20c6b709198cc934991e26ea0ab151"),
    "travel.search_transport": ("external_read", "low", ("travel",), "c8b32081b649eb0bae5f7cf5e9ec1eab007e8cf060ea525d00c8ae677c3f2301"),
    "travel.update_trip_constraints": ("write", "medium", ("travel",), "978a4d1c3f82f386197e0357c86c0c393ac88f91022e46542c4b87b0c7b02bb2"),
}


class Stage5ToolSurfaceContractTest(unittest.TestCase):
    def test_tool_names_effects_risks_bindings_and_schemas_are_frozen(self) -> None:
        conn = sqlite3.connect(":memory:")
        try:
            runtime = _build_tool_runtime(conn, Path("app/skills"))
            actual = {}
            for definition in runtime.registry.list_definitions():
                schema = json.dumps(
                    {"input": definition.input_schema, "output": definition.output_schema},
                    sort_keys=True,
                    separators=(",", ":"),
                )
                actual[definition.name] = (
                    definition.effect.value,
                    definition.risk.value,
                    definition.skill_ids,
                    hashlib.sha256(schema.encode("utf-8")).hexdigest(),
                )
        finally:
            conn.close()

        self.assertEqual(actual, EXPECTED_TOOL_CONTRACTS)

    def test_confirmation_uses_a_structured_action_not_a_tool_name_string(self) -> None:
        parameters = inspect.signature(ToolGateway.execute).parameters

        self.assertIn("confirmation", parameters)
        self.assertNotIn("confirmed_tool_name", parameters)

    def test_evidence_and_guardrail_models_expose_only_frozen_fields(self) -> None:
        self.assertEqual(
            tuple(item.name for item in fields(ExecutionEvidence)),
            ("evidence_type", "summary", "reference"),
        )
        self.assertEqual(
            tuple(item.name for item in fields(GuardrailDecision)),
            ("action", "stage", "reason_code", "reason", "tool_name"),
        )


if __name__ == "__main__":
    unittest.main()
