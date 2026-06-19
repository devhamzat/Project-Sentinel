"""Set-based precision / recall / F1 for entity and relation extraction (§11).

Each field (authors, keywords, datasets/USES, ...) is compared as a SET of
normalised strings against the gold set. We aggregate per field and overall so
Chapter 4 can report per-entity-type numbers and a headline figure, plus a
digital-vs-photographed comparison (same papers, two source kinds).

Pure functions, no I/O — so they are unit-testable offline.
"""

from __future__ import annotations

from dataclasses import dataclass


def _norm(s: str) -> str:
    """Normalise a string for set comparison (case/space-insensitive)."""
    return " ".join(s.lower().split())


def _normset(items: list[str]) -> set[str]:
    return {_norm(x) for x in items if x and x.strip()}


@dataclass
class PRF:
    """Precision, recall, F1 plus the raw counts they came from."""

    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def __add__(self, other: "PRF") -> "PRF":
        return PRF(self.tp + other.tp, self.fp + other.fp, self.fn + other.fn)

    def as_dict(self) -> dict[str, float | int]:
        return {
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
        }


def score_field(predicted: list[str], gold: list[str]) -> PRF:
    """Score one field of one paper as a set comparison."""
    pred, g = _normset(predicted), _normset(gold)
    tp = len(pred & g)
    fp = len(pred - g)
    fn = len(g - pred)
    return PRF(tp, fp, fn)


# Fields we evaluate. USES is the dataset list — the central relation.
EVAL_FIELDS = ["authors", "affiliations", "keywords", "datasets", "methods", "metrics"]


def score_paper(
    predicted: dict[str, list[str]], gold: dict[str, list[str]]
) -> dict[str, PRF]:
    """Score every evaluated field of a single paper."""
    return {
        field: score_field(predicted.get(field, []), gold.get(field, []))
        for field in EVAL_FIELDS
    }


def aggregate(per_paper: list[dict[str, PRF]]) -> dict[str, PRF]:
    """Micro-average across papers: sum tp/fp/fn per field, plus an 'overall'."""
    totals: dict[str, PRF] = {field: PRF(0, 0, 0) for field in EVAL_FIELDS}
    for scores in per_paper:
        for field, prf in scores.items():
            totals[field] = totals[field] + prf
    overall = PRF(0, 0, 0)
    for prf in totals.values():
        overall = overall + prf
    totals["overall"] = overall
    return totals
