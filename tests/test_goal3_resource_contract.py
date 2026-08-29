"""Goal 3 资源仓库兑换码契约的外部回归测试。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator, FormatChecker

_DEFAULT_RESOURCE_ROOT = Path(__file__).resolve().parents[7] / "astrbot_plugin_dna_resources"
RESOURCE_ROOT = Path(os.environ.get("DNA_RESOURCE_REPO", _DEFAULT_RESOURCE_ROOT))
LEGACY_FIXTURE = Path(__file__).parent / "fixtures" / "goal3_legacy_dna_codes.json"
ALLOWED_PLATFORMS = {"pc", "android", "ios"}
ALLOWED_SERVERS = {"cn", "global"}


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    assert isinstance(value, dict)
    return value


def _payload() -> dict[str, Any]:
    return _read_json(RESOURCE_ROOT / "data" / "redeem_codes.json")


def _schema() -> dict[str, Any]:
    return _read_json(RESOURCE_ROOT / "schemas" / "redeem-codes.v1.schema.json")


def _semantic_errors(entries: list[Any]) -> list[str]:
    errors: list[str] = []
    seen_codes: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"data[{index}] must be an object")
            continue
        code = entry.get("code")
        if not isinstance(code, str) or not code.strip():
            errors.append(f"data[{index}].code must be non-empty")
        elif code != code.strip():
            errors.append(f"data[{index}].code must be trimmed")
        elif code in seen_codes:
            errors.append(f"duplicate code: {code}")
        else:
            seen_codes.add(code)

        for field, allowed in (
            ("platforms", ALLOWED_PLATFORMS),
            ("servers", ALLOWED_SERVERS),
        ):
            values = entry.get(field)
            if values is None:
                continue
            if not isinstance(values, list) or len(values) != len(set(values)):
                errors.append(f"data[{index}].{field} must be a unique list")
            elif not set(values).issubset(allowed):
                errors.append(f"data[{index}].{field} contains an unsupported value")

        valid_from = entry.get("valid_from")
        expires_at = entry.get("expires_at")
        if valid_from is not None and expires_at is not None:
            try:
                start = datetime.fromisoformat(valid_from)
                end = datetime.fromisoformat(expires_at)
            except (TypeError, ValueError):
                continue
            if start >= end:
                errors.append(f"data[{index}] valid_from must be before expires_at")
    return errors


def test_manifest_declares_contract_directories_and_existing_layout() -> None:
    manifest = _read_json(RESOURCE_ROOT / "resource_manifest.json")
    required_dirs = set(manifest["required_dirs"])

    assert {"data", "schemas"}.issubset(required_dirs)
    assert isinstance(manifest["resource_version"], str)
    assert manifest["resource_version"].startswith("redeem-code-v1-")
    for directory in required_dirs:
        assert (RESOURCE_ROOT / directory).is_dir(), directory


def test_schema_is_valid_and_declares_the_v1_contract() -> None:
    schema = _schema()
    Draft202012Validator.check_schema(schema)

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["required"] == ["format_version", "data"]
    definition = schema["$defs"]["redeemCode"]
    assert definition["required"] == ["code"]
    assert definition["additionalProperties"] is False
    assert set(definition["properties"]) == {
        "code",
        "reward",
        "valid_from",
        "expires_at",
        "platforms",
        "servers",
    }


def test_schema_accepts_minimal_and_full_entries_but_rejects_invalid_shapes() -> None:
    schema = _schema()
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    valid_payloads = [
        {"format_version": 1, "data": [{"code": "ONLY-CODE"}]},
        {
            "format_version": 1,
            "data": [
                {
                    "code": "FULL-CODE",
                    "reward": "委托密函×3",
                    "valid_from": "2026-08-01T00:00:00+08:00",
                    "expires_at": "2026-09-01T00:00:00+08:00",
                    "platforms": ["pc", "android", "ios"],
                    "servers": ["cn", "global"],
                }
            ],
        },
    ]
    for payload in valid_payloads:
        assert list(validator.iter_errors(payload)) == []

    invalid_entries = [
        {},
        {"code": "BAD", "platforms": ["xbox"]},
        {"code": "BAD", "servers": ["jp"]},
        {"code": "BAD", "valid_from": "2026-08-01T00:00:00"},
        {"code": "BAD", "unexpected": True},
    ]
    for entry in invalid_entries:
        errors = list(validator.iter_errors({"format_version": 1, "data": [entry]}))
        assert errors, entry


def test_data_satisfies_semantic_contract_and_keeps_only_canonical_fields() -> None:
    payload = _payload()
    assert payload["format_version"] == 1
    assert isinstance(payload["data"], list)
    assert _semantic_errors(payload["data"]) == []
    for entry in payload["data"]:
        assert set(entry).issubset(
            {"code", "reward", "valid_from", "expires_at", "platforms", "servers"}
        )
        assert "end_at" not in entry


def test_semantic_contract_rejects_duplicate_codes_and_reversed_dates() -> None:
    duplicate = {"code": "SAME", "reward": "first"}
    duplicate_with_other_metadata = {"code": "SAME", "reward": "second"}
    reversed_dates = {
        "code": "REVERSED",
        "valid_from": "2026-09-01T00:00:00+08:00",
        "expires_at": "2026-08-01T00:00:00+08:00",
    }

    errors = _semantic_errors([duplicate, duplicate_with_other_metadata, reversed_dates])
    assert "duplicate code: SAME" in errors
    assert "data[2] valid_from must be before expires_at" in errors


def test_migrated_data_matches_the_public_legacy_end_at_snapshot() -> None:
    legacy = _read_json(LEGACY_FIXTURE)
    migrated = _payload()
    migrated_by_code = {entry["code"]: entry for entry in migrated["data"]}

    assert legacy["code"] == 0
    assert [item["code"] for item in legacy["data"]] == list(migrated_by_code)
    for old_entry in legacy["data"]:
        expected_expiry = datetime.fromtimestamp(
            old_entry["end_at"], timezone.utc
        ).astimezone(ZoneInfo("Asia/Shanghai")).isoformat()
        migrated_entry = migrated_by_code[old_entry["code"]]
        assert migrated_entry == {
            "code": old_entry["code"],
            "expires_at": expected_expiry,
        }
