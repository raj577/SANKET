#!/usr/bin/env python3
"""
Sensibull OI institutional-style LONG/SHORT scanner.

Usage:
    pip install pandas numpy
    python oi_scanner.py
    python oi_scanner.py --input sensibull_oi_scan.csv

Outputs:
    long_candidates.csv
    short_candidates.csv

OI inputs are treated as signed changes in open interest, as supplied by the CSV.
This is a rule-based scan, not proof of institutional activity or a trade signal.
"""
import argparse
import numpy as np
import pandas as pd

LONG_COLUMNS = [
    "ATM_PutOI", "PE_ITM1_PutOI", "CE_OTM1_CallOI", "ATM_CallOI",
    "PE_ITM2_PutOI", "PE_ITM3_PutOI", "PE_OTM1_PutOI",
    "CE_ITM1_CallOI", "CE_ITM2_CallOI", "PE_OTM2_PutOI",
]
SHORT_COLUMNS = [
    "ATM_CallOI", "CE_ITM1_CallOI", "PE_OTM1_PutOI", "ATM_PutOI",
    "CE_ITM2_CallOI", "CE_ITM3_CallOI", "CE_OTM1_CallOI",
    "PE_ITM1_PutOI", "PE_ITM2_PutOI", "CE_OTM2_CallOI",
]
BASE_COLUMNS = ["Symbol", "Spot"]


def get_grade(score):
    if score >= 2000:
        return "A+"
    if score >= 1500:
        return "A"
    if score >= 1000:
        return "B+"
    if score >= 700:
        return "B"
    if score >= 400:
        return "C"
    return "Ignore"


def validate_columns(df, required, side):
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(
            f"{side}: CSV is missing required columns: {', '.join(missing)}"
        )


