from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT_CSV = ROOT / "data" / "watchlist.csv"
OUTPUT_CSV = ROOT / "data" / "watchlist_scored.csv"


@dataclass
class ScoreBreakdown:
    dividend: int = 0
    growth: int = 0
    financial: int = 0
    valuation: int = 0

    @property
    def total(self) -> int:
        return self.dividend + self.growth + self.financial + self.valuation


def parse_float(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    return float(value)


def parse_int(value: str) -> int | None:
    number = parse_float(value)
    if number is None:
        return None
    return int(number)


def score_dividend_growth(years: int | None) -> int:
    if years is None or years <= 0:
        return 0
    if years >= 10:
        return 12
    if years >= 5:
        return 6
    return 0


def score_dividend_cuts(cuts: int | None) -> int:
    if cuts is None:
        return 0
    if cuts == 0:
        return 10
    if cuts == 1:
        return 7
    if cuts == 2:
        return 4
    return 0


def score_payout_ratio(ratio: float | None) -> int:
    if ratio is None:
        return 0
    if 30 <= ratio <= 50:
        return 8
    if 50 < ratio <= 60:
        return 5
    if 60 < ratio <= 70:
        return 2
    return 0


def score_dividend_yield(yield_pct: float | None) -> int:
    if yield_pct is None or yield_pct < 2:
        return 0
    if yield_pct < 3:
        return 2
    if yield_pct < 4:
        return 4
    return 5


def score_cagr(value: float | None) -> int:
    if value is None or value <= 0:
        return 0
    if value <= 5:
        return 4
    if value <= 10:
        return 7
    return 10


def score_roe(value: float | None) -> int:
    if value is None or value < 5:
        return 0
    if value < 8:
        return 2
    if value < 12:
        return 4
    return 5


def score_operating_margin(value: float | None) -> int:
    if value is None or value < 5:
        return 0
    if value < 10:
        return 2
    if value < 15:
        return 4
    return 5


def score_equity_ratio(value: float | None) -> int:
    if value is None or value < 20:
        return 0
    if value < 40:
        return 2
    if value < 60:
        return 5
    return 8


def score_de_ratio(value: float | None) -> int:
    if value is None:
        return 0
    if value < 0.5:
        return 6
    if value <= 1.0:
        return 3
    return 0


def score_fcf(years_positive: int | None) -> int:
    if years_positive is None:
        return 0
    if years_positive >= 3:
        return 6
    if years_positive == 2:
        return 3
    return 0


def score_pbr(value: float | None) -> int:
    if value is None:
        return 0
    if value < 1.0:
        return 4
    if value <= 2.0:
        return 2
    return 0


def score_mix(value: float | None) -> int:
    if value is None:
        return 0
    if value < 11.25:
        return 3
    if value <= 22.5:
        return 1
    return 0


def score_per_vs_peer(per_value: float | None, peer_per_value: float | None = None) -> int:
    if per_value is None:
        return 0
    if peer_per_value is None or peer_per_value <= 0:
        return 4
    ratio = per_value / peer_per_value
    if ratio < 0.8:
        return 8
    if ratio <= 1.2:
        return 4
    return 0


def build_score(row: dict[str, str]) -> ScoreBreakdown:
    result = ScoreBreakdown()

    result.dividend += score_dividend_growth(parse_int(row["連続増配(年)"]))
    result.dividend += score_dividend_cuts(parse_int(row["過去10年減配回数"]))
    result.dividend += score_payout_ratio(parse_float(row["配当性向(%)"]))
    result.dividend += score_dividend_yield(parse_float(row["配当利回り(%)"]))

    result.growth += score_cagr(parse_float(row["売上CAGR3年(%)"]))
    result.growth += score_cagr(parse_float(row["営利CAGR3年(%)"]))
    result.growth += score_roe(parse_float(row["ROE(%)"]))
    result.growth += score_operating_margin(parse_float(row["営業利益率(%)"]))

    result.financial += score_equity_ratio(parse_float(row["自己資本比率(%)"]))
    result.financial += score_de_ratio(parse_float(row["D/Eレシオ"]))
    result.financial += score_fcf(parse_int(row["FCF3年連続+"]))

    result.valuation += score_per_vs_peer(parse_float(row["PER(倍)"]))
    result.valuation += score_pbr(parse_float(row["PBR(倍)"]))
    result.valuation += score_mix(parse_float(row["ミックス係数"]))

    return result


def main() -> None:
    with INPUT_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    extra_fields = [
        "配当スコア",
        "成長スコア",
        "財務スコア",
        "割安スコア",
        "スコア合計",
        "判定",
        "最終更新日",
    ]
    output_fields = fieldnames + [field for field in extra_fields if field not in fieldnames]

    for row in rows:
        breakdown = build_score(row)
        row["配当スコア"] = str(breakdown.dividend)
        row["成長スコア"] = str(breakdown.growth)
        row["財務スコア"] = str(breakdown.financial)
        row["割安スコア"] = str(breakdown.valuation)
        row["スコア合計"] = str(breakdown.total)
        row["判定"] = "買い候補" if breakdown.total >= 70 else "監視"
        row["最終更新日"] = date.today().isoformat()

    rows.sort(key=lambda row: parse_int(row["スコア合計"]) or 0, reverse=True)

    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
