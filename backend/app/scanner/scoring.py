"""Versioned scanner configuration.

The formulas themselves live in :mod:`app.scanner.engine`. This module only
carries the weights and thresholds so that every scan can persist the exact
configuration it ran with.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace

SCANNER_VERSION = "1.0.0"


@dataclass(frozen=True)
class ScannerConfig:
    version: str = SCANNER_VERSION
    min_grade: str = "C"
    long_enabled: bool = True
    short_enabled: bool = True
    confirmation_minimum: int = 2

    # ATM dominance bonus thresholds
    dominance_strong_ratio: float = 2.0
    dominance_strong_points: float = 20.0
    dominance_medium_ratio: float = 1.5
    dominance_medium_points: float = 10.0
    rotation_points: float = 15.0

    # LONG score weights
    long_pe_itm3: float = 1.0
    long_pe_itm2: float = 2.0
    long_pe_itm1: float = 3.0
    long_atm_put: float = 4.0
    long_pe_otm1: float = 2.0
    long_pe_otm2: float = 1.0
    long_ce_itm1: float = 2.0
    long_atm_call: float = 3.0
    long_ce_otm1: float = 4.0

    # SHORT score weights
    short_ce_itm3: float = 1.0
    short_ce_itm2: float = 2.0
    short_ce_itm1: float = 3.0
    short_atm_call: float = 4.0
    short_ce_otm1: float = 2.0
    short_ce_otm2: float = 1.0
    short_pe_itm1: float = 2.0
    short_atm_put: float = 3.0
    short_pe_otm1: float = 4.0

    # Grade thresholds, highest first. "Ignore" is everything below the last.
    grade_thresholds: tuple[tuple[str, float], ...] = field(
        default=(
            ("A+", 2000.0),
            ("A", 1500.0),
            ("B+", 1000.0),
            ("B", 700.0),
            ("C", 400.0),
        )
    )

    def with_overrides(self, **changes) -> "ScannerConfig":
        return replace(self, **changes)

    def to_dict(self) -> dict:
        data = {
            key: value for key, value in self.__dict__.items()
        }
        data["grade_thresholds"] = [list(item) for item in self.grade_thresholds]
        return data

    def fingerprint(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def versioned_id(self) -> str:
        return f"{self.version}+{self.fingerprint()[:12]}"

    def grade_for(self, score: float) -> str:
        for grade, threshold in self.grade_thresholds:
            if score >= threshold:
                return grade
        return "Ignore"


DEFAULT_CONFIG = ScannerConfig()
