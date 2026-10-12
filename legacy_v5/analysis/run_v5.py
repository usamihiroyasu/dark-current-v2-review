#!/usr/bin/env python3
"""Fail-closed executor for the frozen V5 schedule.

This module is intentionally separate from schedule generation.  It performs
one POST per frozen slot, in global order, and never retries.  Tests inject a
mock transport; importing this module does not contact an endpoint.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import shutil
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol


BASE = Path(__file__).resolve().parent
HARNESS_PATH = BASE.parent / "holdout_harness/harness.py"
sys.path.insert(0, str(HARNESS_PATH.parent))

from harness import (  # noqa: E402
    canonical_json,
    parse_winner,
    render_messages,
    sha256_bytes,
    sha256_file,
    sha256_json,
    to_canonical_choice,
)


SCHEMA_VERSION = "tae-v5-run-record-v1"
EXECUTION_CONFIRMATION = "I_UNDERSTAND_V5_IS_NO_RETRY"
ALLOWED_JUDGES = {"qwen25_32b_awq_remote", "qwen36_mlx_local"}
ALLOWED_ANCHOR_TYPES = {
    "signed_git_commit",
    "trusted_timestamp",
    "persistent_thread_message",
}


class HoldError(RuntimeError):
    """A fail-closed condition that prohibits further dispatch."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}{': ' + detail if detail else ''}")


@dataclass(frozen=True)
class HTTPResult:
    status_code: int | None
    body: bytes
    transport_error: str | None = None


