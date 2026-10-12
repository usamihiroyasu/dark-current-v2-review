#!/usr/bin/env python3
"""Offline conditional reassignment generator for the V5 blocked design."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

CLONE_SEQUENCES = {"C_NS": ("N", "S"), "C_SN": ("S", "N")}
WILLIAMS = {
    "W1": ("N_AB", "N_BA", "S_BA", "S_AB"),
    "W2": ("N_BA", "S_AB", "N_AB", "S_BA"),
    "W3": ("S_AB", "S_BA", "N_BA", "N_AB"),
    "W4": ("S_BA", "N_AB", "S_AB", "N_BA"),
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class HashRNG:
    def __init__(self, master_seed: bytes, namespace: str):
        if len(master_seed) != 32:
            raise ValueError("seed must contain 32 bytes")
        self.master_seed = master_seed
        self.namespace = namespace.encode("utf-8")
        self.counter = 0

    def randbelow(self, n: int) -> int:
        space = 1 << 256
        limit = space - (space % n)
        while True:
            payload = (
                self.master_seed
                + b"\x00"
                + self.namespace
                + b"\x00"
                + self.counter.to_bytes(16, "big")
            )
            self.counter += 1
            value = int.from_bytes(hashlib.sha256(payload).digest(), "big")
            if value < limit:
                return value % n

    def shuffle(self, values: list[Any]) -> None:
        for index in range(len(values) - 1, 0, -1):
            target = self.randbelow(index + 1)
            values[index], values[target] = values[target], values[index]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def replicate_seed(schedule_sha256: str, replicate_index: int) -> bytes:
    if replicate_index < 1:
        raise ValueError("replicate_index must be >= 1")
    if len(schedule_sha256) != 64:
        raise ValueError("schedule SHA-256 must contain 64 hex characters")
    try:
        bytes.fromhex(schedule_sha256)
    except ValueError as exc:
        raise ValueError("schedule SHA-256 is not hexadecimal") from exc
    payload = f"{schedule_sha256}:ri:{replicate_index}".encode("ascii")
    return hashlib.sha256(payload).digest()


def draw_reassignment(
    assignment_rows: list[dict[str, Any]], schedule_sha256: str, replicate_index: int
) -> list[dict[str, Any]]:
    seed = replicate_seed(schedule_sha256, replicate_index)
    strata: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in assignment_rows:
        lane_value = row.get("lane", row.get("assignment_lane"))
        strata[(row["pair_type"], int(lane_value))].append(row)

    output = []
    for (arm, lane), rows in sorted(strata.items()):
        rows = sorted(rows, key=lambda row: row["assignment_unit_id"])
        expected_size = 17 if arm == "dc_core_clone" else 34
        if len(rows) != expected_size:
            raise ValueError(
                f"RI stratum {arm}/lane-{lane} does not contain {expected_size} units"
            )
        labels = [row["sequence_id"] for row in rows]
        expected_ids = set(CLONE_SEQUENCES if arm == "dc_core_clone" else WILLIAMS)
        if set(labels) != expected_ids:
            raise ValueError(f"RI stratum {arm}/lane-{lane} has invalid sequence IDs")
        realized_quota = Counter(labels)
        rng = HashRNG(seed, f"ri:{replicate_index}:{arm}:lane-{lane}")
        rng.shuffle(labels)
        if Counter(labels) != realized_quota:
            raise AssertionError("RI shuffle changed realized quotas")
        sequence_map = CLONE_SEQUENCES if arm == "dc_core_clone" else WILLIAMS
        for row, label in zip(rows, labels):
            treatments = list(sequence_map[label])
            output.append(
                {
                    "replicate_index": replicate_index,
                    "assignment_unit_id": row["assignment_unit_id"],
                    "pair_type": arm,
                    "lane": lane,
                    "sequence_id": label,
                    "treatments_by_period": treatments,
                    "preceding_treatment_by_period": [None, *treatments[:-1]],
                }
            )
    return sorted(output, key=lambda row: row["assignment_unit_id"])


def main() -> None:
    base = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mechanism",
        type=Path,
        default=base / "frozen/assignment_mechanism_v5.json",
    )
    parser.add_argument(
        "--units", type=Path, default=base / "frozen/assignment_units_v5.jsonl"
    )
    parser.add_argument("--replicate-index", type=int, required=True)
    args = parser.parse_args()

    mechanism = json.loads(args.mechanism.read_text(encoding="utf-8"))
    schedule_sha256 = mechanism["schedule_sha256"]
    rows = draw_reassignment(read_jsonl(args.units), schedule_sha256, args.replicate_index)
    for row in rows:
        print(canonical_json(row))


if __name__ == "__main__":
    main()
