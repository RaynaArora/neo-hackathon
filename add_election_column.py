#!/usr/bin/env python3
"""
Add an election column to issue_relevance_scores.csv based on elections.json.

Usage:
    python add_election_column.py \
        --scores /path/to/issue_relevance_scores.csv \
        --elections /path/to/elections.json \
        [--column-name election]
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, Iterable, Optional


def load_candidacy_to_election_map(elections_path: Path) -> Dict[str, Optional[str]]:
    """Return a mapping of candidacy IDs to their election name."""
    with elections_path.open(encoding="utf-8") as elections_file:
        data = json.load(elections_file)

    mapping: Dict[str, Optional[str]] = {}

    if isinstance(data, dict):
        elections_iter: Iterable = data.values()
    elif isinstance(data, list):
        elections_iter = data
    else:
        raise ValueError("Unexpected elections.json structure; expected dict or list.")

    for election in elections_iter:
        election_name = election.get("name")
        for race in election.get("races", []):
            for candidacy in race.get("candidacies", []):
                candidacy_id = candidacy.get("id")
                if candidacy_id and candidacy_id not in mapping:
                    mapping[candidacy_id] = election_name

    return mapping


def add_election_column(
    scores_path: Path,
    mapping: Dict[str, Optional[str]],
    column_name: str,
    output_path: Optional[Path] = None,
) -> None:
    """Add (or replace) the election column in the issue relevance CSV."""
    if output_path is None:
        output_path = scores_path

    with scores_path.open(encoding="utf-8", newline="") as scores_file:
        reader = csv.DictReader(scores_file)
        if reader.fieldnames is None:
            raise ValueError("issue_relevance_scores.csv is missing a header row.")

        fieldnames = reader.fieldnames.copy()
        if column_name not in fieldnames:
            fieldnames.append(column_name)

        rows = []
        for row in reader:
            candidacy_id = row.get("candidate_id")
            row[column_name] = mapping.get(candidacy_id)
            rows.append(row)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8", newline="") as scores_file:
        writer = csv.DictWriter(scores_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Append an election column to issue_relevance_scores.csv."
    )
    parser.add_argument(
        "--scores",
        type=Path,
        default=Path("issue_relevance_scores.csv"),
        help="Path to issue_relevance_scores.csv (default: ./issue_relevance_scores.csv)",
    )
    parser.add_argument(
        "--elections",
        type=Path,
        default=Path("issue_alignment") / "elections.json",
        help="Path to elections.json (default: ./issue_alignment/elections.json)",
    )
    parser.add_argument(
        "--column-name",
        default="election",
        help='Name of the column to add/replace (default: "election")',
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Path to write the updated CSV (default: overwrite --scores file)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    mapping = load_candidacy_to_election_map(args.elections)
    add_election_column(args.scores, mapping, args.column_name, args.output)


if __name__ == "__main__":
    main()