class Transport(Protocol):
    def preflight(self, config: dict[str, Any], timeout: int) -> dict[str, Any]: ...

    def post(
        self, url: str, payload: dict[str, Any], timeout: int
    ) -> HTTPResult: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never allow an implicit second POST through redirect handling."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class UrllibTransport:
    """Single-attempt stdlib transport used only after explicit authorization."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(_NoRedirect)

    def _get_json(self, url: str, timeout: int) -> dict[str, Any]:
        request = urllib.request.Request(url, method="GET")
        with self._opener.open(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def preflight(self, config: dict[str, Any], timeout: int) -> dict[str, Any]:
        base_url = config["base_url"].rstrip("/")
        if config.get("api_style", "openai_compatible") == "ollama_native":
            raw = self._get_json(base_url + "/api/tags", timeout)
            model_ids = [
                row.get("name") or row.get("model") for row in raw.get("models", [])
            ]
        else:
            raw = self._get_json(base_url + "/models", timeout)
            model_ids = [row.get("id") for row in raw.get("data", [])]
        return {
            "model_ids": model_ids,
            "configured_backend": config.get("backend"),
            "raw": raw,
        }

    def post(
        self, url: str, payload: dict[str, Any], timeout: int
    ) -> HTTPResult:
        body = canonical_json(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=timeout) as response:
                return HTTPResult(response.status, response.read())
        except urllib.error.HTTPError as exc:
            return HTTPResult(exc.code, exc.read(), f"HTTPError:{exc.code}")
        except Exception as exc:  # one terminal failure; deliberately no retry
            return HTTPResult(None, b"", f"{type(exc).__name__}:{exc}")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise HoldError("HOLD_INVALID_UTC_TIMESTAMP", str(value)) from exc
    if parsed.tzinfo is None:
        raise HoldError("HOLD_NAIVE_UTC_TIMESTAMP", value)
    return parsed.astimezone(timezone.utc)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HoldError("HOLD_INVALID_JSON", str(path)) from exc
    if not isinstance(value, dict):
        raise HoldError("HOLD_JSON_ROOT_NOT_OBJECT", str(path))
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("row is not an object")
                rows.append(row)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HoldError(
            "HOLD_PROVENANCE_MALFORMED_JSONL", f"{path}:{line_number}"
        ) from exc
    return rows


def durable_append(path: Path, value: dict[str, Any]) -> None:
    """Append one canonical record and make it durable before returning."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_json(value) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    parent_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def durable_write_new(path: Path, data: bytes) -> None:
    """Create a file without clobber and fsync its contents and parent."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        raise
    parent_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def atomic_durable_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    with temporary.open("wb") as handle:
        handle.write((canonical_json(value) + "\n").encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    parent_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def endpoint_origin(config: dict[str, Any]) -> str:
    parsed = urllib.parse.urlsplit(config["base_url"])
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HoldError("HOLD_INVALID_ENDPOINT_ORIGIN")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return f"{parsed.scheme}://{parsed.hostname}:{port}"


def build_request(
    config: dict[str, Any], messages: list[dict[str, str]]
) -> tuple[str, dict[str, Any]]:
    base_url = config["base_url"].rstrip("/")
    if config.get("api_style", "openai_compatible") == "ollama_native":
        payload = {
            "model": config["model"],
            "messages": messages,
            "stream": False,
            "think": config["think"],
            "format": config["format_schema"],
            "options": {
                "temperature": config["temperature"],
                "top_p": config["top_p"],
                "seed": config["seed"],
                "num_predict": config["max_tokens"],
            },
        }
        return base_url + "/api/chat", payload
    payload = {
        "model": config["model"],
        "messages": messages,
        "temperature": config["temperature"],
        "top_p": config["top_p"],
        "seed": config["seed"],
        "max_tokens": config["max_tokens"],
        "response_format": config["response_format"],
        "stream": False,
    }
    payload.update(config.get("extra_body", {}))
    return base_url + "/chat/completions", payload


def extract_response(
    config: dict[str, Any], response: dict[str, Any]
) -> tuple[str, dict[str, Any], str | None, str | None]:
    if config.get("api_style", "openai_compatible") == "ollama_native":
        message = response["message"]
        content = message.get("content") or ""
        thinking = message.get("thinking") or ""
        prompt_tokens = int(response.get("prompt_eval_count") or 0)
        completion_tokens = int(response.get("eval_count") or 0)
        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
        return (
            content,
            usage,
            response.get("model"),
            sha256_bytes(thinking.encode("utf-8")) if thinking else None,
        )
    message = response["choices"][0]["message"]
    content = message.get("content") or ""
    thinking = message.get("reasoning") or ""
    return (
        content,
        response.get("usage") or {},
        response.get("model"),
        sha256_bytes(thinking.encode("utf-8")) if thinking else None,
    )


def _relative_to_package_root(frozen_dir: Path, relative: str) -> Path:
    root = frozen_dir.parent.parent.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HoldError("HOLD_MANIFEST_PATH_ESCAPE", relative) from exc
    return candidate


def verify_precommit(frozen_dir: Path) -> tuple[dict[str, Any], str, str]:
    if (frozen_dir / "candidate_manifest_v5.json").is_file():
        raise HoldError("HOLD_CANDIDATE_NOT_EXECUTABLE")
    manifest_path = frozen_dir / "precommit_manifest_v5.json"
    digest_path = frozen_dir / "PRECOMMIT_SHA256.txt"
    manifest = read_json(manifest_path)
    if manifest.get("status") != "PRECOMMITTED_NOT_EXECUTED":
        raise HoldError("HOLD_PRECOMMIT_STATUS")
    if manifest.get("assertions", {}).get("root_go_recorded") is not True:
        raise HoldError("HOLD_ROOT_GO_NOT_RECORDED")
    if manifest.get("assertions", {}).get("candidate_test_seed_used_for_production") is not False:
        raise HoldError("HOLD_PRODUCTION_TEST_SEED_PROHIBITED")
    seed = manifest.get("assignment_randomization", {}).get("production_seed_hex")
    if not isinstance(seed, str) or len(seed) != 64:
        raise HoldError("HOLD_PRODUCTION_SEED_MISSING")
    try:
        bytes.fromhex(seed)
    except ValueError as exc:
        raise HoldError("HOLD_PRODUCTION_SEED_INVALID") from exc
    try:
        tokens = digest_path.read_text(encoding="utf-8").strip().split()
    except OSError as exc:
        raise HoldError("HOLD_PRECOMMIT_DIGEST_MISSING") from exc
    actual_manifest_sha = sha256_file(manifest_path)
    if tokens != [actual_manifest_sha, "precommit_manifest_v5.json"]:
        raise HoldError("HOLD_PRECOMMIT_SHA256_MISMATCH")
    for relative, expected in manifest.get("frozen_file_hashes", {}).items():
        path = (frozen_dir / relative).resolve()
        try:
            path.relative_to(frozen_dir.resolve())
        except ValueError as exc:
            raise HoldError("HOLD_FROZEN_PATH_ESCAPE", relative) from exc
        if not path.is_file() or sha256_file(path) != expected:
            raise HoldError("HOLD_FROZEN_FILE_HASH_MISMATCH", relative)
    source_hashes = manifest.get("package_source_hashes", {})
    harness_key = "holdout_harness/harness.py"
    runner_key = "v5_fresh_items/run_v5.py"
    if harness_key not in source_hashes or runner_key not in source_hashes:
        raise HoldError("HOLD_REQUIRED_SOURCE_HASH_MISSING")
    for relative, expected in source_hashes.items():
        path = _relative_to_package_root(frozen_dir, relative)
        if not path.is_file() or sha256_file(path) != expected:
            raise HoldError("HOLD_PACKAGE_SOURCE_HASH_MISMATCH", relative)
    if sha256_file(HARNESS_PATH) != source_hashes[harness_key]:
        raise HoldError("HOLD_IMPORTED_HARNESS_HASH_MISMATCH")
    return manifest, actual_manifest_sha, sha256_file(digest_path)


def verify_anchor(
    anchor_path: Path,
    manifest_sha: str,
    digest_file_sha: str,
    earliest_intent_utc: str | None,
    now_utc: str,
    manifest_created_at_utc: str,
) -> dict[str, Any]:
    anchor = read_json(anchor_path)
    required = {
        "schema_version",
        "precommit_manifest_sha256",
        "precommit_sha256_file_sha256",
        "anchored_at_utc",
        "anchor_type",
        "anchor_reference",
        "verified_by",
        "verification_status",
    }
    if set(anchor) != required:
        raise HoldError("HOLD_ANCHOR_SCHEMA_FIELDS")
    if anchor["schema_version"] != "tae-v5-precommit-anchor-v1":
        raise HoldError("HOLD_ANCHOR_SCHEMA_VERSION")
    if anchor["precommit_manifest_sha256"] != manifest_sha:
        raise HoldError("HOLD_ANCHOR_MANIFEST_DIGEST_MISMATCH")
    if anchor["precommit_sha256_file_sha256"] != digest_file_sha:
        raise HoldError("HOLD_ANCHOR_DIGEST_FILE_HASH_MISMATCH")
    if anchor["anchor_type"] not in ALLOWED_ANCHOR_TYPES:
        raise HoldError("HOLD_ANCHOR_TYPE")
    if not isinstance(anchor["anchor_reference"], str) or not anchor["anchor_reference"].strip():
        raise HoldError("HOLD_ANCHOR_REFERENCE_EMPTY")
    if not isinstance(anchor["verified_by"], str) or not anchor["verified_by"].strip():
        raise HoldError("HOLD_ANCHOR_VERIFIER_EMPTY")
    if anchor["verification_status"] != "PASS":
        raise HoldError("HOLD_ANCHOR_NOT_VERIFIED")
    anchor_time = parse_utc(anchor["anchored_at_utc"])
    if anchor_time < parse_utc(manifest_created_at_utc):
        raise HoldError("HOLD_NO_EXECUTION_ANCHOR_PREDATES_MANIFEST")
    boundary = parse_utc(earliest_intent_utc or now_utc)
    if anchor_time >= boundary:
        code = "HOLD_PROVENANCE_LATE_ANCHOR" if earliest_intent_utc else "HOLD_NO_EXECUTION_LATE_ANCHOR"
        raise HoldError(code)
    return anchor


def load_and_verify_schedule(path: Path, expected_sha: str) -> list[dict[str, Any]]:
    if sha256_file(path) != expected_sha:
        raise HoldError("HOLD_SCHEDULE_HASH_MISMATCH")
    schedule = read_jsonl(path)
    sequences = [row.get("global_sequence") for row in schedule]
    slots = [row.get("schedule_slot_id") for row in schedule]
    calls = [row.get("call_id") for row in schedule]
    if (
        len(schedule) != 612
        or sequences != list(range(1, 613))
        or len(set(slots)) != 612
        or len(set(calls)) != 612
    ):
        raise HoldError("HOLD_SCHEDULE_NOT_EXACT_612_ORDER")
    return schedule


def verify_run_inputs(
    frozen_dir: Path,
    run_plan_path: Path,
    config_path: Path,
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    run_plan = read_json(run_plan_path)
    config = read_json(config_path)
    judge_id = run_plan.get("judge_id")
    if judge_id not in ALLOWED_JUDGES or "gpt" in str(judge_id).lower():
        raise HoldError("HOLD_GPT_OSS_V5_PLAN_PROHIBITED", str(judge_id))
    if any("gpt" in path.name.lower() for path in frozen_dir.glob("run_plan_*.json")):
        raise HoldError("HOLD_GPT_OSS_V5_PLAN_PRESENT")
    registry = read_json(frozen_dir / "configuration_registry_v5.json")
    included = {row.get("judge_id"): row for row in registry.get("included", [])}
    if set(included) != ALLOWED_JUDGES or judge_id not in included:
        raise HoldError("HOLD_CONFIGURATION_REGISTRY_MISMATCH")
    if config.get("judge_id") != judge_id:
        raise HoldError("HOLD_CONFIG_JUDGE_ID_MISMATCH")
    config_sha = sha256_json(config)
    if config_sha != run_plan.get("judge_config_sha256"):
        raise HoldError("HOLD_JUDGE_CONFIG_HASH_MISMATCH")
    registry_config_sha = included[judge_id].get("judge_config_sha256")
    if registry_config_sha != config_sha:
        raise HoldError("HOLD_CONFIGURATION_REGISTRY_CONFIG_HASH")
    if run_plan.get("schedule_sha256") != manifest.get("schedule_sha256"):
        raise HoldError("HOLD_RUN_PLAN_SCHEDULE_HASH_MISMATCH")
    if run_plan.get("expected_calls") != 612:
        raise HoldError("HOLD_RUN_PLAN_EXPECTED_CALLS")
    if run_plan.get("retry_policy") != "no automatic or manual retry under this run ID":
        raise HoldError("HOLD_RUN_PLAN_RETRY_POLICY")
    analysis_path = frozen_dir.parent / "ANALYSIS_PLAN_FROZEN.md"
    if sha256_file(analysis_path) != run_plan.get("analysis_plan_sha256"):
        raise HoldError("HOLD_ANALYSIS_PLAN_HASH_MISMATCH")
    frozen_hashes = manifest.get("frozen_file_hashes", {})
    relative_plan = run_plan_path.resolve().relative_to(frozen_dir.resolve()).as_posix()
    if frozen_hashes.get(relative_plan) != sha256_file(run_plan_path):
        raise HoldError("HOLD_RUN_PLAN_NOT_FROZEN")
    schedule = load_and_verify_schedule(
        frozen_dir / "schedule_v5.jsonl", run_plan["schedule_sha256"]
    )
    return run_plan, config, schedule


def validate_existing_journals(
    intents: list[dict[str, Any]], terminals: list[dict[str, Any]], run_id: str
) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    if any(row.get("run_id") != run_id for row in [*intents, *terminals]):
        raise HoldError("HOLD_PROVENANCE_RUN_ID_MISMATCH")
    intent_by_seq = {row.get("global_sequence"): row for row in intents}
    terminal_by_seq = {row.get("global_sequence"): row for row in terminals}
    if len(intent_by_seq) != len(intents):
        raise HoldError("HOLD_PROVENANCE_DUPLICATE_INTENT")
    if len(terminal_by_seq) != len(terminals):
        raise HoldError("HOLD_PROVENANCE_DUPLICATE_TERMINAL")
    if [row.get("global_sequence") for row in intents] != list(
        range(1, len(intents) + 1)
    ):
        raise HoldError("HOLD_PROVENANCE_INTENTS_NOT_ORDERED_PREFIX")
    if [row.get("global_sequence") for row in terminals] != list(
        range(1, len(terminals) + 1)
    ):
        raise HoldError("HOLD_PROVENANCE_TERMINALS_NOT_ORDERED_PREFIX")
    if not set(terminal_by_seq).issubset(intent_by_seq):
        raise HoldError("HOLD_PROVENANCE_TERMINAL_WITHOUT_INTENT")
    for sequence, terminal in terminal_by_seq.items():
        if terminal.get("dispatch_intent_sha256") != sha256_json(intent_by_seq[sequence]):
            raise HoldError("HOLD_PROVENANCE_INTENT_TERMINAL_HASH_MISMATCH")
    return intent_by_seq, terminal_by_seq


def schedule_fields(call: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "call_id",
        "source_call_id",
        "schedule_slot_id",
        "global_sequence",
        "temporal_block",
        "microstratum",
        "assignment_unit_id",
        "assignment_sequence_id",
        "pair_id",
        "task_id",
        "pair_type",
        "source_subset",
        "assignment_lane",
        "exposure_period",
        "treatment",
        "preceding_treatment",
        "criterion",
        "order",
    )
    return {key: call.get(key) for key in keys}


def make_ambiguous_terminal(
    intent: dict[str, Any],
    call: dict[str, Any],
    run_context: dict[str, Any],
    raw_response_sha256: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        **run_context,
        **schedule_fields(call),
        "dispatch_intent_utc": intent["dispatch_intent_utc"],
        "dispatch_intent_sha256": sha256_json(intent),
        "response_utc": None,
        "latency_ms": None,
        "terminal_status": "AMBIGUOUS_DISPATCH_INVALID",
        "http_status": None,
        "transport_failure_class": "process_interruption_after_durable_intent",
        "raw_response_sha256": raw_response_sha256,
        "response_model": None,
        "response_content": "",
        "response_content_sha256": sha256_bytes(b""),
        "parse": {
            "parser_version": "winner-json-v1-strict",
            "valid": False,
            "winner": None,
            "error": "ambiguous_dispatch_after_crash",
        },
        "canonical_verdict": None,
        "invalid_reason": "AMBIGUOUS_DISPATCH_INVALID",
        "usage": {},
        "thinking_present": None,
        "thinking_sha256": None,
    }


def validate_raw_for_intent(
    raw: dict[str, Any], intent: dict[str, Any], call: dict[str, Any]
) -> str:
    """Validate and return the exact raw-response digest for one intent."""

    intent_sha = sha256_json(intent)
    if (
        raw.get("global_sequence") != call["global_sequence"]
        or raw.get("call_id") != call["call_id"]
        or raw.get("dispatch_intent_sha256") != intent_sha
    ):
        raise HoldError(
            "HOLD_PROVENANCE_RAW_INTENT_BINDING", str(call["global_sequence"])
        )
    encoded = raw.get("raw_response_base64")
    if not isinstance(encoded, str):
        raise HoldError(
            "HOLD_PROVENANCE_RAW_BYTES_MISSING", str(call["global_sequence"])
        )
    try:
        raw_bytes = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise HoldError(
            "HOLD_PROVENANCE_RAW_BASE64", str(call["global_sequence"])
        ) from exc
    digest = sha256_bytes(raw_bytes)
    if raw.get("raw_response_sha256") != digest:
        raise HoldError(
            "HOLD_PROVENANCE_RAW_BYTES_HASH", str(call["global_sequence"])
        )
    return digest


def summarize(
    run_context: dict[str, Any], terminals: list[dict[str, Any]], state: str
) -> dict[str, Any]:
    invalid = sum(not row.get("parse", {}).get("valid", False) for row in terminals)
    return {
        "schema_version": SCHEMA_VERSION,
        **run_context,
        "completion_state": state,
        "expected_terminal_records": 612,
        "terminal_records": len(terminals),
        "invalid_records": invalid,
        "invalid_rate": invalid / 612,
        "finished_at_utc": utc_now(),
        "retry_count": 0,
    }


def validate_closure_journals(
    *,
    intents: list[dict[str, Any]],
    terminals: list[dict[str, Any]],
    raw_rows: list[dict[str, Any]],
    preflight_rows: list[dict[str, Any]],
    schedule: list[dict[str, Any]],
    config: dict[str, Any],
    run_context: dict[str, Any],
    require_complete: bool,
) -> None:
    """Prove closure can proceed without another endpoint interaction."""

    count = len(terminals)
    if len(intents) != count or count < 1 or count > 612:
        raise HoldError("HOLD_CLOSURE_JOURNAL_COUNT_MISMATCH")
    if require_complete and count != 612:
        raise HoldError("HOLD_CLOSURE_JOURNALS_NOT_COMPLETE")
    expected_sequences = list(range(1, count + 1))
    if [row.get("global_sequence") for row in intents] != expected_sequences:
        raise HoldError("HOLD_CLOSURE_INTENT_ORDER")
    if [row.get("global_sequence") for row in terminals] != expected_sequences:
        raise HoldError("HOLD_CLOSURE_TERMINAL_ORDER")
    if not preflight_rows:
        raise HoldError("HOLD_CLOSURE_PREFLIGHT_MISSING")
    preflight_hashes = {sha256_json(row) for row in preflight_rows}
    raw_by_sequence: dict[int, dict[str, Any]] = {}
    previous_raw_sequence = 0
    for raw in raw_rows:
        sequence = raw.get("global_sequence")
        if not isinstance(sequence, int) or sequence <= previous_raw_sequence:
            raise HoldError("HOLD_CLOSURE_RAW_ORDER_OR_DUPLICATE")
        previous_raw_sequence = sequence
        raw_by_sequence[sequence] = raw

    context_keys = (
        "run_id",
        "judge_id",
        "judge_config_sha256",
        "schedule_sha256",
        "analysis_plan_sha256",
        "precommit_manifest_sha256",
        "anchor_reference_sha256",
        "anchor_snapshot_sha256",
    )
    for index, (intent, terminal, call) in enumerate(
        zip(intents, terminals, schedule), start=1
    ):
        for record_name, record in (("intent", intent), ("terminal", terminal)):
            if any(record.get(key) != run_context[key] for key in context_keys):
                raise HoldError(
                    "HOLD_CLOSURE_CONTEXT_MISMATCH", f"{record_name}:{index}"
                )
            for key, value in schedule_fields(call).items():
                if record.get(key) != value:
                    raise HoldError(
                        "HOLD_CLOSURE_SCHEDULE_MISMATCH",
                        f"{record_name}:{index}:{key}",
                    )
        if intent.get("attempt") != 1 or intent.get("retry_ordinal") != 0:
            raise HoldError("HOLD_CLOSURE_RETRY_DEFECT", str(index))
        if intent.get("preflight_record_sha256") not in preflight_hashes:
            raise HoldError("HOLD_CLOSURE_PREFLIGHT_BINDING", str(index))
        _, payload = build_request(config, render_messages(call))
        if intent.get("request_sha256") != sha256_json(payload):
            raise HoldError("HOLD_CLOSURE_REQUEST_HASH", str(index))
        intent_sha = sha256_json(intent)
        if terminal.get("dispatch_intent_sha256") != intent_sha:
            raise HoldError("HOLD_CLOSURE_INTENT_TERMINAL_HASH", str(index))
        content = terminal.get("response_content")
        if not isinstance(content, str) or terminal.get(
            "response_content_sha256"
        ) != sha256_bytes(content.encode("utf-8")):
            raise HoldError("HOLD_CLOSURE_RESPONSE_CONTENT_HASH", str(index))
        if terminal.get("terminal_status") == "OK" and terminal.get(
            "response_model"
        ) != config["model"]:
            raise HoldError("HOLD_CLOSURE_SERVED_MODEL_MISMATCH", str(index))

        raw_sha = terminal.get("raw_response_sha256")
        raw = raw_by_sequence.get(index)
        if raw_sha is None:
            if raw is not None and terminal.get(
                "terminal_status"
            ) != "AMBIGUOUS_DISPATCH_INVALID":
                raise HoldError("HOLD_CLOSURE_UNEXPECTED_RAW", str(index))
            if raw is not None:
                validate_raw_for_intent(raw, intent, call)
            continue
        if raw is None:
            raise HoldError("HOLD_CLOSURE_RAW_MISSING", str(index))
        if (
            raw.get("call_id") != call["call_id"]
            or raw.get("dispatch_intent_sha256") != intent_sha
            or raw.get("raw_response_sha256") != raw_sha
        ):
            raise HoldError("HOLD_CLOSURE_RAW_TERMINAL_BINDING", str(index))
        encoded = raw.get("raw_response_base64")
        if not isinstance(encoded, str):
            raise HoldError("HOLD_CLOSURE_RAW_BYTES_MISSING", str(index))
        try:
            raw_bytes = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise HoldError("HOLD_CLOSURE_RAW_BASE64", str(index)) from exc
        if sha256_bytes(raw_bytes) != raw_sha:
            raise HoldError("HOLD_CLOSURE_RAW_BYTES_HASH", str(index))

    expected_raw = {
        index
        for index, terminal in enumerate(terminals, start=1)
        if terminal.get("raw_response_sha256") is not None
    }
    optional_ambiguous_raw = {
        index
        for index, terminal in enumerate(terminals, start=1)
        if terminal.get("terminal_status") == "AMBIGUOUS_DISPATCH_INVALID"
    }
    if not expected_raw.issubset(raw_by_sequence) or not set(
        raw_by_sequence
    ).issubset(expected_raw | optional_ambiguous_raw):
        raise HoldError("HOLD_CLOSURE_RAW_SLOT_SET")


def _journal_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"sha256": None, "records": 0, "bytes": 0}
    return {
        "sha256": sha256_file(path),
        "records": len(read_jsonl(path)),
        "bytes": path.stat().st_size,
    }


def finalize_run(
    *,
    run_manifest_path: Path,
    summary_path: Path,
    checksum_path: Path,
    initial_manifest: dict[str, Any],
    run_context: dict[str, Any],
    terminals: list[dict[str, Any]],
    status: str,
    intent_path: Path,
    terminal_path: Path,
    raw_path: Path,
    preflight_path: Path,
    anchor_snapshot_path: Path,
    after_finalize_stage: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Durably close a run, safely resumable between every closure stage."""

    if summary_path.exists():
        result = read_json(summary_path)
        expected_summary = {
            "schema_version": SCHEMA_VERSION,
            **run_context,
            "completion_state": status,
            "expected_terminal_records": 612,
            "terminal_records": len(terminals),
            "invalid_records": sum(
                not row.get("parse", {}).get("valid", False) for row in terminals
            ),
            "invalid_rate": sum(
                not row.get("parse", {}).get("valid", False) for row in terminals
            )
            / 612,
            "retry_count": 0,
        }
        if any(result.get(key) != value for key, value in expected_summary.items()):
            raise HoldError("HOLD_CLOSURE_SUMMARY_MISMATCH")
        parse_utc(result.get("finished_at_utc"))
    else:
        result = summarize(run_context, terminals, status)
        durable_write_new(
            summary_path, (canonical_json(result) + "\n").encode("utf-8")
        )
    if after_finalize_stage is not None:
        after_finalize_stage("summary")

    finished_at = result["finished_at_utc"]
    intent_rows = read_jsonl(intent_path)
    final_manifest = dict(initial_manifest)
    final_manifest.update(
        {
            "status": status,
            "finished_at_utc": finished_at,
            "first_dispatch_intent_utc": (
                intent_rows[0]["dispatch_intent_utc"] if intent_rows else None
            ),
            "last_dispatch_intent_utc": (
                intent_rows[-1]["dispatch_intent_utc"] if intent_rows else None
            ),
            "retry_count": 0,
            "expected_calls": 612,
            "terminal_records": len(terminals),
            "invalid_records": result["invalid_records"],
            "anchor_snapshot_sha256": sha256_file(anchor_snapshot_path),
            "artifacts": {
                "dispatch_intents.jsonl": _journal_metadata(intent_path),
                "terminal_records.jsonl": _journal_metadata(terminal_path),
                "raw_responses_confidential.jsonl": _journal_metadata(raw_path),
                "model_preflight_confidential.jsonl": _journal_metadata(
                    preflight_path
                ),
                "summary.json": {
                    "sha256": sha256_file(summary_path),
                    "bytes": summary_path.stat().st_size,
                },
            },
        }
    )
    existing_manifest = read_json(run_manifest_path)
    existing_status = existing_manifest.get("status")
    if existing_status == "RUNNING":
        atomic_durable_json(run_manifest_path, final_manifest)
    elif existing_status == status:
        if existing_manifest != final_manifest:
            raise HoldError("HOLD_CLOSURE_FINAL_MANIFEST_MISMATCH")
    else:
        raise HoldError("HOLD_CLOSURE_MANIFEST_STATE_MISMATCH")
    if after_finalize_stage is not None:
        after_finalize_stage("manifest")

    checksum_record = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_context["run_id"],
        "run_manifest_sha256": sha256_file(run_manifest_path),
    }
    if checksum_path.exists():
        existing_checksum = read_json(checksum_path)
        if any(
            existing_checksum.get(key) != value
            for key, value in checksum_record.items()
        ):
            raise HoldError("HOLD_CLOSURE_CHECKSUM_MISMATCH")
    else:
        checksum_record["recorded_at_utc"] = utc_now()
        durable_write_new(
            checksum_path,
            (canonical_json(checksum_record) + "\n").encode("utf-8"),
        )
    if after_finalize_stage is not None:
        after_finalize_stage("checksum")
    return result


