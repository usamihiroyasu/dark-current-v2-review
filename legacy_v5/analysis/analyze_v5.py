#!/usr/bin/env python3
"""Fail-closed V5 analysis and public-safe export.

V5 contains matched clone and signal arms on 102 fresh items.  This analyzer
never pools configurations or V3/V4 outcomes and never reads an endpoint.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import ri_reassign_v5 as ri
import run_v5 as rv


SCHEMA_VERSION = "tae-v5-analysis-v1"
JUDGES = ("qwen25_32b_awq_remote", "qwen36_mlx_local")
CRITERIA = ("neutral", "strict")
ALPHA = 0.05


class HoldError(RuntimeError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HoldError(f"HOLD_JSON_ROOT {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_json_new(path: Path, value: Any) -> None:
    if path.exists():
        raise HoldError(f"HOLD_NO_CLOBBER {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def write_jsonl_new(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    if path.exists():
        raise HoldError(f"HOLD_NO_CLOBBER {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")


def binomial_cdf(k: int, n: int, p: float) -> float:
    return sum(math.comb(n, index) * p**index * (1.0 - p) ** (n - index) for index in range(k + 1))


def clopper_pearson_upper(k: int, n: int, alpha: float = 0.05) -> float:
    """One-sided exact upper confidence limit, dependency-free."""
    if k >= n:
        return 1.0
    low, high = 0.0, 1.0
    for _ in range(100):
        middle = (low + high) / 2.0
        if binomial_cdf(k, n, middle) > alpha:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def holm(items: list[dict[str, Any]], alpha: float = ALPHA) -> list[dict[str, Any]]:
    ordered = sorted(enumerate(items), key=lambda pair: (pair[1]["raw_p"], pair[1]["id"]))
    adjusted = [1.0] * len(items)
    running = 0.0
    size = len(items)
    for rank, (index, item) in enumerate(ordered):
        running = max(running, min(1.0, (size - rank) * item["raw_p"]))
        adjusted[index] = running
    return [
        {**item, "holm_adjusted_p": adjusted[index], "reject_after_holm": adjusted[index] <= alpha}
        for index, item in enumerate(items)
    ]


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lo, hi = math.floor(position), math.ceil(position)
    if lo == hi:
        return ordered[lo]
    weight = position - lo
    return ordered[lo] * (1 - weight) + ordered[hi] * weight


class HashRNG:
    def __init__(self, seed: str):
        self.seed = seed.encode("utf-8")
        self.counter = 0

    def randbelow(self, n: int) -> int:
        space = 1 << 256
        limit = space - (space % n)
        while True:
            value = int.from_bytes(
                hashlib.sha256(self.seed + self.counter.to_bytes(16, "big")).digest(), "big"
            )
            self.counter += 1
            if value < limit:
                return value % n


def stratified_bootstrap_lower(
    values_by_subset: dict[str, list[float]], namespace: str, replicates: int
) -> dict[str, Any]:
    expected_subsets = {"Factuality", "Focus", "Math", "Precise IF", "Safety", "Ties"}
    if set(values_by_subset) != expected_subsets or any(
        len(values_by_subset[subset]) != 17 for subset in expected_subsets
    ):
        raise HoldError("HOLD_BOOTSTRAP_SUBSET_STRUCTURE")
    rng = HashRNG(namespace)
    estimates = []
    for _ in range(replicates):
        subset_means = []
        for subset in sorted(expected_subsets):
            values = values_by_subset[subset]
            draw = [values[rng.randbelow(17)] for _ in range(17)]
            subset_means.append(sum(draw) / 17)
        estimates.append(sum(subset_means) / 6)
    return {
        "replicates": replicates,
        "two_sided_95": [percentile(estimates, 0.025), percentile(estimates, 0.975)],
        "one_sided_lower_95": percentile(estimates, 0.05),
    }


def verify_frozen(
    frozen: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], str, str]:
    manifest_path = frozen / "precommit_manifest_v5.json"
    manifest = read_json(manifest_path)
    if manifest.get("status") != "PRECOMMITTED_NOT_EXECUTED":
        raise HoldError("HOLD_PRECOMMIT_STATUS")
    digest_tokens = (frozen / "PRECOMMIT_SHA256.txt").read_text().strip().split()
    if digest_tokens != [sha256_file(manifest_path), "precommit_manifest_v5.json"]:
        raise HoldError("HOLD_PRECOMMIT_DIGEST")
    for name, digest in manifest.get("frozen_file_hashes", {}).items():
        path = frozen / name
        if not path.is_file() or sha256_file(path) != digest:
            raise HoldError(f"HOLD_FROZEN_HASH {name}")
    package_root = frozen.parent.parent.resolve()
    for relative, digest in manifest.get("package_source_hashes", {}).items():
        path = (package_root / relative).resolve()
        try:
            path.relative_to(package_root)
        except ValueError as exc:
            raise HoldError(f"HOLD_PACKAGE_SOURCE_PATH {relative}") from exc
        if not path.is_file() or sha256_file(path) != digest:
            raise HoldError(f"HOLD_PACKAGE_SOURCE_HASH {relative}")
    schedule_path = frozen / "schedule_v5.jsonl"
    if sha256_file(schedule_path) != manifest.get("schedule_sha256"):
        raise HoldError("HOLD_SCHEDULE_HASH")
    schedule = read_jsonl(schedule_path)
    if len(schedule) != 612 or [row["global_sequence"] for row in schedule] != list(range(1, 613)):
        raise HoldError("HOLD_SCHEDULE_SHAPE")
    return (
        manifest,
        schedule,
        sha256_file(manifest_path),
        sha256_file(frozen / "PRECOMMIT_SHA256.txt"),
    )


def _verify_artifact_metadata(
    run_dir: Path, run_manifest: dict[str, Any], filename: str
) -> None:
    metadata = run_manifest.get("artifacts", {}).get(filename)
    path = run_dir / filename
    if not isinstance(metadata, dict) or not path.is_file():
        raise HoldError(f"HOLD_ARTIFACT_MISSING {filename}")
    if metadata.get("sha256") != sha256_file(path):
        raise HoldError(f"HOLD_ARTIFACT_HASH {filename}")
    if metadata.get("bytes") != path.stat().st_size:
        raise HoldError(f"HOLD_ARTIFACT_SIZE {filename}")
    if filename.endswith(".jsonl") and metadata.get("records") != len(read_jsonl(path)):
        raise HoldError(f"HOLD_ARTIFACT_RECORDS {filename}")


def _derive_terminal(
    config: dict[str, Any], call: dict[str, Any], raw: dict[str, Any]
) -> dict[str, Any]:
    encoded = raw.get("raw_response_base64")
    if not isinstance(encoded, str):
        raise HoldError("HOLD_RAW_BASE64_MISSING")
    try:
        body = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise HoldError("HOLD_RAW_BASE64_INVALID") from exc
    if raw.get("raw_response_sha256") != hashlib.sha256(body).hexdigest():
        raise HoldError("HOLD_RAW_BODY_HASH")
    transport_error = raw.get("transport_error")
    http_status = raw.get("http_status")
    response = None
    response_json_error = None
    if body:
        try:
            decoded = json.loads(body.decode("utf-8"))
            if not isinstance(decoded, dict):
                raise ValueError("root_not_object")
            response = decoded
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            response_json_error = f"{type(exc).__name__}:{exc}"
    content = ""
    response_model = None
    thinking_sha = None
    extract_error = None
    if response is not None and http_status == 200:
        try:
            content, _, response_model, thinking_sha = rv.extract_response(config, response)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            extract_error = f"{type(exc).__name__}:{exc}"
    if transport_error is not None:
        status, reason = "TRANSPORT_ERROR", transport_error
    elif http_status != 200:
        status, reason = "HTTP_ERROR", f"http_status:{http_status}"
    elif response_json_error is not None:
        status, reason = "RESPONSE_JSON_INVALID", response_json_error
    elif extract_error is not None:
        status, reason = "RESPONSE_SCHEMA_INVALID", extract_error
    elif response_model is None:
        status, reason = "SERVED_MODEL_MISSING", "response_model_missing"
    elif response_model != config["model"]:
        status, reason = "SERVED_MODEL_MISMATCH", f"configured={config['model']};served={response_model}"
    else:
        parsed = rv.parse_winner(content)
        status = "OK" if parsed["valid"] else "PARSER_INVALID"
        reason = None if parsed["valid"] else parsed["error"]
        return {
            "terminal_status": status,
            "invalid_reason": reason,
            "response_model": response_model,
            "response_content": content,
            "response_content_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "parse": parsed,
            "canonical_verdict": rv.to_canonical_choice(call, parsed["winner"]),
            "thinking_present": thinking_sha is not None,
            "thinking_sha256": thinking_sha,
        }
    parsed = {
        "parser_version": "winner-json-v1-strict",
        "valid": False,
        "winner": None,
        "error": reason,
    }
    return {
        "terminal_status": status,
        "invalid_reason": reason,
        "response_model": response_model,
        "response_content": content,
        "response_content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "parse": parsed,
        "canonical_verdict": None,
        "thinking_present": thinking_sha is not None,
        "thinking_sha256": thinking_sha,
    }


def load_run(
    run_dir: Path,
    schedule: list[dict[str, Any]],
    manifest_sha: str,
    digest_file_sha: str,
    frozen_manifest: dict[str, Any],
    frozen_dir: Path,
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    manifest = read_json(run_dir / "run_manifest.json")
    if manifest.get("status") != "COMPLETE" or manifest.get("retry_count") != 0:
        raise HoldError(f"HOLD_RUN_NOT_COMPLETE {run_dir}")
    if manifest.get("precommit_manifest_sha256") != manifest_sha:
        raise HoldError(f"HOLD_RUN_PRECOMMIT_BINDING {run_dir}")
    checksum = read_json(run_dir / "RUN_MANIFEST_SHA256.json")
    if checksum.get("run_id") != manifest.get("run_id") or checksum.get("run_manifest_sha256") != sha256_file(run_dir / "run_manifest.json"):
        raise HoldError(f"HOLD_RUN_MANIFEST_CHECKSUM {run_dir}")
    for filename in (
        "dispatch_intents.jsonl",
        "terminal_records.jsonl",
        "raw_responses_confidential.jsonl",
        "model_preflight_confidential.jsonl",
        "summary.json",
    ):
        _verify_artifact_metadata(run_dir, manifest, filename)

    plan = read_json(run_dir / "run_plan_snapshot.json")
    config = read_json(run_dir / "judge_config_confidential.json")
    anchor = read_json(run_dir / "precommit_anchor_snapshot.json")
    if sha256_file(run_dir / "precommit_anchor_snapshot.json") != manifest.get("anchor_snapshot_sha256"):
        raise HoldError("HOLD_ANCHOR_SNAPSHOT_HASH")
    required_anchor = {
        "schema_version", "precommit_manifest_sha256",
        "precommit_sha256_file_sha256", "anchored_at_utc", "anchor_type",
        "anchor_reference", "verified_by", "verification_status",
    }
    if set(anchor) != required_anchor or anchor.get("schema_version") != "tae-v5-precommit-anchor-v1" or anchor.get("verification_status") != "PASS":
        raise HoldError("HOLD_ANCHOR_SCHEMA_OR_STATUS")
    if anchor.get("precommit_manifest_sha256") != manifest_sha or anchor.get("precommit_sha256_file_sha256") != digest_file_sha:
        raise HoldError("HOLD_ANCHOR_PRECOMMIT_BINDING")
    if not str(anchor.get("anchor_reference", "")).strip() or not str(anchor.get("verified_by", "")).strip():
        raise HoldError("HOLD_ANCHOR_EMPTY_FIELD")
    if manifest.get("anchor_reference_sha256") != hashlib.sha256(anchor["anchor_reference"].encode()).hexdigest():
        raise HoldError("HOLD_ANCHOR_REFERENCE_HASH")
    if rv.parse_utc(anchor["anchored_at_utc"]) < rv.parse_utc(frozen_manifest["created_at_utc"]):
        raise HoldError("HOLD_ANCHOR_PREDATES_MANIFEST")
    if manifest.get("judge_id") != config.get("judge_id") or plan.get("judge_id") != config.get("judge_id"):
        raise HoldError("HOLD_RUN_CONFIG_ID")
    frozen_plan = frozen_dir / f"run_plan_{manifest['judge_id']}.json"
    if not frozen_plan.is_file() or sha256_file(frozen_plan) != frozen_manifest.get("frozen_file_hashes", {}).get(frozen_plan.name):
        raise HoldError("HOLD_FROZEN_RUN_PLAN")
    if sha256_file(run_dir / "run_plan_snapshot.json") != sha256_file(frozen_plan):
        raise HoldError("HOLD_RUN_PLAN_SNAPSHOT_HASH")
    registry = read_json(frozen_dir / "configuration_registry_v5.json")
    included = {row["judge_id"]: row for row in registry.get("included", [])}
    if set(included) != set(JUDGES) or included[manifest["judge_id"]].get("judge_config_sha256") != rv.sha256_json(config):
        raise HoldError("HOLD_FROZEN_CONFIG_REGISTRY")
    if manifest.get("judge_config_sha256") != rv.sha256_json(config) or plan.get("judge_config_sha256") != rv.sha256_json(config):
        raise HoldError("HOLD_RUN_CONFIG_HASH")
    if manifest.get("schedule_sha256") != plan.get("schedule_sha256") or sha256_file(run_dir / "schedule_snapshot.jsonl") != manifest.get("schedule_sha256"):
        raise HoldError("HOLD_RUN_SCHEDULE_HASH")
    if read_jsonl(run_dir / "schedule_snapshot.jsonl") != schedule:
        raise HoldError("HOLD_RUN_SCHEDULE_SNAPSHOT")
    if manifest.get("analysis_plan_sha256") != plan.get("analysis_plan_sha256"):
        raise HoldError("HOLD_RUN_ANALYSIS_PLAN_HASH")
    if manifest.get("endpoint_origin_sha256") != hashlib.sha256(rv.endpoint_origin(config).encode()).hexdigest():
        raise HoldError("HOLD_ENDPOINT_ORIGIN_HASH")

    terminals = read_jsonl(run_dir / "terminal_records.jsonl")
    intents = read_jsonl(run_dir / "dispatch_intents.jsonl")
    raw_rows = read_jsonl(run_dir / "raw_responses_confidential.jsonl")
    preflights = read_jsonl(run_dir / "model_preflight_confidential.jsonl")
    if len(terminals) != 612 or len(intents) != 612:
        raise HoldError(f"HOLD_TERMINAL_COUNT {run_dir}")
    if any(row.get("attempt") != 1 or row.get("retry_ordinal") != 0 for row in intents):
        raise HoldError(f"HOLD_RETRY_DEFECT {run_dir}")
    if [row.get("global_sequence") for row in intents] != list(range(1, 613)) or [row.get("global_sequence") for row in terminals] != list(range(1, 613)):
        raise HoldError("HOLD_JOURNAL_ORDER")
    context_keys = (
        "run_id", "judge_id", "judge_config_sha256", "schedule_sha256",
        "analysis_plan_sha256", "precommit_manifest_sha256",
        "anchor_reference_sha256", "anchor_snapshot_sha256",
    )
    if not preflights:
        raise HoldError("HOLD_PREFLIGHT_MISSING")
    valid_preflight_hashes = set()
    for preflight in preflights:
        if config["model"] not in preflight.get("served_model_ids", []):
            raise HoldError("HOLD_PREFLIGHT_MODEL")
        if (
            preflight.get("configured_model") != config["model"]
            or preflight.get("configured_backend") != config.get("backend")
        ):
            raise HoldError("HOLD_PREFLIGHT_BINDING")
        if any(preflight.get(key) != manifest.get(key) for key in context_keys):
            raise HoldError("HOLD_PREFLIGHT_CONTEXT")
        checked_at = rv.parse_utc(preflight.get("checked_at_utc"))
        if checked_at < rv.parse_utc(anchor["anchored_at_utc"]):
            raise HoldError("HOLD_PREFLIGHT_PREDATES_ANCHOR")
        valid_preflight_hashes.add(rv.sha256_json(preflight))
    first_intent_utc = intents[0].get("dispatch_intent_utc")
    if rv.parse_utc(anchor["anchored_at_utc"]) >= rv.parse_utc(first_intent_utc):
        raise HoldError("HOLD_LATE_ANCHOR")
    if manifest.get("first_dispatch_intent_utc") != first_intent_utc or manifest.get("last_dispatch_intent_utc") != intents[-1].get("dispatch_intent_utc"):
        raise HoldError("HOLD_RUN_INTENT_BOUNDARY")
    raw_by_sequence = {row.get("global_sequence"): row for row in raw_rows}
    if len(raw_by_sequence) != len(raw_rows):
        raise HoldError("HOLD_RAW_DUPLICATE")
    allowed_raw_slots = {row["global_sequence"] for row in terminals if row.get("raw_response_sha256") is not None}
    optional_ambiguous_slots = {row["global_sequence"] for row in terminals if row.get("terminal_status") == "AMBIGUOUS_DISPATCH_INVALID"}
    if not allowed_raw_slots.issubset(raw_by_sequence) or not set(raw_by_sequence).issubset(allowed_raw_slots | optional_ambiguous_slots):
        raise HoldError("HOLD_RAW_SLOT_KEYSET")
    coded = []
    for expected, intent, terminal in zip(schedule, intents, terminals):
        if terminal.get("global_sequence") != expected["global_sequence"] or terminal.get("call_id") != expected["call_id"]:
            raise HoldError(f"HOLD_SLOT_BINDING {run_dir}")
        if intent.get("global_sequence") != expected["global_sequence"] or intent.get("call_id") != expected["call_id"]:
            raise HoldError("HOLD_INTENT_SLOT_BINDING")
        if any(intent.get(key) != manifest.get(key) or terminal.get(key) != manifest.get(key) for key in context_keys):
            raise HoldError("HOLD_JOURNAL_CONTEXT")
        if terminal.get("dispatch_intent_sha256") != rv.sha256_json(intent):
            raise HoldError("HOLD_INTENT_TERMINAL_CHAIN")
        if intent.get("preflight_record_sha256") not in valid_preflight_hashes:
            raise HoldError("HOLD_INTENT_PREFLIGHT_BINDING")
        for key, value in rv.schedule_fields(expected).items():
            if intent.get(key) != value or terminal.get(key) != value:
                raise HoldError(f"HOLD_JOURNAL_SCHEDULE_FIELD {key}")
        request_url, payload = rv.build_request(config, rv.render_messages(expected))
        if intent.get("request_sha256") != rv.sha256_json(payload):
            raise HoldError("HOLD_REQUEST_HASH")
        ambiguous = terminal.get("terminal_status") == "AMBIGUOUS_DISPATCH_INVALID"
        if ambiguous:
            if terminal.get("latency_ms") is not None or terminal.get("response_utc") is not None:
                raise HoldError("HOLD_AMBIGUOUS_TERMINAL_TIMING")
        elif not isinstance(terminal.get("latency_ms"), (int, float)) or terminal["latency_ms"] < 0:
            raise HoldError("HOLD_LATENCY")
        rv.parse_utc(intent["dispatch_intent_utc"])
        if not ambiguous:
            rv.parse_utc(terminal["response_utc"])
        raw = raw_by_sequence.get(expected["global_sequence"])
        if raw is None:
            if terminal.get("terminal_status") != "AMBIGUOUS_DISPATCH_INVALID" or terminal.get("raw_response_sha256") is not None:
                raise HoldError("HOLD_RAW_MISSING")
        else:
            if any(raw.get(key) != manifest.get(key) for key in context_keys):
                raise HoldError("HOLD_RAW_CONTEXT")
            if raw.get("dispatch_intent_sha256") != rv.sha256_json(intent) or raw.get("call_id") != expected["call_id"]:
                raise HoldError("HOLD_RAW_INTENT_CHAIN")
            if raw.get("request_url") != request_url or raw.get("request") != payload:
                raise HoldError("HOLD_RAW_REQUEST_REDERIVATION")
            if terminal.get("raw_response_sha256") != raw.get("raw_response_sha256"):
                raise HoldError("HOLD_RAW_TERMINAL_HASH")
            derived = _derive_terminal(config, expected, raw)
            for key, value in derived.items():
                if terminal.get(key) != value:
                    raise HoldError(f"HOLD_TERMINAL_REDERIVATION {key}")
            if raw.get("response_utc") != terminal.get("response_utc") or rv.parse_utc(raw["response_utc"]) < rv.parse_utc(intent["dispatch_intent_utc"]):
                raise HoldError("HOLD_RESPONSE_TIME_CHAIN")
        parse = terminal.get("parse", {})
        valid = terminal.get("terminal_status") == "OK" and parse.get("valid") is True
        canonical = terminal.get("canonical_verdict") if valid else None
        arm = expected["pair_type"]
        false_preference = bool(valid and canonical != "tie") if arm == "dc_core_clone" else None
        signal_success = bool(valid and canonical == "chosen") if arm == "signal_chosen_vs_rejected" else None
        coded.append(
            {
                "judge_id": manifest["judge_id"],
                "call_id": expected["call_id"],
                "task_id": expected["task_id"],
                "assignment_unit_id": expected["assignment_unit_id"],
                "assignment_sequence_id": expected["assignment_sequence_id"],
                "assignment_lane": expected["assignment_lane"],
                "exposure_period": expected["exposure_period"],
                "treatment": expected["treatment"],
                "preceding_treatment": expected["preceding_treatment"],
                "pair_type": arm,
                "source_subset": expected["source_subset"],
                "criterion": expected["criterion"],
                "order": expected["order"],
                "canonical_verdict": canonical,
                "valid": valid,
                "invalid": not valid,
                "false_preference": false_preference,
                "signal_success": signal_success,
                "terminal_status": terminal.get("terminal_status"),
                "invalid_reason": terminal.get("invalid_reason"),
            }
        )
    invalid = sum(row["invalid"] for row in coded)
    gate = {
        "judge_id": manifest["judge_id"],
        "invalid_count": invalid,
        "invalid_rate": invalid / 612,
        "threshold": 0.01,
        "status": "PASS" if invalid / 612 <= 0.01 else "HOLD_INVALID_RATE",
    }
    summary = read_json(run_dir / "summary.json")
    expected_summary = {
        "completion_state": "COMPLETE",
        "expected_terminal_records": 612,
        "terminal_records": 612,
        "invalid_records": invalid,
        "invalid_rate": invalid / 612,
        "retry_count": 0,
    }
    if any(summary.get(key) != value for key, value in expected_summary.items()):
        raise HoldError("HOLD_SUMMARY_RECONCILIATION")
    return manifest["judge_id"], coded, gate


def assignment_rows_from_coded(coded: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in coded:
        grouped[row["assignment_unit_id"]].append(row)
    assignments = []
    for unit, rows in sorted(grouped.items()):
        sequence_ids = {row["assignment_sequence_id"] for row in rows}
        lanes = {int(row["assignment_lane"]) for row in rows}
        arms = {row["pair_type"] for row in rows}
        if len(sequence_ids) != 1 or len(lanes) != 1 or len(arms) != 1:
            raise HoldError(f"HOLD_ASSIGNMENT_METADATA {unit}")
        assignments.append(
            {
                "assignment_unit_id": unit,
                "pair_type": next(iter(arms)),
                "lane": next(iter(lanes)),
                "sequence_id": next(iter(sequence_ids)),
            }
        )
    if len(assignments) != 204:
        raise HoldError("HOLD_ASSIGNMENT_UNIT_COUNT")
    return assignments


def signal_statistic(
    coded: list[dict[str, Any]],
    assignment_rows: list[dict[str, Any]],
    contrast: str,
) -> float:
    outcome_by_unit_period = {
        (row["assignment_unit_id"], int(row["exposure_period"])): float(
            row["signal_success"] or False
        )
        for row in coded
        if row["pair_type"] == "signal_chosen_vs_rejected"
    }
    values = []
    for assignment in assignment_rows:
        if assignment["pair_type"] != "signal_chosen_vs_rejected":
            continue
        treatments = assignment.get("treatments_by_period")
        if treatments is None:
            treatments = list(ri.WILLIAMS[assignment["sequence_id"]])
        cells: dict[str, float] = {}
        for period, treatment in enumerate(treatments, start=1):
            cells[treatment] = outcome_by_unit_period[
                (assignment["assignment_unit_id"], period)
            ]
        if set(cells) != {"N_AB", "N_BA", "S_AB", "S_BA"}:
            raise HoldError("HOLD_SIGNAL_TREATMENT_COVERAGE")
        if contrast == "criterion":
            value = (cells["S_AB"] + cells["S_BA"]) / 2 - (
                cells["N_AB"] + cells["N_BA"]
            ) / 2
        elif contrast == "order":
            value = (cells["N_BA"] + cells["S_BA"]) / 2 - (
                cells["N_AB"] + cells["S_AB"]
            ) / 2
        elif contrast == "interaction":
            value = (cells["S_BA"] - cells["S_AB"]) - (
                cells["N_BA"] - cells["N_AB"]
            )
        else:
            raise HoldError(f"HOLD_UNKNOWN_CONTRAST {contrast}")
        values.append(value)
    if len(values) != 102:
        raise HoldError("HOLD_SIGNAL_RI_UNIT_COUNT")
    return sum(values) / len(values)


def signal_randomization_families(
    coded_by_judge: dict[str, list[dict[str, Any]]],
    assignments: list[dict[str, Any]],
    schedule_sha: str,
    replicates: int,
    operational: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if replicates < 1:
        raise HoldError("HOLD_RI_REPLICATES")
    contrasts = ("criterion", "order", "interaction")
    observed = {
        (judge, contrast): signal_statistic(
            coded_by_judge[judge], assignments, contrast
        )
        for judge in JUDGES
        for contrast in contrasts
    }
    tail = Counter()
    for replicate in range(1, replicates + 1):
        redrawn = ri.draw_reassignment(assignments, schedule_sha, replicate)
        for judge in JUDGES:
            for contrast in contrasts:
                statistic = signal_statistic(
                    coded_by_judge[judge], redrawn, contrast
                )
                tail[(judge, contrast)] += int(
                    abs(statistic) >= abs(observed[(judge, contrast)]) - 1e-15
                )
    members = []
    for judge in JUDGES:
        for contrast in contrasts:
            computed = (tail[(judge, contrast)] + 1) / (replicates + 1)
            eligible = operational[judge]["status"] == "PASS"
            members.append(
                {
                    "id": f"{judge}|signal|{contrast}",
                    "judge_id": judge,
                    "contrast": contrast,
                    "estimate": observed[(judge, contrast)],
                    "ri_tail_count": tail[(judge, contrast)],
                    "ri_replicates": replicates,
                    "diagnostic_computed_raw_p": computed,
                    "raw_p": computed if eligible else 1.0,
                    "status": "CONFIRMATORY_ELIGIBLE" if eligible else "EXPLORATORY_PIPELINE_DIAGNOSTIC",
                }
            )
    primary = [row for row in members if row["contrast"] == "criterion"]
    secondary = [row for row in members if row["contrast"] != "criterion"]
    if len(primary) != 2 or len(secondary) != 4:
        raise HoldError("HOLD_RI_FIXED_FAMILY_SIZE")
    return holm(primary), holm(secondary)


def clone_randomization_family(
    coded_by_judge: dict[str, list[dict[str, Any]]],
    assignments: list[dict[str, Any]],
    schedule_sha: str,
    replicates: int,
    operational: dict[str, Any],
) -> list[dict[str, Any]]:
    clone_assignments = [row for row in assignments if row["pair_type"] == "dc_core_clone"]
    if len(clone_assignments) != 102:
        raise HoldError("HOLD_CLONE_RI_ASSIGNMENTS")

    def statistic(coded: list[dict[str, Any]], mapped: list[dict[str, Any]]) -> float:
        outcome_by_unit_period = {
            (row["assignment_unit_id"], int(row["exposure_period"])): float(
                row["invalid"] or bool(row["false_preference"])
            )
            for row in coded if row["pair_type"] == "dc_core_clone"
        }
        values = []
        for assignment in mapped:
            if assignment["pair_type"] != "dc_core_clone":
                continue
            treatments = assignment.get("treatments_by_period") or list(
                ri.CLONE_SEQUENCES[assignment["sequence_id"]]
            )
            cells = {
                treatment: outcome_by_unit_period[(assignment["assignment_unit_id"], period)]
                for period, treatment in enumerate(treatments, start=1)
            }
            values.append(cells["S"] - cells["N"])
        return sum(values) / len(values)

    observed = {judge: statistic(coded_by_judge[judge], clone_assignments) for judge in JUDGES}
    tails = Counter()
    for replicate in range(1, replicates + 1):
        redrawn = ri.draw_reassignment(assignments, schedule_sha, replicate)
        for judge in JUDGES:
            draw = statistic(coded_by_judge[judge], redrawn)
            tails[judge] += int(abs(draw) >= abs(observed[judge]) - 1e-15)
    members = []
    for judge in JUDGES:
        computed = (tails[judge] + 1) / (replicates + 1)
        eligible = operational[judge]["status"] == "PASS"
        members.append({
            "id": f"{judge}|clone|criterion",
            "judge_id": judge,
            "contrast": "strict_minus_neutral_adverse",
            "estimate": observed[judge],
            "ri_tail_count": tails[judge],
            "ri_replicates": replicates,
            "diagnostic_computed_raw_p": computed,
            "raw_p": computed if eligible else 1.0,
            "status": "CONFIRMATORY_ELIGIBLE" if eligible else "EXPLORATORY_PIPELINE_DIAGNOSTIC",
        })
    return holm(members)


def analyze(
    coded_by_judge: dict[str, list[dict[str, Any]]],
    schedule_sha: str,
    bootstrap_replicates: int,
    ri_replicates: int,
) -> dict[str, Any]:
    if set(coded_by_judge) != set(JUDGES):
        raise HoldError("HOLD_FIXED_JUDGE_FAMILY")
    operational = {}
    dc = []
    utility = []
    matched = []
    subset_descriptive = []
    for judge in JUDGES:
        coded = coded_by_judge[judge]
        invalid_total = sum(row["invalid"] for row in coded)
        operational[judge] = {
            "invalid_count": invalid_total,
            "invalid_rate": invalid_total / 612,
            "threshold": 0.01,
            "status": "PASS" if invalid_total / 612 <= 0.01 else "HOLD",
        }
        by_task = defaultdict(list)
        for row in coded:
            by_task[row["task_id"]].append(row)
        if len(by_task) != 102:
            raise HoldError(f"HOLD_MATCHED_TASK_COUNT {judge}")
        for criterion in CRITERIA:
            clone = [row for row in coded if row["pair_type"] == "dc_core_clone" and row["criterion"] == criterion]
            if len(clone) != 102:
                raise HoldError("HOLD_DC_CELL_SIZE")
            invalid = sum(row["invalid"] for row in clone)
            events = sum(bool(row["false_preference"]) for row in clone)
            evaluable = invalid == 0 and operational[judge]["status"] == "PASS"
            dc.append(
                {
                    "id": f"{judge}|dc|{criterion}",
                    "judge_id": judge,
                    "criterion": criterion,
                    "n": 102,
                    "false_preferences": events,
                    "invalid_count": invalid,
                    "rate": events / 102,
                    "one_sided_exact_upper_95": clopper_pearson_upper(events, 102),
                    "raw_p": binomial_cdf(events, 102, 0.05) if evaluable else 1.0,
                    "status": "EVALUABLE" if evaluable else "NOT_EVALUABLE_INVALID_OR_OPERATIONAL_HOLD",
                }
            )
            unit_values = []
            unit_values_by_subset: dict[str, list[float]] = defaultdict(list)
            for task_id in sorted(by_task):
                rows = [
                    row for row in by_task[task_id]
                    if row["pair_type"] == "signal_chosen_vs_rejected" and row["criterion"] == criterion
                ]
                if len(rows) != 2 or {row["order"] for row in rows} != {"AB", "BA"}:
                    raise HoldError(f"HOLD_SIGNAL_MATCH {judge} {task_id} {criterion}")
                task_value = sum(float(row["signal_success"] or False) for row in rows) / 2.0
                unit_values.append(task_value)
                subsets = {row["source_subset"] for row in rows}
                if len(subsets) != 1:
                    raise HoldError("HOLD_SIGNAL_TASK_SUBSET_MISMATCH")
                unit_values_by_subset[next(iter(subsets))].append(task_value)
            interval = stratified_bootstrap_lower(
                unit_values_by_subset,
                f"{schedule_sha}:{judge}:{criterion}:v5-signal-utility",
                bootstrap_replicates,
            )
            utility.append(
                {
                    "id": f"{judge}|signal|{criterion}",
                    "judge_id": judge,
                    "criterion": criterion,
                    "assignment_units": 102,
                    "mean_success": sum(unit_values) / 102,
                    "bootstrap": interval,
                    "threshold": 0.75,
                    "passes_utility_gate": operational[judge]["status"] == "PASS" and interval["one_sided_lower_95"] >= 0.75,
                }
            )
            matched.append(
                {
                    "judge_id": judge,
                    "criterion": criterion,
                    "matched_task_units": 102,
                    "null_and_signal_same_prompt_and_chosen": True,
                }
            )
            for subset in ("Factuality", "Focus", "Math", "Precise IF", "Safety", "Ties"):
                clone_subset = [row for row in clone if row["source_subset"] == subset]
                signal_subset = [
                    row for row in coded
                    if row["pair_type"] == "signal_chosen_vs_rejected"
                    and row["criterion"] == criterion
                    and row["source_subset"] == subset
                ]
                if len(clone_subset) != 17 or len(signal_subset) != 34:
                    raise HoldError("HOLD_SUBSET_DESCRIPTIVE_CELL_SIZE")
                subset_descriptive.append({
                    "judge_id": judge,
                    "criterion": criterion,
                    "source_subset": subset,
                    "clone_assignment_units": 17,
                    "clone_false_preference_rate_fail_closed": sum(
                        row["invalid"] or bool(row["false_preference"])
                        for row in clone_subset
                    ) / 17,
                    "signal_assignment_units": 17,
                    "signal_mean_success_fail_closed": sum(
                        float(row["signal_success"] or False) for row in signal_subset
                    ) / 34,
                    "inference": "DESCRIPTIVE_ONLY_NO_SUBSET_SELECTION",
                })
    assignments = assignment_rows_from_coded(coded_by_judge[JUDGES[0]])
    comparison_assignments = assignment_rows_from_coded(coded_by_judge[JUDGES[1]])
    if assignments != comparison_assignments:
        raise HoldError("HOLD_CONFIGURATION_ASSIGNMENT_MISMATCH")
    dc_adjusted = holm(dc)
    signal_ri, signal_secondary_ri = signal_randomization_families(
        coded_by_judge, assignments, schedule_sha, ri_replicates, operational
    )
    clone_ri = clone_randomization_family(
        coded_by_judge, assignments, schedule_sha, ri_replicates, operational
    )
    utility_key = {(row["judge_id"], row["criterion"]): row for row in utility}
    joint = []
    for row in dc_adjusted:
        signal = utility_key[(row["judge_id"], row["criterion"])]
        if operational[row["judge_id"]]["status"] != "PASS":
            status = "HOLD"
        elif not row["reject_after_holm"]:
            status = "FAIL_DC"
        elif signal["passes_utility_gate"]:
            status = "PASS_USEFUL_LOW_DC"
        else:
            status = "PASS_STATISTICAL_BUT_NOT_USEFUL"
        joint.append({"judge_id": row["judge_id"], "criterion": row["criterion"], "status": status})
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": "102 fresh RewardBench 2 items，17 per subset；two named configurations analyzed separately；no V3/V4 pooling",
        "operational_gate": operational,
        "dc_fixed_family_size_4": dc_adjusted,
        "signal_utility_gates": utility,
        "signal_criterion_ri_fixed_family_size_2": signal_ri,
        "signal_order_interaction_ri_fixed_family_size_4": signal_secondary_ri,
        "clone_criterion_ri_fixed_family_size_2": clone_ri,
        "joint_interpretation": joint,
        "matched_design_audit": matched,
        "subset_descriptive": subset_descriptive,
    }


def public_records(coded_by_judge: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    allowed = (
        "judge_id", "call_id", "task_id", "assignment_unit_id", "assignment_sequence_id",
        "assignment_lane", "exposure_period", "treatment", "preceding_treatment", "pair_type",
        "source_subset", "criterion", "order", "canonical_verdict", "valid",
        "invalid", "false_preference", "signal_success", "terminal_status",
    )
    safe_statuses = {
        "OK", "TRANSPORT_ERROR", "HTTP_ERROR", "RESPONSE_JSON_INVALID",
        "RESPONSE_SCHEMA_INVALID", "SERVED_MODEL_MISSING", "SERVED_MODEL_MISMATCH",
        "PARSER_INVALID", "AMBIGUOUS_DISPATCH_INVALID",
    }
    output = []
    for judge in JUDGES:
        for row in coded_by_judge[judge]:
            terminal_status = row.get("terminal_status")
            if terminal_status not in safe_statuses:
                raise HoldError("HOLD_PUBLIC_TERMINAL_STATUS_ENUM")
            output.append({key: row.get(key) for key in allowed})
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--bootstrap-replicates", type=int, default=20000)
    parser.add_argument("--ri-replicates", type=int, default=99999)
    parser.add_argument("--test-mode", action="store_true", help="Permit reduced MC counts for offline tests only")
    args = parser.parse_args()
    if not args.test_mode and (args.bootstrap_replicates != 20000 or args.ri_replicates != 99999):
        raise HoldError("HOLD_FROZEN_REPLICATE_COUNTS")
    manifest, schedule, manifest_sha, digest_file_sha = verify_frozen(args.frozen)
    coded_by_judge = {}
    for run_dir in args.run_dir:
        judge, coded, _ = load_run(
            run_dir,
            schedule,
            manifest_sha,
            digest_file_sha,
            manifest,
            args.frozen,
        )
        if judge in coded_by_judge:
            raise HoldError("HOLD_DUPLICATE_JUDGE_RUN")
        coded_by_judge[judge] = coded
    result = analyze(
        coded_by_judge,
        manifest["schedule_sha256"],
        args.bootstrap_replicates,
        args.ri_replicates,
    )
    args.out.mkdir(parents=True, exist_ok=False)
    result_path = args.out / "analysis_v5.json"
    public_path = args.out / "public_terminal_records_v5.jsonl"
    write_json_new(result_path, result)
    write_jsonl_new(public_path, public_records(coded_by_judge))
    release = {
        "schema_version": "tae-v5-public-release-v1",
        "source_precommit_manifest_sha256": manifest_sha,
        "schedule_sha256": manifest["schedule_sha256"],
        "analysis_sha256": sha256_file(result_path),
        "public_records_sha256": sha256_file(public_path),
        "public_records": 1224,
        "excluded": ["prompts", "candidate text", "raw response", "request payload", "endpoint origin", "hidden reasoning"],
    }
    write_json_new(args.out / "public_release_manifest_v5.json", release)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
