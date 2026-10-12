#!/usr/bin/env python3
"""Reproduce V5 primary gates from the public-safe per-call release."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import analyze_v5 as av


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--bootstrap-replicates", type=int, default=20000)
    parser.add_argument("--ri-replicates", type=int, default=99999)
    parser.add_argument("--test-mode", action="store_true")
    args = parser.parse_args()
    if not args.test_mode and (args.bootstrap_replicates != 20000 or args.ri_replicates != 99999):
        raise av.HoldError("HOLD_FROZEN_REPLICATE_COUNTS")
    manifest = av.read_json(args.release_dir / "public_release_manifest_v5.json")
    records_path = args.release_dir / "public_terminal_records_v5.jsonl"
    if av.sha256_file(records_path) != manifest.get("public_records_sha256"):
        raise av.HoldError("HOLD_PUBLIC_RECORD_HASH")
    rows = av.read_jsonl(records_path)
    if len(rows) != 1224 or Counter(row.get("judge_id") for row in rows) != Counter({judge: 612 for judge in av.JUDGES}):
        raise av.HoldError("HOLD_PUBLIC_RECORD_SHAPE")
    coded = {judge: [row for row in rows if row["judge_id"] == judge] for judge in av.JUDGES}
    result = av.analyze(
        coded,
        manifest["schedule_sha256"],
        args.bootstrap_replicates,
        args.ri_replicates,
    )
    result["public_reanalysis"] = {
        "source_public_records_sha256": manifest["public_records_sha256"],
        "confidential_fields_required": False,
    }
    av.write_json_new(args.out, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