def execute_v5(
    *,
    frozen_dir: Path,
    run_plan_path: Path,
    config_path: Path,
    run_dir: Path,
    anchor_path: Path,
    authorized: bool,
    resume: bool = False,
    transport: Transport | None = None,
    after_intent_durable: Callable[[dict[str, Any]], None] | None = None,
    after_finalize_stage: Callable[[str], None] | None = None,
    quiet: bool = False,
) -> dict[str, Any]:
    """Execute or resume exactly one frozen configuration with no retry."""

    if not authorized:
        raise HoldError("HOLD_NO_EXECUTION_AUTHORIZATION")
    frozen_dir = frozen_dir.resolve()
    run_plan_path = run_plan_path.resolve()
    config_path = config_path.resolve()
    run_dir = run_dir.resolve()
    anchor_path = anchor_path.resolve()

    manifest, manifest_sha, digest_file_sha = verify_precommit(frozen_dir)
    run_plan, config, schedule = verify_run_inputs(
        frozen_dir, run_plan_path, config_path, manifest
    )
    run_id = run_plan["run_id"]
    if run_dir.name != run_id:
        raise HoldError("HOLD_RUN_DIRECTORY_ID_MISMATCH")

    intent_path = run_dir / "dispatch_intents.jsonl"
    terminal_path = run_dir / "terminal_records.jsonl"
    raw_path = run_dir / "raw_responses_confidential.jsonl"
    run_manifest_path = run_dir / "run_manifest.json"
    summary_path = run_dir / "summary.json"
    manifest_checksum_path = run_dir / "RUN_MANIFEST_SHA256.json"
    preflight_path = run_dir / "model_preflight_confidential.jsonl"
    anchor_snapshot_path = run_dir / "precommit_anchor_snapshot.json"

    if run_dir.exists() and any(run_dir.iterdir()) and not resume:
        raise HoldError("HOLD_RUN_ID_NOT_NEW")
    if resume and not run_manifest_path.exists():
        raise HoldError("HOLD_RESUME_RUN_MANIFEST_MISSING")
    run_dir.mkdir(parents=True, exist_ok=True)

    intents = read_jsonl(intent_path)
    terminals = read_jsonl(terminal_path)
    intent_by_seq, terminal_by_seq = validate_existing_journals(
        intents, terminals, run_id
    )
    earliest_intent = intents[0].get("dispatch_intent_utc") if intents else None
    anchor = verify_anchor(
        anchor_path,
        manifest_sha,
        digest_file_sha,
        earliest_intent,
        utc_now(),
        manifest["created_at_utc"],
    )

    run_context = {
        "run_id": run_id,
        "judge_id": config["judge_id"],
        "judge_config_sha256": sha256_json(config),
        "schedule_sha256": run_plan["schedule_sha256"],
        "analysis_plan_sha256": run_plan["analysis_plan_sha256"],
        "precommit_manifest_sha256": manifest_sha,
        "anchor_reference_sha256": sha256_bytes(
            anchor["anchor_reference"].encode("utf-8")
        ),
        "anchor_snapshot_sha256": sha256_file(anchor_path),
    }

    if resume:
        existing_manifest = read_json(run_manifest_path)
        expected_subset = {
            key: existing_manifest.get(key) for key in run_context
        }
        if expected_subset != run_context:
            raise HoldError("HOLD_PROVENANCE_RUN_MANIFEST_MISMATCH")
        existing_status = existing_manifest.get("status")
        if existing_status not in {"RUNNING", "COMPLETE", "HOLD_PROVENANCE"}:
            raise HoldError("HOLD_CLOSURE_MANIFEST_STATE_MISMATCH")
        if manifest_checksum_path.exists():
            checksum = read_json(manifest_checksum_path)
            if (
                checksum.get("run_id") != run_id
                or checksum.get("run_manifest_sha256")
                != sha256_file(run_manifest_path)
            ):
                raise HoldError("HOLD_CLOSURE_CHECKSUM_MISMATCH")
            if existing_status in {"COMPLETE", "HOLD_PROVENANCE"}:
                raise HoldError("HOLD_NO_CLOBBER_FINALIZED_RUN")
            raise HoldError("HOLD_CLOSURE_CHECKSUM_WITH_RUNNING_MANIFEST")
        initial_manifest = existing_manifest
    else:
        run_manifest = {
            "schema_version": SCHEMA_VERSION,
            **run_context,
            "status": "RUNNING",
            "started_at_utc": utc_now(),
            "retry_policy": "NO_RETRY",
            "retry_count": 0,
            "raw_record_classification": "CONFIDENTIAL_NOT_FOR_PUBLIC_ARTIFACT",
            "endpoint_origin_sha256": sha256_bytes(
                endpoint_origin(config).encode("utf-8")
            ),
            "device_backend_provenance": {
                "runner_hostname": socket.gethostname(),
                "runner_platform": platform.platform(),
                "runner_machine": platform.machine(),
                "python": platform.python_version(),
                "endpoint_hostname": urllib.parse.urlsplit(config["base_url"]).hostname,
                "configured_backend": config.get("backend"),
            },
        }
        durable_write_new(
            run_manifest_path, (canonical_json(run_manifest) + "\n").encode("utf-8")
        )
        initial_manifest = run_manifest
        for source, destination in (
            (run_plan_path, run_dir / "run_plan_snapshot.json"),
            (config_path, run_dir / "judge_config_confidential.json"),
            (frozen_dir / "schedule_v5.jsonl", run_dir / "schedule_snapshot.jsonl"),
            (anchor_path, run_dir / "precommit_anchor_snapshot.json"),
        ):
            durable_write_new(destination, source.read_bytes())

    if not anchor_snapshot_path.is_file() or sha256_file(
        anchor_snapshot_path
    ) != run_context["anchor_snapshot_sha256"]:
        raise HoldError("HOLD_PROVENANCE_ANCHOR_SNAPSHOT_HASH_MISMATCH")

    model_identity_defects = [
        index
        for index, row in enumerate(terminals, start=1)
        if row.get("terminal_status")
        in {"SERVED_MODEL_MISMATCH", "SERVED_MODEL_MISSING"}
    ]
    if model_identity_defects:
        if (
            not resume
            or model_identity_defects != [len(terminals)]
            or len(intents) != len(terminals)
        ):
            raise HoldError("HOLD_PROVENANCE_PRIOR_MODEL_IDENTITY_DEFECT")
        raw_rows = read_jsonl(raw_path)
        preflight_rows = read_jsonl(preflight_path)
        validate_closure_journals(
            intents=intents,
            terminals=terminals,
            raw_rows=raw_rows,
            preflight_rows=preflight_rows,
            schedule=schedule,
            config=config,
            run_context=run_context,
            require_complete=False,
        )
        if initial_manifest.get("status") not in {"RUNNING", "HOLD_PROVENANCE"}:
            raise HoldError("HOLD_CLOSURE_MANIFEST_STATUS_CONTRADICTION")
        return finalize_run(
            run_manifest_path=run_manifest_path,
            summary_path=summary_path,
            checksum_path=manifest_checksum_path,
            initial_manifest=initial_manifest,
            run_context=run_context,
            terminals=terminals,
            status="HOLD_PROVENANCE",
            intent_path=intent_path,
            terminal_path=terminal_path,
            raw_path=raw_path,
            preflight_path=preflight_path,
            anchor_snapshot_path=anchor_snapshot_path,
            after_finalize_stage=after_finalize_stage,
        )

    # Any durable intent without a terminal is irreversibly ambiguous.  Record
    # it invalid before considering a later never-attempted slot.
    raw_rows_before_resume = read_jsonl(raw_path) if resume else []
    raw_by_sequence_before_resume = {
        row.get("global_sequence"): row for row in raw_rows_before_resume
    }
    if len(raw_by_sequence_before_resume) != len(raw_rows_before_resume):
        raise HoldError("HOLD_PROVENANCE_RAW_ORDER_OR_DUPLICATE")
    for sequence in sorted(set(intent_by_seq) - set(terminal_by_seq)):
        call = schedule[sequence - 1]
        raw = raw_by_sequence_before_resume.get(sequence)
        raw_sha = (
            validate_raw_for_intent(raw, intent_by_seq[sequence], call)
            if raw is not None
            else None
        )
        terminal = make_ambiguous_terminal(
            intent_by_seq[sequence], call, run_context, raw_sha
        )
        durable_append(terminal_path, terminal)
        terminals.append(terminal)
        terminal_by_seq[sequence] = terminal

    if sorted(terminal_by_seq) != list(range(1, len(terminal_by_seq) + 1)):
        raise HoldError("HOLD_PROVENANCE_TERMINALS_NOT_ORDERED_PREFIX")

    # A complete journal set enters closure-only recovery.  It is forbidden to
    # preflight or dispatch again, even when summary/manifest/checksum creation
    # was interrupted previously.
    if resume and len(intents) == len(terminals) == 612:
        raw_rows = read_jsonl(raw_path)
        preflight_rows = read_jsonl(preflight_path)
        validate_closure_journals(
            intents=intents,
            terminals=terminals,
            raw_rows=raw_rows,
            preflight_rows=preflight_rows,
            schedule=schedule,
            config=config,
            run_context=run_context,
            require_complete=True,
        )
        closure_status = (
            "HOLD_PROVENANCE"
            if any(
                row.get("terminal_status")
                in {"SERVED_MODEL_MISMATCH", "SERVED_MODEL_MISSING"}
                for row in terminals
            )
            else "COMPLETE"
        )
        if initial_manifest.get("status") not in {"RUNNING", closure_status}:
            raise HoldError("HOLD_CLOSURE_MANIFEST_STATUS_CONTRADICTION")
        return finalize_run(
            run_manifest_path=run_manifest_path,
            summary_path=summary_path,
            checksum_path=manifest_checksum_path,
            initial_manifest=initial_manifest,
            run_context=run_context,
            terminals=terminals,
            status=closure_status,
            intent_path=intent_path,
            terminal_path=terminal_path,
            raw_path=raw_path,
            preflight_path=preflight_path,
            anchor_snapshot_path=anchor_snapshot_path,
            after_finalize_stage=after_finalize_stage,
        )

    active_transport = transport or UrllibTransport()
    timeout = int(config["timeout_seconds"])
    try:
        preflight = active_transport.preflight(config, timeout)
    except Exception as exc:
        raise HoldError("HOLD_NO_EXECUTION_PREFLIGHT_FAILED", type(exc).__name__) from exc
    model_ids = preflight.get("model_ids")
    if not isinstance(model_ids, list) or config["model"] not in model_ids:
        raise HoldError("HOLD_NO_EXECUTION_MODEL_ID_MISMATCH", repr(model_ids))
    preflight_record = {
        "schema_version": SCHEMA_VERSION,
        **run_context,
        "checked_at_utc": utc_now(),
        "configured_model": config["model"],
        "served_model_ids": model_ids,
        "configured_backend": config.get("backend"),
        "preflight_raw": preflight.get("raw"),
    }
    durable_append(preflight_path, preflight_record)
    preflight_sha = sha256_json(preflight_record)

    for call in schedule:
        sequence = call["global_sequence"]
        if sequence in terminal_by_seq:
            continue
        if sequence != len(intent_by_seq) + 1:
            raise HoldError("HOLD_PROVENANCE_NEXT_SLOT_NOT_GLOBAL_ORDER")

        messages = render_messages(call)
        request_url, payload = build_request(config, messages)
        intent_utc = utc_now()
        if parse_utc(anchor["anchored_at_utc"]) >= parse_utc(intent_utc):
            raise HoldError("HOLD_NO_EXECUTION_LATE_ANCHOR")
        intent = {
            "schema_version": SCHEMA_VERSION,
            **run_context,
            **schedule_fields(call),
            "dispatch_intent_utc": intent_utc,
            "request_sha256": sha256_json(payload),
            "preflight_record_sha256": preflight_sha,
            "attempt": 1,
            "retry_ordinal": 0,
        }
        durable_append(intent_path, intent)
        intent_by_seq[sequence] = intent
        if after_intent_durable is not None:
            after_intent_durable(intent)

        start = time.monotonic_ns()
        result = active_transport.post(request_url, payload, timeout)
        latency_ms = (time.monotonic_ns() - start) / 1_000_000
        response_utc = utc_now()

        response: dict[str, Any] | None = None
        response_json_error: str | None = None
        if result.body:
            try:
                decoded = json.loads(result.body.decode("utf-8"))
                if not isinstance(decoded, dict):
                    raise ValueError("root_not_object")
                response = decoded
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                response_json_error = f"{type(exc).__name__}:{exc}"

        content = ""
        usage: dict[str, Any] = {}
        response_model: str | None = None
        thinking_sha: str | None = None
        extract_error: str | None = None
        if response is not None and result.status_code == 200:
            try:
                content, usage, response_model, thinking_sha = extract_response(
                    config, response
                )
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                extract_error = f"{type(exc).__name__}:{exc}"

        if result.transport_error is not None:
            terminal_status = "TRANSPORT_ERROR"
            invalid_reason = result.transport_error
        elif result.status_code != 200:
            terminal_status = "HTTP_ERROR"
            invalid_reason = f"http_status:{result.status_code}"
        elif response_json_error is not None:
            terminal_status = "RESPONSE_JSON_INVALID"
            invalid_reason = response_json_error
        elif extract_error is not None:
            terminal_status = "RESPONSE_SCHEMA_INVALID"
            invalid_reason = extract_error
        elif response_model is None:
            terminal_status = "SERVED_MODEL_MISSING"
            invalid_reason = "response_model_missing"
        elif response_model != config["model"]:
            terminal_status = "SERVED_MODEL_MISMATCH"
            invalid_reason = f"configured={config['model']};served={response_model}"
        else:
            terminal_status = "PENDING_PARSE"
            invalid_reason = None

        parsed = (
            parse_winner(content)
            if terminal_status == "PENDING_PARSE"
            else {
                "parser_version": "winner-json-v1-strict",
                "valid": False,
                "winner": None,
                "error": invalid_reason,
            }
        )
        if terminal_status == "PENDING_PARSE":
            if parsed["valid"]:
                terminal_status = "OK"
            else:
                terminal_status = "PARSER_INVALID"
                invalid_reason = parsed["error"]

        raw_record = {
            "schema_version": SCHEMA_VERSION,
            "classification": "CONFIDENTIAL_NOT_FOR_PUBLIC_ARTIFACT",
            **run_context,
            "call_id": call["call_id"],
            "global_sequence": sequence,
            "dispatch_intent_sha256": sha256_json(intent),
            "request_url": request_url,
            "request": payload,
            "http_status": result.status_code,
            "transport_error": result.transport_error,
            "raw_response_utf8": result.body.decode("utf-8", errors="replace"),
            "raw_response_base64": base64.b64encode(result.body).decode("ascii"),
            "raw_response_sha256": sha256_bytes(result.body),
            "response_utc": response_utc,
        }
        durable_append(raw_path, raw_record)

        terminal = {
            "schema_version": SCHEMA_VERSION,
            **run_context,
            **schedule_fields(call),
            "dispatch_intent_utc": intent_utc,
            "dispatch_intent_sha256": sha256_json(intent),
            "response_utc": response_utc,
            "latency_ms": latency_ms,
            "terminal_status": terminal_status,
            "http_status": result.status_code,
            "transport_failure_class": result.transport_error,
            "raw_response_sha256": raw_record["raw_response_sha256"],
            "response_model": response_model,
            "response_content": content,
            "response_content_sha256": sha256_bytes(content.encode("utf-8")),
            "parse": parsed,
            "canonical_verdict": to_canonical_choice(call, parsed["winner"]),
            "invalid_reason": invalid_reason,
            "usage": usage,
            "thinking_present": thinking_sha is not None,
            "thinking_sha256": thinking_sha,
        }
        durable_append(terminal_path, terminal)
        terminals.append(terminal)
        terminal_by_seq[sequence] = terminal

        if not quiet:
            print(
                f"[{sequence}/612] {call['call_id']} {terminal_status}",
                flush=True,
            )
        if terminal_status in {"SERVED_MODEL_MISMATCH", "SERVED_MODEL_MISSING"}:
            return finalize_run(
                run_manifest_path=run_manifest_path,
                summary_path=summary_path,
                checksum_path=manifest_checksum_path,
                initial_manifest=initial_manifest,
                run_context=run_context,
                terminals=terminals,
                status="HOLD_PROVENANCE",
                intent_path=intent_path,
                terminal_path=terminal_path,
                raw_path=raw_path,
                preflight_path=preflight_path,
                anchor_snapshot_path=anchor_snapshot_path,
                after_finalize_stage=after_finalize_stage,
            )

    state = "COMPLETE" if len(terminals) == 612 else "HOLD_PARTIAL"
    return finalize_run(
        run_manifest_path=run_manifest_path,
        summary_path=summary_path,
        checksum_path=manifest_checksum_path,
        initial_manifest=initial_manifest,
        run_context=run_context,
        terminals=terminals,
        status=state,
        intent_path=intent_path,
        terminal_path=terminal_path,
        raw_path=raw_path,
        preflight_path=preflight_path,
        anchor_snapshot_path=anchor_snapshot_path,
        after_finalize_stage=after_finalize_stage,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frozen-dir", type=Path, default=BASE / "frozen")
    parser.add_argument("--run-plan", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--anchor", type=Path, default=BASE / "audit/precommit_anchor_v5.json"
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--execute-confirmation", required=True)
    args = parser.parse_args()
    if args.execute_confirmation != EXECUTION_CONFIRMATION:
        raise SystemExit("HOLD_NO_EXECUTION_AUTHORIZATION")
    try:
        result = execute_v5(
            frozen_dir=args.frozen_dir,
            run_plan_path=args.run_plan,
            config_path=args.config,
            run_dir=args.run_dir,
            anchor_path=args.anchor,
            authorized=True,
            resume=args.resume,
            quiet=args.quiet,
        )
    except HoldError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["completion_state"] != "COMPLETE":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
