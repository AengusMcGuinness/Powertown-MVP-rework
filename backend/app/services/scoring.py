from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List

from pydantic import BaseModel


@dataclass(frozen=True)
class ScoreResult(BaseModel):
    score: int
    confidence: str
    drivers: List[str] = []


_RULES = [
    (
        "load indicators",
        18,
        [
            r"\bfactory\b",
            r"\bwarehouse\b",
            r"\bmanufactur",
            r"\brefrigerat",
            r"\bcold storage\b",
            r"\bhvac\b",
            r"\bchiller\b",
        ],
    ),
    (
        "electrical infrastructure",
        22,
        [
            r"\btransformer\b",
            r"\bswitchgear\b",
            r"\bsubstation\b",
            r"\bswitchyard\b",
            r"\bthree[- ]phase\b",
        ],
    ),
    ("onsite generation", 14, [r"\bsolar\b", r"\bPV\b", r"\binverter\b"]),
    (
        "siting space",
        18,
        [r"\blot\b", r"\bparking\b", r"\byard\b", r"\bempty space\b", r"\bpaved\b"],
    ),
    (
        "logistics / industrial use",
        12,
        [
            r"\bloading dock\b",
            r"\bforklift\b",
            r"\bdistribution\b",
            r"\btruck\b",
            r"\bcontainer\b",
        ],
    ),
    (
        "contact captured",
        16,
        [
            r"\bfacilities\b",
            r"\bmanager\b",
            r"\bmaintenance\b",
            r"\bbusiness card\b",
            r"\bphone\b",
            r"@",
        ],
    ),
]


def score_building(observation_texts: Iterable[str | None]) -> ScoreResult:
    text = "\n".join([t for t in observation_texts if t]).lower()

    if not text.strip():
        return ScoreResult(
            score=0, confidence="low", drivers=["No observation text yet."]
        )

    raw = 0
    drivers: list[str] = []

    for label, points, patterns in _RULES:
        hit = any(re.search(p, text) for p in patterns)
        if hit:
            raw += points
            drivers.append(f"+{points}: {label}")

    # Cap to 100
    score = min(100, raw)

    # Confidence heuristic: more independent hits => higher confidence
    hits = len(drivers)
    if hits >= 4:
        confidence = "high"
    elif hits >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    # Keep only top drivers (already weighted)
    return ScoreResult(score=score, confidence=confidence, drivers=drivers[:5])
