#!/usr/bin/env python3
"""Fail-closed verification and canonical V5 public reanalysis.

The only outcome-bearing inputs are the public terminal records, the sanitized
public schedule, and the post-run provenance receipt.  Frozen analysis source
files are hash-checked before import.  No confidential run artifact is read.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


class HoldError(RuntimeError):
    """A fail-closed public-release verification condition."""


EXPECTED_RECEIPT_SHA256 = "ca3a05bcfcd53b94c81e0a8604f3afa990f52e4385a66d8141c3f0e426e3b228"
EXPECTED_PRECOMMIT_SHA256 = "39fce0700a3138d959287f568737fc08510112972b614ea6dfd67fe1fdba0272"
EXPECTED_FROZEN_SCHEDULE_SHA256 = "fa07cff66c7d45dd4c95b8fbc679083fc2a50e2f3cca1188a69cc94c681070be"
EXPECTED_ANALYSIS_PLAN_SHA256 = "e9cb2e760a1c0b2767830fe758059de4ca5efc380fa78a418064a33f77d5c4b6"
EXPECTED_PUBLIC_SCHEDULE_SHA256 = "9370f6019cf133a901e892a955780d0164bc9d572b15fd9457b635edf519baf4"
EXPECTED_PUBLIC_RECORDS_SHA256 = "5e74de53068bdd914b745d76434bec0bd6b304d02da17d4b932338f8feabdb48"
EXPECTED_CANONICAL_ANALYSIS_SHA256 = "b3a7089c4572e46114ca29457c363b91827e6bb66677563376aaf0c382ac076b"

JUDGES = ("qwen25_32b_awq_remote", "qwen36_mlx_local")
EXPECTED_RUNS = {
    "qwen25_32b_awq_remote": {
        "invalid_records": 1,
        "public_record_slice_sha256": "0971b521cfd575c15524fe7b873d4f23b12baabb8e84f78b259f2a49c366d7d2",
        "run_manifest_sha256": "1024cda470ddc8081295c7aa19acfe1adeaa945388074656f457a443ed359690",
    },
    "qwen36_mlx_local": {
        "invalid_records": 0,
        "public_record_slice_sha256": "12f35f2855b8b8db7b7f294a072beb797549d1d2ab0b1e830136a53367759797",
        "run_manifest_sha256": "e83062fc906060ec28294ae18bed215c501e6ec595267083a9ab5803bec74e0d",
    },
}
EXPECTED_SOURCE_HASHES = {
    "analyze_v5.py": "11ff5476b098133a37b77dedcf63ddb80f5b65a2fedde7b25c4862d4ce9fea82",
    "reanalyze_public_v5.py": "4c4c2550c299ebbb7892eb88707beb7fbe150611ad0551f191b2dfc91fbdb4f3",
    "ri_reassign_v5.py": "be8ddc02c517c9d9566407a3da7ce4e2fd237c93fac916d840cb49b46d661781",
    "run_v5.py": "68f7568e3ea563f4ae0e9b216a22f8190ad7226b0079efe1a047c1ab39668424",
    "../holdout_harness/harness.py": "6015ddeab1cb926dc64bb3b23824c98de62edcf0d26b962ac323d2ed877632e1",
}

PUBLIC_SCHEDULE_FIELDS = (
    "assignment_lane",
    "assignment_sequence_id",
    "assignment_unit_id",
    "call_id",
    "criterion",
    "exposure_period",
    "global_sequence",
    "microstratum",
    "order",
    "pair_type",
    "position_in_microstratum",
    "preceding_treatment",
    "schedule_slot_id",
    "source_subset",
    "task_id",
    "temporal_block",
    "treatment",
)
PUBLIC_RECORD_FIELDS = (
    "assignment_lane",
    "assignment_sequence_id",
    "assignment_unit_id",
    "call_id",
    "canonical_verdict",
    "criterion",
    "exposure_period",
    "false_preference",
    "invalid",
    "judge_id",
    "order",
    "pair_type",
    "preceding_treatment",
    "signal_success",
    "source_subset",
    "task_id",
    "terminal_status",
    "treatment",
    "valid",
)
JOIN_FIELDS = (
    "assignment_lane",
    "assignment_sequence_id",
    "assignment_unit_id",
    "call_id",
    "criterion",
    "exposure_period",
    "order",
    "pair_type",
    "preceding_treatment",
    "source_subset",
    "task_id",
    "treatment",
)

_URL = re.compile(r"https?://", re.IGNORECASE)
_IPV4 = re.compile(r"(?<![0-9a-f])(?:\d{1,3}\.){3}\d{1,3}(?![0-9a-f])", re.IGNORECASE)
_PRIVATE_PATH = re.compile(r"(?:/Users/|/home/|file://)", re.IGNORECASE)
_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_TIMESTAMP = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_rows(rows: Iterable[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update((canonical_json(row) + "\n").encode("utf-8"))
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HoldError(f"HOLD_JSON_READ {path.name}") from exc
    if not isinstance(value, dict):
        raise HoldError(f"HOLD_JSON_ROOT {path.name}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open(encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HoldError(f"HOLD_JSONL_READ {path.name}") from exc
    if not all(isinstance(row, dict) for row in rows):
        raise HoldError(f"HOLD_JSONL_ROW {path.name}")
    return rows


def reject_sensitive_strings(value: Any, location: str = "root") -> None:
    """Reject common recipient-facing leakage patterns in all three inputs."""
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).casefold()
            forbidden_key_fragments = (
                "prompt",
                "candidate_a",
                "candidate_b",
                "request_payload",
                "raw_response",
                "endpoint",
                "reasoning",
                "thinking",
                "timestamp",
                "hostname",
                "base_url",
                "api_key",
                "authorization",
            )
            if any(fragment in lowered for fragment in forbidden_key_fragments):
                raise HoldError(f"HOLD_SENSITIVE_KEY {location}.{key}")
            reject_sensitive_strings(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_sensitive_strings(child, f"{location}[{index}]")
    elif isinstance(value, str):
        if any(pattern.search(value) for pattern in (_URL, _IPV4, _PRIVATE_PATH, _EMAIL, _TIMESTAMP)):
            raise HoldError(f"HOLD_SENSITIVE_STRING {location}")


def verify_receipt(receipt_path: Path) -> dict[str, Any]:
    if sha256_file(receipt_path) != EXPECTED_RECEIPT_SHA256:
        raise HoldError("HOLD_PUBLIC_RECEIPT_HASH")
    receipt = read_json(receipt_path)
    reject_sensitive_strings(receipt, "receipt")
    if receipt.get("schema_version") != "tae-v5-public-provenance-receipt-v2":
        raise HoldError("HOLD_RECEIPT_SCHEMA")
    if receipt.get("status") != "COMPLETE_POST_RUN_HASH_CHAIN":
        raise HoldError("HOLD_RECEIPT_STATUS")
    frozen = receipt.get("frozen_chain")
    if not isinstance(frozen, dict):
        raise HoldError("HOLD_RECEIPT_FROZEN_CHAIN")
    expected_frozen = {
        "analysis_plan_sha256": EXPECTED_ANALYSIS_PLAN_SHA256,
        "schedule_sha256": EXPECTED_FROZEN_SCHEDULE_SHA256,
        "source_hashes": EXPECTED_SOURCE_HASHES,
        "source_precommit_manifest_sha256": EXPECTED_PRECOMMIT_SHA256,
    }
    if frozen != expected_frozen:
        raise HoldError("HOLD_RECEIPT_FROZEN_CHAIN")
    public_inputs = receipt.get("public_inputs")
    if not isinstance(public_inputs, dict):
        raise HoldError("HOLD_RECEIPT_PUBLIC_INPUTS")
    expected_public_inputs = {
        "schedule": {
            "file": "public_schedule_v5.jsonl",
            "projection_fields": list(PUBLIC_SCHEDULE_FIELDS),
            "records": 612,
            "sha256": EXPECTED_PUBLIC_SCHEDULE_SHA256,
        },
        "terminal_records": {
            "file": "public_terminal_records_v5.jsonl",
            "records": 1224,
            "sha256": EXPECTED_PUBLIC_RECORDS_SHA256,
        },
    }
    if public_inputs != expected_public_inputs:
        raise HoldError("HOLD_RECEIPT_PUBLIC_INPUTS")
    expected_contract = {
        "bootstrap_replicates": 20000,
        "canonical_analysis_sha256": EXPECTED_CANONICAL_ANALYSIS_SHA256,
        "judges": list(JUDGES),
        "output_schema_version": "tae-v5-analysis-v1",
        "ri_replicates": 99999,
    }
    if receipt.get("reanalysis_contract") != expected_contract:
        raise HoldError("HOLD_RECEIPT_REANALYSIS_CONTRACT")
    runs = receipt.get("run_chain")
    if not isinstance(runs, list) or len(runs) != 2:
        raise HoldError("HOLD_RECEIPT_RUN_CHAIN")
    by_judge = {row.get("judge_id"): row for row in runs if isinstance(row, dict)}
    if set(by_judge) != set(JUDGES):
        raise HoldError("HOLD_RECEIPT_RUN_CHAIN")
    for judge in JUDGES:
        expected = {
            "expected_calls": 612,
            "invalid_records": EXPECTED_RUNS[judge]["invalid_records"],
            "judge_id": judge,
            "public_record_count": 612,
            "public_record_slice_sha256": EXPECTED_RUNS[judge]["public_record_slice_sha256"],
            "retry_count": 0,
            "run_manifest_sha256": EXPECTED_RUNS[judge]["run_manifest_sha256"],
            "status": "COMPLETE",
            "terminal_records": 612,
        }
        if by_judge[judge] != expected:
            raise HoldError(f"HOLD_RECEIPT_RUN_CHAIN {judge}")
    return receipt


def verify_source_hashes(source_dir: Path, receipt: dict[str, Any]) -> None:
    source_hashes = receipt["frozen_chain"]["source_hashes"]
    if source_hashes != EXPECTED_SOURCE_HASHES:
        raise HoldError("HOLD_FROZEN_SOURCE_SET")
    for relative, expected in source_hashes.items():
        path = (source_dir / relative).resolve()
        if not path.is_file() or sha256_file(path) != expected:
            raise HoldError(f"HOLD_FROZEN_SOURCE_HASH {relative}")


def verify_public_schedule(path: Path, receipt: dict[str, Any]) -> list[dict[str, Any]]:
    if sha256_file(path) != receipt["public_inputs"]["schedule"]["sha256"]:
        raise HoldError("HOLD_PUBLIC_SCHEDULE_HASH")
    rows = read_jsonl(path)
    if len(rows) != 612:
        raise HoldError("HOLD_PUBLIC_SCHEDULE_COUNT")
    expected_fields = set(PUBLIC_SCHEDULE_FIELDS)
    if any(set(row) != expected_fields for row in rows):
        raise HoldError("HOLD_PUBLIC_SCHEDULE_FIELDS")
    reject_sensitive_strings(rows, "schedule")
    if [row["global_sequence"] for row in rows] != list(range(1, 613)):
        raise HoldError("HOLD_PUBLIC_SCHEDULE_ORDER")
    if [row["schedule_slot_id"] for row in rows] != [f"v5-slot-{index:04d}" for index in range(1, 613)]:
        raise HoldError("HOLD_PUBLIC_SCHEDULE_SLOT_IDS")
    if len({row["call_id"] for row in rows}) != 612:
        raise HoldError("HOLD_PUBLIC_SCHEDULE_DUPLICATE")
    if Counter(row["pair_type"] for row in rows) != Counter(
        {"dc_core_clone": 204, "signal_chosen_vs_rejected": 408}
    ):
        raise HoldError("HOLD_PUBLIC_SCHEDULE_ARM_COUNTS")
    return rows


def verify_public_records(
    path: Path, receipt: dict[str, Any], schedule: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if sha256_file(path) != receipt["public_inputs"]["terminal_records"]["sha256"]:
        raise HoldError("HOLD_PUBLIC_RECORD_HASH")
    rows = read_jsonl(path)
    if len(rows) != 1224:
        raise HoldError("HOLD_PUBLIC_RECORD_COUNT")
    expected_fields = set(PUBLIC_RECORD_FIELDS)
    if any(set(row) != expected_fields for row in rows):
        raise HoldError("HOLD_PUBLIC_RECORD_FIELDS")
    reject_sensitive_strings(rows, "records")
    if Counter(row.get("judge_id") for row in rows) != Counter({judge: 612 for judge in JUDGES}):
        raise HoldError("HOLD_PUBLIC_RECORD_JUDGE_COUNTS")
    if len({(row["judge_id"], row["call_id"]) for row in rows}) != 1224:
        raise HoldError("HOLD_PUBLIC_RECORD_DUPLICATE")
    schedule_by_call = {row["call_id"]: row for row in schedule}
    for row in rows:
        expected = schedule_by_call.get(row["call_id"])
        if expected is None or any(row[field] != expected[field] for field in JOIN_FIELDS):
            raise HoldError(f"HOLD_PUBLIC_RECORD_SCHEDULE_JOIN {row['judge_id']} {row['call_id']}")
    for run in receipt["run_chain"]:
        judge = run["judge_id"]
        judge_rows = [row for row in rows if row["judge_id"] == judge]
        if sha256_rows(judge_rows) != run["public_record_slice_sha256"]:
            raise HoldError(f"HOLD_PUBLIC_RECORD_SLICE_HASH {judge}")
        if sum(bool(row["invalid"]) for row in judge_rows) != run["invalid_records"]:
            raise HoldError(f"HOLD_PUBLIC_RECORD_INVALID_COUNT {judge}")
    return rows


def verify_release_inputs(release_dir: Path, source_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    receipt = verify_receipt(release_dir / "public_provenance_receipt_v5.json")
    verify_source_hashes(source_dir, receipt)
    schedule = verify_public_schedule(release_dir / "public_schedule_v5.jsonl", receipt)
    records = verify_public_records(
        release_dir / "public_terminal_records_v5.jsonl", receipt, schedule
    )
    return receipt, records


def load_frozen_analyzer(source_dir: Path) -> Any:
    sys.path.insert(0, str(source_dir))
    module = importlib.import_module("analyze_v5")
    if Path(module.__file__).resolve() != (source_dir / "analyze_v5.py").resolve():
        raise HoldError("HOLD_ANALYZER_IMPORT_ORIGIN")
    return module


def reproduce(receipt: dict[str, Any], records: list[dict[str, Any]], source_dir: Path) -> dict[str, Any]:
    analyzer = load_frozen_analyzer(source_dir)
    coded = {judge: [row for row in records if row["judge_id"] == judge] for judge in JUDGES}
    contract = receipt["reanalysis_contract"]
    result = analyzer.analyze(
        coded,
        receipt["frozen_chain"]["schedule_sha256"],
        contract["bootstrap_replicates"],
        contract["ri_replicates"],
    )
    output_bytes = (canonical_json(result) + "\n").encode("utf-8")
    if sha256_bytes(output_bytes) != contract["canonical_analysis_sha256"]:
        raise HoldError("HOLD_CANONICAL_ANALYSIS_MISMATCH")
    return result


def write_json_new(path: Path, value: Any) -> None:
    if path.exists():
        raise HoldError(f"HOLD_NO_CLOBBER {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def main() -> None:
    release_default = Path(__file__).resolve().parent
    source_default = release_default.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-dir", type=Path, default=release_default)
    parser.add_argument("--analysis-source-dir", type=Path, default=source_default)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if not args.verify_only and args.out is None:
        raise SystemExit("HOLD_OUTPUT_REQUIRED")
    try:
        receipt, records = verify_release_inputs(
            args.release_dir.resolve(), args.analysis_source_dir.resolve()
        )
        status = {
            "receipt_sha256": EXPECTED_RECEIPT_SHA256,
            "status": "PASS_INPUT_HASH_CHAIN",
        }
        if not args.verify_only:
            result = reproduce(receipt, records, args.analysis_source_dir.resolve())
            write_json_new(args.out.resolve(), result)
            status = {
                "analysis_sha256": EXPECTED_CANONICAL_ANALYSIS_SHA256,
                "receipt_sha256": EXPECTED_RECEIPT_SHA256,
                "status": "PASS_CANONICAL_REANALYSIS",
            }
        print(canonical_json(status))
    except HoldError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
