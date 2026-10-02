"""Mapping domain values and OSCAL relationship enum (spec 5)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Relationship(str, Enum):
    EQUIVALENT_TO = "equivalent-to"
    EQUAL_TO = "equal-to"
    SUBSET_OF = "subset-of"
    SUPERSET_OF = "superset-of"
    INTERSECTS_WITH = "intersects-with"
    NO_RELATIONSHIP = "no-relationship"


POSITIVE_RELATIONSHIPS: tuple[Relationship, ...] = (
    Relationship.EQUIVALENT_TO,
    Relationship.EQUAL_TO,
    Relationship.SUBSET_OF,
    Relationship.SUPERSET_OF,
    Relationship.INTERSECTS_WITH,
)


@dataclass(frozen=True, slots=True)
class CandidatePair:
    run_id: str
    pair_id: str
    req_id: str
    catalog_id: str
    control_id: str
    verify_status: str
    noul_prob: Optional[float] = None


@dataclass(frozen=True, slots=True)
class MappingRecord:
    run_id: str
    req_id: str
    catalog_id: str
    control_id: str
    relation: Relationship
    confidence_percentage: float
    confidence_category: str
