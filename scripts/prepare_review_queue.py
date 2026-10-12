"""Create a blocker-ranked, label-free human review queue."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.dataset.review_queue import blocker_ranked_review_queue
from src.storage.jsonl import iter_jsonl, write_jsonl_atomic


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label-audit", type=Path, required=True)
    parser.add_argument("--history-audit", type=Path, required=True)
    parser.add_argument("--event-reviews", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    for path in (args.label_audit, args.history_audit, args.event_reviews):
        if not path.is_file():
            parser.error(f"missing input: {path}")
    reviews = list(iter_jsonl(args.event_reviews))
    reviewed = {row["sample_id"] for row in reviews
                if row.get("decision") in {"architecture_refactor", "non_architectural"}}
    queue = blocker_ranked_review_queue(
        iter_jsonl(args.label_audit), iter_jsonl(args.history_audit), reviewed,
    )
    write_jsonl_atomic(args.output, iter(queue))
    print(f"Pending diff reviews: {len(queue)}")
    print(f"Potential labels unlocked by top review: {queue[0]['blocked_label_count'] if queue else 0}")
    print(f"Review queue: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
