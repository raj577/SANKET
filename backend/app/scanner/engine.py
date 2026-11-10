"""Pandas OI scanner.

The scoring rules here are a faithful port of the original ``oi_scanner.py``.
Do not change the formulas without bumping :data:`SCANNER_VERSION`; every scan
persists the configuration fingerprint used to produce its candidates.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from app.core.exceptions import ScannerError
from app.models.enums import GRADE_ORDER, Direction
from app.scanner.scoring import DEFAULT_CONFIG, ScannerConfig

BASE_COLUMNS = ["Symbol", "Spot"]

LONG_COLUMNS = [
    "ATM_PutOI",
    "PE_ITM1_PutOI",
    "CE_OTM1_CallOI",
    "ATM_CallOI",
    "PE_ITM2_PutOI",
    "PE_ITM3_PutOI",
    "PE_OTM1_PutOI",
    "CE_ITM1_CallOI",
    "CE_ITM2_CallOI",
    "PE_OTM2_PutOI",
]

SHORT_COLUMNS = [
    "ATM_CallOI",
    "CE_ITM1_CallOI",
    "PE_OTM1_PutOI",
    "ATM_PutOI",
    "CE_ITM2_CallOI",
    "CE_ITM3_CallOI",
    "CE_OTM1_CallOI",
    "PE_ITM1_PutOI",
    "PE_ITM2_PutOI",
    "CE_OTM2_CallOI",
]


@dataclass
class Candidate:
    symbol: str
    direction: str
    scan_ltp: float
    score: float
    grade: str
    reason: str
    confirmation_count: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScanResult:
    longs: list[Candidate] = field(default_factory=list)
    shorts: list[Candidate] = field(default_factory=list)
    rows_read: int = 0
    rows_used: int = 0
    rows_skipped: int = 0
    warnings: list[str] = field(default_factory=list)
    config_version: str = ""
    config: dict = field(default_factory=dict)

    @property
    def total_candidates(self) -> int:
        return len(self.longs) + len(self.shorts)

    def summary(self) -> dict:
        return {
            "rows_read": self.rows_read,
            "rows_used": self.rows_used,
            "rows_skipped": self.rows_skipped,
            "long_candidates": len(self.longs),
            "short_candidates": len(self.shorts),
            "warnings": list(self.warnings),
            "scanner_version": self.config_version,
        }


def _prepare(df: pd.DataFrame, required: list[str], side: str) -> tuple[pd.DataFrame | None, str | None]:
    missing = [column for column in BASE_COLUMNS + required if column not in df.columns]
    if missing:
        return None, f"{side}: missing required columns: {', '.join(missing)}"

    columns = list(dict.fromkeys(BASE_COLUMNS + required))
    data = df[columns].copy()
    data["Symbol"] = data["Symbol"].astype(str).str.strip()

    for column in required + ["Spot"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    data = data.replace([np.inf, -np.inf], np.nan)
    data = data.dropna(subset=columns)
    data = data.loc[data["Symbol"].ne("") & data["Symbol"].ne("nan")]
    return data, None


def _filter_min_grade(result: pd.DataFrame, config: ScannerConfig) -> pd.DataFrame:
    minimum = GRADE_ORDER.get(config.min_grade, GRADE_ORDER["C"])
    if minimum <= 0:
        return result
    keep = result["Grade"].map(lambda grade: GRADE_ORDER.get(grade, 0) >= minimum)
    return result.loc[keep]


def _to_candidates(frame: pd.DataFrame, direction: str, score_column: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    for row in frame.itertuples(index=False):
        candidates.append(
            Candidate(
                symbol=str(getattr(row, "Symbol")),
                direction=direction,
                scan_ltp=float(getattr(row, "Spot")),
                score=float(getattr(row, score_column)),
                grade=str(getattr(row, "Grade")),
                reason=str(getattr(row, "Reason")),
                confirmation_count=int(getattr(row, "ConfirmationCount")),
            )
        )
    return candidates


def scan_longs(df: pd.DataFrame, config: ScannerConfig = DEFAULT_CONFIG) -> tuple[list[Candidate], str | None]:
    data, error = _prepare(df, LONG_COLUMNS, Direction.LONG.value)
    if data is None:
        return [], error

    checks = pd.DataFrame(
        {
            "PE_ITM2_PutOI": data["PE_ITM2_PutOI"] > 0,
            "PE_ITM3_PutOI": data["PE_ITM3_PutOI"] > 0,
            "PE_OTM1_PutOI": data["PE_OTM1_PutOI"] > 0,
            "CE_ITM1_CallOI": data["CE_ITM1_CallOI"] <= 0,
            "CE_ITM2_CallOI": data["CE_ITM2_CallOI"] <= 0,
        },
        index=data.index,
    )
    data = data.copy()
    data["ConfirmationCount"] = checks.sum(axis=1)

    qualifies = (
        (data["ATM_PutOI"] > 0)
        & (data["PE_ITM1_PutOI"] > 0)
        & (data["CE_OTM1_CallOI"] < 0)
        & (data["ATM_CallOI"] <= 0)
        & (data["ConfirmationCount"] >= config.confirmation_minimum)
    )
    data = data.loc[qualifies].copy()
    if data.empty:
        return [], None

    data["LongScore"] = (
        data["PE_ITM3_PutOI"] * config.long_pe_itm3
        + data["PE_ITM2_PutOI"] * config.long_pe_itm2
        + data["PE_ITM1_PutOI"] * config.long_pe_itm1
        + data["ATM_PutOI"] * config.long_atm_put
        + data["PE_OTM1_PutOI"].clip(lower=0) * config.long_pe_otm1
        + data["PE_OTM2_PutOI"].clip(lower=0) * config.long_pe_otm2
        + (-data["CE_ITM1_CallOI"].clip(upper=0)) * config.long_ce_itm1
        + (-data["ATM_CallOI"].clip(upper=0)) * config.long_atm_call
        + (-data["CE_OTM1_CallOI"].clip(upper=0)) * config.long_ce_otm1
    )

    dominance = data["ATM_PutOI"] / data["ATM_CallOI"].abs().clip(lower=1)
    rotation = (
        (data["PE_ITM2_PutOI"] > data["PE_ITM3_PutOI"])
        & (data["PE_ITM1_PutOI"] > data["PE_ITM2_PutOI"])
        & (data["ATM_PutOI"] > data["PE_ITM1_PutOI"])
    )

    data["LongScore"] += np.where(
        dominance > config.dominance_strong_ratio,
        config.dominance_strong_points,
        np.where(dominance > config.dominance_medium_ratio, config.dominance_medium_points, 0),
    )
    data["LongScore"] += np.where(rotation, config.rotation_points, 0)

    data["Reason"] = "ATM Put Writing, ITM Put Writing, Call Unwinding"
    data.loc[rotation, "Reason"] += ", Bullish Writer Rotation"
    data.loc[dominance > config.dominance_strong_ratio, "Reason"] += ", Strong ATM Dominance"

    data["Grade"] = data["LongScore"].map(config.grade_for)
    data = data.loc[data["Grade"] != "Ignore"]
    data = _filter_min_grade(data, config)
    data = data.sort_values(["LongScore", "Symbol"], ascending=[False, True]).reset_index(drop=True)
    return _to_candidates(data, Direction.LONG.value, "LongScore"), None


def scan_shorts(df: pd.DataFrame, config: ScannerConfig = DEFAULT_CONFIG) -> tuple[list[Candidate], str | None]:
    data, error = _prepare(df, SHORT_COLUMNS, Direction.SHORT.value)
    if data is None:
        return [], error

    checks = pd.DataFrame(
        {
            "CE_ITM2_CallOI": data["CE_ITM2_CallOI"] > 0,
            "CE_ITM3_CallOI": data["CE_ITM3_CallOI"] > 0,
            "CE_OTM1_CallOI": data["CE_OTM1_CallOI"] > 0,
            "PE_ITM1_PutOI": data["PE_ITM1_PutOI"] <= 0,
            "PE_ITM2_PutOI": data["PE_ITM2_PutOI"] <= 0,
        },
        index=data.index,
    )
    data = data.copy()
    data["ConfirmationCount"] = checks.sum(axis=1)

    qualifies = (
        (data["ATM_CallOI"] > 0)
        & (data["CE_ITM1_CallOI"] > 0)
        & (data["PE_OTM1_PutOI"] < 0)
        & (data["ATM_PutOI"] <= 0)
        & (data["ConfirmationCount"] >= config.confirmation_minimum)
    )
    data = data.loc[qualifies].copy()
    if data.empty:
        return [], None

    data["ShortScore"] = (
        data["CE_ITM3_CallOI"] * config.short_ce_itm3
        + data["CE_ITM2_CallOI"] * config.short_ce_itm2
        + data["CE_ITM1_CallOI"] * config.short_ce_itm1
        + data["ATM_CallOI"] * config.short_atm_call
        + data["CE_OTM1_CallOI"].clip(lower=0) * config.short_ce_otm1
        + data["CE_OTM2_CallOI"].clip(lower=0) * config.short_ce_otm2
        + (-data["PE_ITM1_PutOI"].clip(upper=0)) * config.short_pe_itm1
        + (-data["ATM_PutOI"].clip(upper=0)) * config.short_atm_put
        + (-data["PE_OTM1_PutOI"].clip(upper=0)) * config.short_pe_otm1
    )

    dominance = data["ATM_CallOI"] / data["ATM_PutOI"].abs().clip(lower=1)
    rotation = (
        (data["CE_ITM2_CallOI"] > data["CE_ITM3_CallOI"])
        & (data["CE_ITM1_CallOI"] > data["CE_ITM2_CallOI"])
        & (data["ATM_CallOI"] > data["CE_ITM1_CallOI"])
    )

    data["ShortScore"] += np.where(
        dominance > config.dominance_strong_ratio,
        config.dominance_strong_points,
        np.where(dominance > config.dominance_medium_ratio, config.dominance_medium_points, 0),
    )
    data["ShortScore"] += np.where(rotation, config.rotation_points, 0)

    data["Reason"] = "ATM Call Writing, ITM Call Writing, Put Unwinding"
    data.loc[rotation, "Reason"] += ", Bearish Writer Rotation"
    data.loc[dominance > config.dominance_strong_ratio, "Reason"] += ", Strong ATM Dominance"

    data["Grade"] = data["ShortScore"].map(config.grade_for)
    data = data.loc[data["Grade"] != "Ignore"]
    data = _filter_min_grade(data, config)
    data = data.sort_values(["ShortScore", "Symbol"], ascending=[False, True]).reset_index(drop=True)
    return _to_candidates(data, Direction.SHORT.value, "ShortScore"), None


def scan_dataframe(df: pd.DataFrame, config: ScannerConfig = DEFAULT_CONFIG) -> ScanResult:
    if df is None or df.empty:
        raise ScannerError("CSV contains no rows")

    missing_base = [column for column in BASE_COLUMNS if column not in df.columns]
    if missing_base:
        raise ScannerError(f"CSV is missing required columns: {', '.join(missing_base)}")

    result = ScanResult(
        rows_read=int(len(df)),
        config_version=config.versioned_id(),
        config=config.to_dict(),
    )

    longs: list[Candidate] = []
    shorts: list[Candidate] = []
    if config.long_enabled:
        longs, warning = scan_longs(df, config)
        if warning:
            result.warnings.append(warning)
    if config.short_enabled:
        shorts, warning = scan_shorts(df, config)
        if warning:
            result.warnings.append(warning)

    result.longs = longs
    result.shorts = shorts
    result.rows_used = len(longs) + len(shorts)
    result.rows_skipped = max(result.rows_read - result.rows_used, 0)
    return result


def scan_csv(path: str | Path, config: ScannerConfig = DEFAULT_CONFIG) -> ScanResult:
    try:
        frame = pd.read_csv(path)
    except Exception as exc:  # noqa: BLE001 - surfaced as a typed scanner error
        raise ScannerError(f"Unable to read CSV: {exc}") from exc
    return scan_dataframe(frame, config)
