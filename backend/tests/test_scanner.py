"""The ported scanner must keep the original formulas and thresholds."""
from __future__ import annotations

from app.scanner.engine import scan_csv
from app.scanner.scoring import DEFAULT_CONFIG

from .conftest import SAMPLE_CSV


def test_sample_scan_matches_original_counts():
    result = scan_csv(SAMPLE_CSV)
    assert result.rows_read == 213
    assert len(result.longs) == 8
    assert len(result.shorts) == 7
    assert result.warnings == []


def test_long_candidate_formula_and_reason():
    result = scan_csv(SAMPLE_CSV)
    wipro = next(c for c in result.longs if c.symbol == "WIPRO")
    assert wipro.direction == "LONG"
    assert wipro.grade in {"A+", "A", "B+", "B", "C"}
    assert wipro.score >= 400
    assert wipro.confirmation_count >= DEFAULT_CONFIG.confirmation_minimum
    assert "ATM Put Writing" in wipro.reason
    assert any(
        fragment in wipro.reason
        for fragment in ("Bullish Writer Rotation", "Strong ATM Dominance")
    )


def test_short_candidate_formula_and_reason():
    result = scan_csv(SAMPLE_CSV)
    swiggy = next(c for c in result.shorts if c.symbol == "SWIGGY")
    assert swiggy.direction == "SHORT"
    assert swiggy.score >= 400
    assert swiggy.confirmation_count >= DEFAULT_CONFIG.confirmation_minimum
    assert "ATM Call Writing" in swiggy.reason
