from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import yfinance as yf


ROOT = Path(__file__).resolve().parents[1]
SEED_CSV = ROOT / "data" / "universe_seeds.csv"
OUTPUT_CSV = ROOT / "data" / "watchlist.csv"
MIN_DIVIDEND_YIELD = 2.0
MIN_MARKET_CAP = 30_000_000_000
MIN_EQUITY_RATIO = 20.0
MIN_LISTING_YEARS = 5
FINANCIAL_SECTORS = {"銀行", "保険", "その他金融", "リース"}
SOFT_REASONS = {"利回り不足", "自己資本比率不足", "上場年数不足"}
HARD_REASONS = {"時価総額不足", "2期連続営業赤字", "直近5年で無配あり"}


OUTPUT_FIELDS = [
    "コード",
    "銘柄名",
    "業種",
    "配当利回り(%)",
    "PER(倍)",
    "PBR(倍)",
    "ミックス係数",
    "自己資本比率(%)",
    "ROE(%)",
    "営業利益率(%)",
    "売上CAGR3年(%)",
    "営利CAGR3年(%)",
    "連続増配(年)",
    "過去10年減配回数",
    "配当性向(%)",
    "D/Eレシオ",
    "FCF3年連続+",
    "スコア合計",
    "最終更新日",
    "採用区分",
    "スクリーニング理由",
    "メモ",
]


def to_percent(value: float | None) -> float | None:
    if value is None:
        return None
    return value * 100 if abs(value) <= 1 else value


def format_number(value: float | int | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, int):
        return str(value)
    return f"{value:.{digits}f}"


def first_matching_value(frame: pd.DataFrame, labels: list[str]) -> float | None:
    for label in labels:
        if label in frame.index:
            series = frame.loc[label].dropna()
            if not series.empty:
                return float(series.iloc[0])
    return None


def cagr_from_series(values: pd.Series, periods: int = 3) -> float | None:
    clean = values.dropna()
    if len(clean) < periods + 1:
        return None
    latest = float(clean.iloc[0])
    oldest = float(clean.iloc[periods])
    if latest <= 0 or oldest <= 0:
        return None
    return ((latest / oldest) ** (1 / periods) - 1) * 100


def normalize_dividend_yield(value: float | None) -> float | None:
    if value is None:
        return None
    return value * 100 if value <= 1 else value


def normalize_debt_to_equity(value: float | None) -> float | None:
    if value is None:
        return None
    return value / 100 if value > 10 else value


def annual_dividend_metrics(dividends: pd.Series) -> tuple[int | None, int | None, bool]:
    if dividends.empty:
        return None, None, True

    annual = dividends.resample("YE").sum()
    annual.index = annual.index.year
    annual = annual.sort_index()

    positive = annual[annual > 0]
    if positive.empty:
        return 0, 0, True

    recent_five = annual.tail(5)
    has_no_dividend_recently = len(recent_five) >= 5 and any(value <= 0 for value in recent_five)

    cuts = 0
    streak = 0
    best_streak = 0
    previous = None
    for amount in positive:
        if previous is not None:
            if amount > previous:
                streak += 1
            elif amount < previous:
                cuts += 1
                streak = 0
            best_streak = max(best_streak, streak)
        previous = amount

    return best_streak, cuts, has_no_dividend_recently


def listing_years(ticker: yf.Ticker) -> int | None:
    history = ticker.history(period="max", interval="3mo", auto_adjust=False)
    if history.empty:
        return None
    start = history.index.min().date()
    today = date.today()
    return today.year - start.year - ((today.month, today.day) < (start.month, start.day))


@dataclass
class ScreenedRow:
    row: dict[str, str]
    included: bool
    reason: str
    score_hint: float