def prepare_data(df, required, side):
    validate_columns(df, BASE_COLUMNS + required, side)
    columns = list(dict.fromkeys(BASE_COLUMNS + required))
    data = df[columns].copy()

    # Convert malformed values to NaN; incomplete rows are excluded.
    for column in required + ["Spot"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    data = data.dropna(subset=columns)
    finite = np.isfinite(data["Spot"])
    for column in required:
        finite &= np.isfinite(data[column])
    return data.loc[finite].copy()


def apply_grade_and_sort(data, score_column, output_columns):
    data["Grade"] = data[score_column].map(get_grade)
    data = data.loc[data["Grade"] != "Ignore", output_columns]
    return data.sort_values(score_column, ascending=False).reset_index(drop=True)


def scan_longs(df):
    x = prepare_data(df, LONG_COLUMNS, "LONG")

    confirmation_checks = pd.DataFrame({
        "PE_ITM2_PutOI": x["PE_ITM2_PutOI"] > 0,
        "PE_ITM3_PutOI": x["PE_ITM3_PutOI"] > 0,
        "PE_OTM1_PutOI": x["PE_OTM1_PutOI"] > 0,
        "CE_ITM1_CallOI": x["CE_ITM1_CallOI"] <= 0,
        "CE_ITM2_CallOI": x["CE_ITM2_CallOI"] <= 0,
    }, index=x.index)
    x["ConfirmationCount"] = confirmation_checks.sum(axis=1)

    qualifies = (
        (x["ATM_PutOI"] > 0)
        & (x["PE_ITM1_PutOI"] > 0)
        & (x["CE_OTM1_CallOI"] < 0)
        & (x["ATM_CallOI"] <= 0)
        & (x["ConfirmationCount"] >= 2)
    )
    x = x.loc[qualifies].copy()

    x["LongScore"] = (
        x["PE_ITM3_PutOI"]
        + x["PE_ITM2_PutOI"] * 2
        + x["PE_ITM1_PutOI"] * 3
        + x["ATM_PutOI"] * 4
        + x["PE_OTM1_PutOI"].clip(lower=0) * 2
        + x["PE_OTM2_PutOI"].clip(lower=0)
        + (-x["CE_ITM1_CallOI"].clip(upper=0)) * 2
        + (-x["ATM_CallOI"].clip(upper=0)) * 3
        + (-x["CE_OTM1_CallOI"].clip(upper=0)) * 4
    )

    x["ATM_Dominance_Bull"] = (
        x["ATM_PutOI"] / x["ATM_CallOI"].abs().clip(lower=1)
    )
    rotation = (
        (x["PE_ITM2_PutOI"] > x["PE_ITM3_PutOI"])
        & (x["PE_ITM1_PutOI"] > x["PE_ITM2_PutOI"])
        & (x["ATM_PutOI"] > x["PE_ITM1_PutOI"])
    )

    x["LongScore"] += np.where(
        x["ATM_Dominance_Bull"] > 2, 20,
        np.where(x["ATM_Dominance_Bull"] > 1.5, 10, 0)
    )
    x["LongScore"] += np.where(rotation, 15, 0)

    x["Reason"] = "ATM Put Writing, ITM Put Writing, Call Unwinding"
    x.loc[rotation, "Reason"] += ", Bullish Writer Rotation"
    x.loc[x["ATM_Dominance_Bull"] > 2, "Reason"] += ", Strong ATM Dominance"
    return apply_grade_and_sort(
        x, "LongScore", ["Symbol", "Spot", "LongScore", "Grade", "Reason"]
    )


def scan_shorts(df):
    x = prepare_data(df, SHORT_COLUMNS, "SHORT")

    confirmation_checks = pd.DataFrame({
        "CE_ITM2_CallOI": x["CE_ITM2_CallOI"] > 0,
        "CE_ITM3_CallOI": x["CE_ITM3_CallOI"] > 0,
        "CE_OTM1_CallOI": x["CE_OTM1_CallOI"] > 0,
        "PE_ITM1_PutOI": x["PE_ITM1_PutOI"] <= 0,
        "PE_ITM2_PutOI": x["PE_ITM2_PutOI"] <= 0,
    }, index=x.index)
    x["ConfirmationCount"] = confirmation_checks.sum(axis=1)

    qualifies = (
        (x["ATM_CallOI"] > 0)
        & (x["CE_ITM1_CallOI"] > 0)
        & (x["PE_OTM1_PutOI"] < 0)
        & (x["ATM_PutOI"] <= 0)
        & (x["ConfirmationCount"] >= 2)
    )
    x = x.loc[qualifies].copy()

    x["ShortScore"] = (
        x["CE_ITM3_CallOI"]
        + x["CE_ITM2_CallOI"] * 2
        + x["CE_ITM1_CallOI"] * 3
        + x["ATM_CallOI"] * 4
        + x["CE_OTM1_CallOI"].clip(lower=0) * 2
        + x["CE_OTM2_CallOI"].clip(lower=0)
        + (-x["PE_ITM1_PutOI"].clip(upper=0)) * 2
        + (-x["ATM_PutOI"].clip(upper=0)) * 3
        + (-x["PE_OTM1_PutOI"].clip(upper=0)) * 4
    )

    x["ATM_Dominance_Bear"] = (
        x["ATM_CallOI"] / x["ATM_PutOI"].abs().clip(lower=1)
    )
    rotation = (
        (x["CE_ITM2_CallOI"] > x["CE_ITM3_CallOI"])
        & (x["CE_ITM1_CallOI"] > x["CE_ITM2_CallOI"])
        & (x["ATM_CallOI"] > x["CE_ITM1_CallOI"])
    )

    x["ShortScore"] += np.where(
        x["ATM_Dominance_Bear"] > 2, 20,
        np.where(x["ATM_Dominance_Bear"] > 1.5, 10, 0)
    )
    x["ShortScore"] += np.where(rotation, 15, 0)

    x["Reason"] = "ATM Call Writing, ITM Call Writing, Put Unwinding"
    x.loc[rotation, "Reason"] += ", Bearish Writer Rotation"
    x.loc[x["ATM_Dominance_Bear"] > 2, "Reason"] += ", Strong ATM Dominance"
    return apply_grade_and_sort(
        x, "ShortScore", ["Symbol", "Spot", "ShortScore", "Grade", "Reason"]
    )


def main():
    parser = argparse.ArgumentParser(description="Sensibull OI LONG/SHORT scanner")
    parser.add_argument("--input", default="sensibull_oi_scan.csv",
                        help="Input CSV path (default: sensibull_oi_scan.csv)")
    parser.add_argument("--long-output", default="long_candidates.csv")
    parser.add_argument("--short-output", default="short_candidates.csv")
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    # Handle missing columns per direction: report the issue and still create
    # the corresponding empty output file instead of terminating the scanner.
    try:
        longs = scan_longs(df)
    except ValueError as exc:
        print(f"\nWARNING: {exc}")
        longs = pd.DataFrame(columns=["Symbol", "Spot", "LongScore", "Grade", "Reason"])

    try:
        shorts = scan_shorts(df)
    except ValueError as exc:
        print(f"\nWARNING: {exc}")
        shorts = pd.DataFrame(columns=["Symbol", "Spot", "ShortScore", "Grade", "Reason"])

    longs.to_csv(args.long_output, index=False)
    shorts.to_csv(args.short_output, index=False)

    print("\nTOP 20 LONGS")
    print(longs.head(20).to_string(index=False) if not longs.empty else "No LONG candidates.")
    print("\nTOP 20 SHORTS")
    print(shorts.head(20).to_string(index=False) if not shorts.empty else "No SHORT candidates.")
    print(f"\nSaved {len(longs)} LONG candidates to: {args.long_output}")
    print(f"Saved {len(shorts)} SHORT candidates to: {args.short_output}")


if __name__ == "__main__":
    main()
