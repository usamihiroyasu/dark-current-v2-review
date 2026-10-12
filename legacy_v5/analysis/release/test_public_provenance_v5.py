#!/usr/bin/env python3
"""Positive and tamper-negative tests for the V5 public hash chain."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path


RELEASE_DIR = Path(__file__).resolve().parent
SOURCE_DIR = RELEASE_DIR.parent
SPEC = importlib.util.spec_from_file_location(
    "verify_and_reanalyze_public_v5",
    RELEASE_DIR / "verify_and_reanalyze_public_v5.py",
)
assert SPEC is not None and SPEC.loader is not None
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class PublicProvenanceTests(unittest.TestCase):
    def make_release_copy(self, root: Path) -> Path:
        release = root / "release"
        release.mkdir()
        for name in (
            "public_provenance_receipt_v5.json",
            "public_schedule_v5.jsonl",
            "public_terminal_records_v5.jsonl",
        ):
            shutil.copy2(RELEASE_DIR / name, release / name)
        return release

    def test_positive_input_hash_chain(self) -> None:
        receipt, records = VERIFY.verify_release_inputs(RELEASE_DIR, SOURCE_DIR)
        self.assertEqual(receipt["status"], "COMPLETE_POST_RUN_HASH_CHAIN")
        self.assertEqual(len(records), 1224)

    def test_terminal_record_byte_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = self.make_release_copy(Path(temporary))
            path = release / "public_terminal_records_v5.jsonl"
            data = path.read_bytes()
            self.assertIn(b'"valid":true', data)
            path.write_bytes(data.replace(b'"valid":true', b'"valid":false', 1))
            with self.assertRaisesRegex(VERIFY.HoldError, "HOLD_PUBLIC_RECORD_HASH"):
                VERIFY.verify_release_inputs(release, SOURCE_DIR)

    def test_schedule_byte_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = self.make_release_copy(Path(temporary))
            path = release / "public_schedule_v5.jsonl"
            data = path.read_bytes()
            self.assertIn(b'"treatment":"S_AB"', data)
            path.write_bytes(data.replace(b'"treatment":"S_AB"', b'"treatment":"N_AB"', 1))
            with self.assertRaisesRegex(VERIFY.HoldError, "HOLD_PUBLIC_SCHEDULE_HASH"):
                VERIFY.verify_release_inputs(release, SOURCE_DIR)

    def test_receipt_run_hash_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = self.make_release_copy(Path(temporary))
            path = release / "public_provenance_receipt_v5.json"
            receipt = json.loads(path.read_text(encoding="utf-8"))
            receipt["run_chain"][0]["run_manifest_sha256"] = "0" * 64
            path.write_text(canonical_json(receipt) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(VERIFY.HoldError, "HOLD_PUBLIC_RECEIPT_HASH"):
                VERIFY.verify_release_inputs(release, SOURCE_DIR)

    def test_frozen_analyzer_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "v5_fresh_items"
            harness = root / "holdout_harness"
            source.mkdir()
            harness.mkdir()
            for name in (
                "analyze_v5.py",
                "reanalyze_public_v5.py",
                "ri_reassign_v5.py",
                "run_v5.py",
            ):
                shutil.copy2(SOURCE_DIR / name, source / name)
            shutil.copy2(SOURCE_DIR.parent / "holdout_harness/harness.py", harness / "harness.py")
            with (source / "analyze_v5.py").open("a", encoding="utf-8") as handle:
                handle.write("\n# tamper\n")
            receipt = VERIFY.verify_receipt(RELEASE_DIR / "public_provenance_receipt_v5.json")
            with self.assertRaisesRegex(VERIFY.HoldError, "HOLD_FROZEN_SOURCE_HASH analyze_v5.py"):
                VERIFY.verify_source_hashes(source, receipt)

    def test_sensitive_field_is_rejected(self) -> None:
        with self.assertRaisesRegex(VERIFY.HoldError, "HOLD_SENSITIVE_KEY"):
            VERIFY.reject_sensitive_strings({"prompt": "not public"})

    def test_semantic_schedule_join_tamper_is_rejected(self) -> None:
        receipt = VERIFY.verify_receipt(RELEASE_DIR / "public_provenance_receipt_v5.json")
        schedule = VERIFY.verify_public_schedule(
            RELEASE_DIR / "public_schedule_v5.jsonl", receipt
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "records.jsonl"
            rows = VERIFY.read_jsonl(RELEASE_DIR / "public_terminal_records_v5.jsonl")
            rows[0]["treatment"] = "N_AB"
            path.write_text("".join(canonical_json(row) + "\n" for row in rows), encoding="utf-8")
            local_receipt = json.loads(canonical_json(receipt))
            local_receipt["public_inputs"]["terminal_records"]["sha256"] = VERIFY.sha256_file(path)
            with self.assertRaisesRegex(VERIFY.HoldError, "HOLD_PUBLIC_RECORD_SCHEDULE_JOIN"):
                VERIFY.verify_public_records(path, local_receipt, schedule)

    @unittest.skipUnless(
        os.environ.get("V5_FULL_REANALYSIS") == "1",
        "set V5_FULL_REANALYSIS=1 for the 99,999-RI integration test",
    )
    def test_full_reanalysis_matches_canonical_hash(self) -> None:
        receipt, records = VERIFY.verify_release_inputs(RELEASE_DIR, SOURCE_DIR)
        result = VERIFY.reproduce(receipt, records, SOURCE_DIR)
        observed = VERIFY.sha256_bytes((canonical_json(result) + "\n").encode("utf-8"))
        self.assertEqual(observed, VERIFY.EXPECTED_CANONICAL_ANALYSIS_SHA256)


if __name__ == "__main__":
    unittest.main(verbosity=2)