def build_row(seed: dict[str, str]) -> ScreenedRow:
    code = seed["コード"]
    ticker = yf.Ticker(f"{code}.T")
    info = ticker.info
    income = ticker.income_stmt
    balance = ticker.balance_sheet
    cashflow = ticker.cashflow

    market_cap = info.get("marketCap")
    dividend_yield = normalize_dividend_yield(info.get("dividendYield"))
    trailing_pe = info.get("trailingPE")
    pbr = info.get("priceToBook")
    roe = to_percent(info.get("returnOnEquity"))
    operating_margin = to_percent(info.get("operatingMargins"))
    payout_ratio = to_percent(info.get("payoutRatio"))
    de_ratio = normalize_debt_to_equity(info.get("debtToEquity"))

    total_assets = first_matching_value(balance, ["Total Assets"])
    total_equity = first_matching_value(
        balance,
        ["Stockholders Equity", "Total Equity Gross Minority Interest", "Common Stock Equity"],
    )
    equity_ratio = ((total_equity / total_assets) * 100) if total_assets and total_equity else None

    revenue = income.loc["Total Revenue"].dropna() if "Total Revenue" in income.index else pd.Series(dtype=float)
    operating_income = income.loc["Operating Income"].dropna() if "Operating Income" in income.index else pd.Series(dtype=float)
    operating_loss_2y = False
    if not operating_income.empty and len(operating_income) >= 2:
        operating_loss_2y = bool((operating_income.iloc[0] < 0) and (operating_income.iloc[1] < 0))

    free_cash_flow = cashflow.loc["Free Cash Flow"].dropna() if "Free Cash Flow" in cashflow.index else pd.Series(dtype=float)
    fcf_positive_years = int((free_cash_flow.head(3) > 0).sum()) if not free_cash_flow.empty else None

    dividend_years, dividend_cuts, has_no_dividend_recently = annual_dividend_metrics(ticker.dividends)
    years_listed = listing_years(ticker)

    reasons: list[str] = []
    skip_equity_filter = seed["業種"] in FINANCIAL_SECTORS
    if dividend_yield is None or dividend_yield < MIN_DIVIDEND_YIELD:
        reasons.append("利回り不足")
    if market_cap is None or market_cap < MIN_MARKET_CAP:
        reasons.append("時価総額不足")
    if (not skip_equity_filter) and (equity_ratio is None or equity_ratio < MIN_EQUITY_RATIO):
        reasons.append("自己資本比率不足")
    if years_listed is None or years_listed < MIN_LISTING_YEARS:
        reasons.append("上場年数不足")
    if operating_loss_2y:
        reasons.append("2期連続営業赤字")
    if has_no_dividend_recently:
        reasons.append("直近5年で無配あり")

    hard_failures = [reason for reason in reasons if reason in HARD_REASONS]
    soft_failures = [reason for reason in reasons if reason in SOFT_REASONS]
    included = not hard_failures

    row = {
        "コード": seed["コード"],
        "銘柄名": seed["銘柄名"],
        "業種": seed["業種"],
        "配当利回り(%)": format_number(dividend_yield),
        "PER(倍)": format_number(trailing_pe),
        "PBR(倍)": format_number(pbr),
        "ミックス係数": format_number((trailing_pe * pbr) if trailing_pe and pbr else None),
        "自己資本比率(%)": format_number(equity_ratio),
        "ROE(%)": format_number(roe),
        "営業利益率(%)": format_number(operating_margin),
        "売上CAGR3年(%)": format_number(cagr_from_series(revenue)),
        "営利CAGR3年(%)": format_number(cagr_from_series(operating_income)),
        "連続増配(年)": format_number(dividend_years, 0),
        "過去10年減配回数": format_number(dividend_cuts, 0),
        "配当性向(%)": format_number(payout_ratio),
        "D/Eレシオ": format_number(de_ratio),
        "FCF3年連続+": format_number(fcf_positive_years, 0),
        "スコア合計": "",
        "最終更新日": date.today().isoformat(),
        "採用区分": "境界採用" if soft_failures else "通常",
        "スクリーニング理由": " / ".join(reasons) if reasons else "",
        "メモ": f"時価総額={format_number((market_cap / 100000000) if market_cap else None)}億円 / 上場年数={years_listed or ''}",
    }

    score_hint = float(dividend_yield or 0) + float(roe or 0) + float(operating_margin or 0)
    if soft_failures:
        score_hint -= len(soft_failures) * 5
    return ScreenedRow(row=row, included=included, reason=" / ".join(reasons), score_hint=score_hint)


def main() -> None:
    with SEED_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        seeds = list(csv.DictReader(handle))

    included_rows: list[ScreenedRow] = []
    dropped: list[ScreenedRow] = []

    for seed in seeds:
        result = build_row(seed)
        if result.included:
            included_rows.append(result)
        else:
            dropped.append(result)

    included_rows.sort(key=lambda item: (item.row["採用区分"] == "通常", item.score_hint), reverse=True)

    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for item in included_rows:
            writer.writerow(item.row)

    print(f"Wrote {OUTPUT_CSV} with {len(included_rows)} screened tickers")
    rescued = [item for item in included_rows if item.row["採用区分"] == "境界採用"]
    if rescued:
        print("Included with caution:")
        for item in rescued:
            print(f"{item.row['コード']} {item.row['銘柄名']}: {item.reason}")
    if dropped:
        print("Dropped:")
        for item in dropped:
            print(f"{item.row['コード']} {item.row['銘柄名']}: {item.reason}")


if __name__ == "__main__":
    main()
