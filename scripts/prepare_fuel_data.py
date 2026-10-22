"""Prepare the company fuel-price CSV for import into the planner.

The source CSV is treated as immutable. This script copies it to the
canonical raw-data location only when that location does not already exist,
then refuses to overwrite a different existing raw file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd


REQUIRED_COLUMNS = [
    "OPIS Truckstop ID",
    "Truckstop Name",
    "Address",
    "City",
    "State",
    "Rack ID",
    "Retail Price",
]
OUTPUT_COLUMNS = [
    "opis_id",
    "name",
    "address",
    "city",
    "state",
    "rack_id",
    "retail_price",
    "source_row_numbers",
    "source_row_count",
    "source_prices",
    "price_aggregation",
]
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI",
    "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC",
    "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT",
    "VT", "VA", "WA", "WV", "WI", "WY",
}
CANADIAN_PROVINCES = {
    "AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC",
    "SK", "YT",
}
TEXT_COLUMNS = ["name", "address", "city", "state", "rack_id"]


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Preserve, validate, clean, and audit the company fuel CSV."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Source CSV; defaults to the preserved raw file, then the supplied root CSV.",
    )
    parser.add_argument(
        "--raw-output",
        type=Path,
        default=root / "data" / "raw" / "company_fuel_prices.csv",
        help="Immutable canonical copy of the source CSV.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "data" / "processed" / "fuel_stations_cleaned.csv",
        help="Deterministic cleaned CSV.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=root / "data" / "processed" / "data_quality_report.json",
        help="JSON data-quality report.",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def preserve_raw_file(source: Path, raw_path: Path) -> str:
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    if raw_path.exists():
        if sha256(source) != sha256(raw_path):
            raise RuntimeError(
                f"Refusing to overwrite existing raw CSV with different contents: {raw_path}"
            )
    else:
        shutil.copyfile(source, raw_path)
    return sha256(raw_path)


def clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def normalized(value: object) -> str:
    return " ".join(clean_text(value).casefold().split())


def positive_price(value: object) -> float | None:
    if pd.isna(value):
        return None
    try:
        parsed = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed <= 0:
        return None
    return parsed


def price_issue(value: object) -> str | None:
    if pd.isna(value) or clean_text(value) == "":
        return "missing_price"
    try:
        parsed = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return "non_numeric_price"
    if not math.isfinite(parsed):
        return "non_finite_price"
    if parsed == 0:
        return "zero_price"
    if parsed < 0:
        return "negative_price"
    return None


def count_reasons(reasons: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for reason in reasons:
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def station_group_key(row: pd.Series) -> tuple[str, ...]:
    """Merge only one ID at one normalized physical location.

    A repeated ID at a different location is retained and flagged as
    suspicious rather than silently merging potentially distinct stations.
    """
    opis_id = row["opis_id"]
    location = (row["address_key"], row["city_key"], row["state"])
    if opis_id:
        return ("id_location", opis_id, *location)
    return ("missing_id_location", *location, row["name_key"])


def build_report(
    *,
    source: Path,
    raw_path: Path,
    raw_hash: str,
    original_rows: int,
    retained_rows: int,
    excluded_rows: int,
    excluded_reasons: list[str],
    missing_ids: int,
    exact_duplicates: int,
    merged_records: int,
    price_conflicts: int,
    invalid_prices: int,
    unknown_states: int,
    canadian_rows: int,
    suspicious_ids: int,
    final_unique_stations: int,
) -> dict[str, object]:
    return {
        "source": {
            "input_file": str(source),
            "preserved_raw_file": str(raw_path),
            "sha256": raw_hash,
        },
        "rules": {
            "required_columns": REQUIRED_COLUMNS,
            "allowed_us_states": sorted(US_STATES),
            "canadian_codes_excluded": sorted(CANADIAN_PROVINCES),
            "price_rule": "numeric, finite, and greater than zero",
            "identity_rule": (
                "merge records only when OPIS ID and normalized address/city/state "
                "match; missing-ID rows use normalized location and name"
            ),
            "conflicting_price_rule": (
                "median of valid prices for a clearly identical station group; "
                "this is not treated as the newest or current price"
            ),
        },
        "counts": {
            "original_rows": original_rows,
            "retained_rows": retained_rows,
            "excluded_rows": excluded_rows,
            "exclusions_by_reason": count_reasons(excluded_reasons),
            "missing_id_rows_flagged": missing_ids,
            "exact_duplicates_removed": exact_duplicates,
            "merged_records": merged_records,
            "price_conflicts": price_conflicts,
            "invalid_price_rows": invalid_prices,
            "unknown_state_rows": unknown_states,
            "canadian_rows": canadian_rows,
            "suspicious_repeated_ids": suspicious_ids,
            "final_unique_station_count": final_unique_stations,
        },
    }


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    supplied_input = root / "fuel-prices-for-be-assessment.csv"
    raw_path = args.raw_output.resolve()
    output_path = args.output.resolve()
    report_path = args.report.resolve()
    source = (
        args.input.resolve()
        if args.input is not None
        else raw_path if raw_path.exists() else supplied_input
    )

    if not source.exists():
        print(f"Input CSV was not found: {source}", file=sys.stderr)
        return 2

    try:
        raw_hash = preserve_raw_file(source, raw_path)
        frame = pd.read_csv(
            source,
            dtype={
                "OPIS Truckstop ID": "string",
                "Rack ID": "string",
                "Retail Price": "string",
            },
            keep_default_na=True,
        )
    except (OSError, UnicodeError, pd.errors.ParserError, RuntimeError) as exc:
        print(f"Could not prepare the source CSV: {exc}", file=sys.stderr)
        return 2

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing_columns:
        print(
            "Missing required CSV columns: " + ", ".join(missing_columns),
            file=sys.stderr,
        )
        return 2

    frame = frame[REQUIRED_COLUMNS].copy()
    frame.insert(0, "source_row_number", range(2, len(frame) + 2))
    frame = frame.rename(
        columns={
            "OPIS Truckstop ID": "opis_id",
            "Truckstop Name": "name",
            "Address": "address",
            "City": "city",
            "State": "state",
            "Rack ID": "rack_id",
            "Retail Price": "retail_price_source",
        }
    )
    for column in TEXT_COLUMNS:
        frame[column] = frame[column].map(clean_text)
    frame["state"] = frame["state"].str.upper()
    frame["opis_id"] = frame["opis_id"].map(clean_text)
    frame["retail_price_valid"] = frame["retail_price_source"].map(positive_price)
    frame["price_issue"] = frame["retail_price_source"].map(price_issue)
    frame["name_key"] = frame["name"].map(normalized)
    frame["address_key"] = frame["address"].map(normalized)
    frame["city_key"] = frame["city"].map(normalized)

    original_rows = len(frame)
    excluded_reasons: list[str] = []
    missing_ids = int(frame["opis_id"].eq("").sum())
    for _, row in frame.iterrows():
        reasons: list[str] = []
        if not row["name"]:
            reasons.append("missing_name")
        if not row["address"]:
            reasons.append("missing_address")
        if not row["city"]:
            reasons.append("missing_city")
        if not row["state"]:
            reasons.append("missing_state")
        if row["state"] in CANADIAN_PROVINCES:
            reasons.append("canadian_record")
        elif row["state"] not in US_STATES:
            reasons.append("unknown_state")
        if row["price_issue"]:
            reasons.append(row["price_issue"])
        excluded_reasons.extend(reasons)
    invalid_price_rows = int(frame["price_issue"].notna().sum())
    unknown_states = int(
        (~frame["state"].isin(US_STATES | CANADIAN_PROVINCES)).sum()
    )
    canadian_rows = int(frame["state"].isin(CANADIAN_PROVINCES).sum())

    valid = frame[
        frame["name"].ne("")
        & frame["address"].ne("")
        & frame["city"].ne("")
        & frame["state"].isin(US_STATES)
        & frame["retail_price_valid"].notna()
    ].copy()
    initial_excluded_rows = original_rows - len(valid)

    meaningful = [
        "opis_id", "name_key", "address_key", "city_key", "state", "rack_id",
        "retail_price_valid",
    ]
    duplicate_mask = valid.duplicated(subset=meaningful, keep="first")
    exact_duplicates = int(duplicate_mask.sum())
    valid = valid.loc[~duplicate_mask].copy()

    repeated_id_counts = valid[valid["opis_id"].ne("")].groupby("opis_id")[
        "address_key"
    ].nunique()
    suspicious_ids = int((repeated_id_counts > 1).sum())
    valid["station_group"] = valid.apply(station_group_key, axis=1)

    output_rows: list[dict[str, object]] = []
    price_conflicts = 0
    merged_records = 0
    for _, group in valid.groupby("station_group", sort=True, dropna=False):
        group = group.sort_values("source_row_number")
        prices = group["retail_price_valid"].astype(float)
        conflict = prices.nunique() > 1
        if conflict:
            price_conflicts += 1
        if len(group) > 1:
            merged_records += len(group) - 1
        first = group.iloc[0]
        output_rows.append(
            {
                "opis_id": first["opis_id"] or None,
                "name": first["name"],
                "address": first["address"],
                "city": first["city"],
                "state": first["state"],
                "rack_id": first["rack_id"] or None,
                "retail_price": float(prices.median()),
                "source_row_numbers": ",".join(
                    str(int(value)) for value in group["source_row_number"]
                ),
                "source_row_count": len(group),
                "source_prices": ",".join(
                    str(value) for value in group["retail_price_source"]
                ),
                "price_aggregation": "median_valid_price" if conflict else "source_price",
            }
        )

    cleaned = pd.DataFrame(output_rows, columns=OUTPUT_COLUMNS)
    cleaned = cleaned.sort_values(
        by=["state", "city", "address", "opis_id"],
        na_position="last",
        kind="mergesort",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned.to_csv(output_path, index=False, lineterminator="\n")
    report = build_report(
        source=source,
        raw_path=raw_path,
        raw_hash=raw_hash,
        original_rows=original_rows,
        retained_rows=len(cleaned),
        excluded_rows=initial_excluded_rows + exact_duplicates,
        excluded_reasons=excluded_reasons,
        missing_ids=missing_ids,
        exact_duplicates=exact_duplicates,
        merged_records=merged_records,
        price_conflicts=price_conflicts,
        invalid_prices=invalid_price_rows,
        unknown_states=unknown_states,
        canadian_rows=canadian_rows,
        suspicious_ids=suspicious_ids,
        final_unique_stations=len(cleaned),
    )
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["counts"], indent=2, sort_keys=True))
    print(f"Cleaned CSV: {output_path}")
    print(f"Quality report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
