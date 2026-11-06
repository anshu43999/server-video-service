import json
import unittest
from pathlib import Path

from app.main import app


ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "fixtures" / "m36_api_contract.json"


def enum_values(schema):
    if "enum" in schema:
        return schema["enum"]
    if schema.get("items", {}).get("enum"):
        return schema["items"]["enum"]
    for branch in schema.get("anyOf", []):
        values = enum_values(branch)
        if values:
            return values
    return None


class M36ApiContractGoldenTests(unittest.TestCase):
    def test_model_target_and_scene_contract_matches_golden(self):
        expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
        openapi = app.openapi()
        actual_paths = {}
        for path, methods in expected["paths"].items():
            actual_paths[path] = {}
            for method in methods:
                operation = openapi["paths"][path][method]
                body = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
                request = body.get("$ref", "").rsplit("/", 1)[-1] or None
                success = sorted(int(code) for code in operation["responses"] if code.isdigit() and 200 <= int(code) < 300)
                actual_paths[path][method] = {"request": request, "success": success}
        self.assertEqual(expected["paths"], actual_paths)

        actual_schemas = {}
        for name in expected["schemas"]:
            schema = openapi["components"]["schemas"][name]
            enums = {}
            for field, definition in schema["properties"].items():
                values = enum_values(definition)
                if values:
                    enums[field] = values
            actual_schemas[name] = {
                "required": schema.get("required", []),
                "fields": sorted(schema["properties"]),
                "enums": enums,
            }
            self.assertFalse(schema.get("additionalProperties", True), name)
        self.assertEqual(expected["schemas"], actual_schemas)


if __name__ == "__main__":
    unittest.main()
