from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd
import yfinance as yf

from score_watchlist import ScoreBreakdown, build_score


ROOT = Path(__file__).resolve().parents[1]
INPUT_CSV = ROOT / "data" / "watchlist.csv"
LIVE_OUTPUT_CSV = ROOT / "data" / "watchlist_live.csv"
CANDIDATES_OUTPUT_CSV = ROOT / "data" / "sbi_candidates.csv"
SHEETS_OUTPUT_CSV = ROOT / "data" / "sheets_candidates.csv"
RATIONALE_OUTPUT_CSV = ROOT / "data" / "sheets_rationale.csv"
MEMO_OUTPUT_CSV = ROOT / "data" / "sheets_morning_memo.csv"
HTML_OUTPUT = ROOT / "reports" / "dashboard.html"
SUMMARY_OUTPUT = ROOT / "reports" / "morning_summary.md"


@dataclass
class MarketContext:
    vix: float | None
    nikkei_5d: float | None
    nikkei_20d: float | None
    regime: str
    buy_dip_bonus: int
    note: str


def parse_float(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    return float(value)


def format_number(value: float | int | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, int):
        return str(value)
    return f"{value:.{digits}f}"


def to_percent(value: float | None) -> float | None:
    if value is None:
        return None
    return value * 100 if abs(value) <= 1 else value


def normalize_dividend_yield(value: float | None) -> float | None:
    if value is None:
        return None
    if value <= 1:
        return value * 100
    return value


def normalize_debt_to_equity(value: float | None) -> float | None:
    if value is None:
        return None
    return value / 100 if value > 10 else value


def cagr_from_series(values: pd.Series, periods: int = 3) -> float | None:
    clean = values.dropna()
    if len(clean) < periods + 1:
        return None
    latest = float(clean.iloc[0])
    oldest = float(clean.iloc[periods])
    if latest <= 0 or oldest <= 0:
        return None
    return ((latest / oldest) ** (1 / periods) - 1) * 100


def first_matching_value(frame: pd.DataFrame, labels: Iterable[str]) -> float | None:
    for label in labels:
        if label in frame.index:
            series = frame.loc[label].dropna()
            if not series.empty:
                return float(series.iloc[0])
    return None


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
    has_no_dividend_recently = len(recent_five) >= 5 and any(amount <= 0 for amount in recent_five)
    if len(positive) < 2:
        return 0, 0, has_no_dividend_recently

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


def infer_market_snapshot(ticker: yf.Ticker) -> dict[str, float | None]:
    history = ticker.history(period="400d", auto_adjust=False)
    if history.empty:
        return {}

    latest = history.iloc[-1]
    previous = history.iloc[-2] if len(history) > 1 else latest
    five_days_ago = history.iloc[-6] if len(history) > 5 else previous
    month_ago = history.iloc[-22] if len(history) > 21 else previous

    close_series = history["Close"].dropna()
    daily_returns = close_series.pct_change().dropna()
    ma25 = close_series.tail(25).mean() if len(close_series) >= 25 else None
    ma75 = close_series.tail(75).mean() if len(close_series) >= 75 else None
    year_high = float(close_series.tail(252).max()) if len(close_series) >= 2 else None
    year_low = float(close_series.tail(252).min()) if len(close_series) >= 2 else None

    last_price = float(latest["Close"])
    previous_close = float(previous["Close"])
    daily_change = ((last_price / previous_close) - 1) * 100 if previous_close else None
    avg_abs_daily_move = float(daily_returns.tail(5).abs().mean() * 100) if len(daily_returns) >= 5 else None
    five_day_change = ((last_price / float(five_days_ago["Close"])) - 1) * 100 if float(five_days_ago["Close"]) else None
    month_change = ((last_price / float(month_ago["Close"])) - 1) * 100 if float(month_ago["Close"]) else None
    drawdown_from_high = ((last_price / year_high) - 1) * 100 if year_high else None
    estimate_move_pct = max(avg_abs_daily_move or 0, 0.8)
    order_ref_price = previous_close
    order_range_low = order_ref_price * (1 - estimate_move_pct / 100)
    order_range_high = order_ref_price * (1 + estimate_move_pct / 100)

    return {
        "前日終値(円)": previous_close,
        "成行目安(円)": last_price,
        "SBI参考価格(円)": order_ref_price,
        "成行目安下限(円)": order_range_low,
        "成行目安上限(円)": order_range_high,
        "成行想定変動率(%)": estimate_move_pct,
        "前日比(%)": daily_change,
        "当日始値(円)": float(latest["Open"]),
        "高値(円)": float(latest["High"]),
        "安値(円)": float(latest["Low"]),
        "出来高": int(latest["Volume"]),
        "25MA(円)": ma25,
        "75MA(円)": ma75,
        "52週高値(円)": year_high,
        "52週安値(円)": year_low,
        "5日騰落率(%)": five_day_change,
        "1ヶ月騰落率(%)": month_change,
        "52週高値乖離率(%)": drawdown_from_high,
    }


def infer_fundamentals(ticker: yf.Ticker) -> dict[str, float | int | None]:
    info = ticker.info
    income = ticker.income_stmt
    balance = ticker.balance_sheet
    cashflow = ticker.cashflow

    total_assets = first_matching_value(balance, ["Total Assets"])
    total_equity = first_matching_value(
        balance,
        ["Stockholders Equity", "Total Equity Gross Minority Interest", "Common Stock Equity"],
    )
    equity_ratio = ((total_equity / total_assets) * 100) if total_assets and total_equity else None

    free_cash_flow = cashflow.loc["Free Cash Flow"].dropna() if "Free Cash Flow" in cashflow.index else pd.Series(dtype=float)
    fcf_positive_years = int((free_cash_flow.head(3) > 0).sum()) if not free_cash_flow.empty else None

    revenue = income.loc["Total Revenue"].dropna() if "Total Revenue" in income.index else pd.Series(dtype=float)
    operating_income = income.loc["Operating Income"].dropna() if "Operating Income" in income.index else pd.Series(dtype=float)

    dividend_years, dividend_cuts, has_no_dividend_recently = annual_dividend_metrics(ticker.dividends)

    trailing_pe = info.get("trailingPE")
    pbr = info.get("priceToBook")

    return {
        "配当利回り(%)": normalize_dividend_yield(info.get("dividendYield")),
        "PER(倍)": float(trailing_pe) if trailing_pe else None,
        "PBR(倍)": float(pbr) if pbr else None,
        "ミックス係数": (float(trailing_pe) * float(pbr)) if trailing_pe and pbr else None,
        "自己資本比率(%)": equity_ratio,
        "ROE(%)": to_percent(info.get("returnOnEquity")),
        "営業利益率(%)": to_percent(info.get("operatingMargins")),
        "売上CAGR3年(%)": cagr_from_series(revenue),
        "営利CAGR3年(%)": cagr_from_series(operating_income),
        "連続増配(年)": dividend_years,
        "過去10年減配回数": dividend_cuts,
        "配当性向(%)": to_percent(info.get("payoutRatio")),
        "直近5年で無配あり": "あり" if has_no_dividend_recently else "なし",
        "D/Eレシオ": normalize_debt_to_equity(info.get("debtToEquity")),
        "FCF3年連続+": fcf_positive_years,
    }


def get_market_context() -> MarketContext:
    vix_history = yf.Ticker("^VIX").history(period="1mo")["Close"].dropna()
    nikkei_history = yf.Ticker("^N225").history(period="3mo")["Close"].dropna()

    vix = float(vix_history.iloc[-1]) if not vix_history.empty else None
    nikkei_5d = ((float(nikkei_history.iloc[-1]) / float(nikkei_history.iloc[-6])) - 1) * 100 if len(nikkei_history) >= 6 else None
    nikkei_20d = ((float(nikkei_history.iloc[-1]) / float(nikkei_history.iloc[-21])) - 1) * 100 if len(nikkei_history) >= 21 else None

    if (vix is not None and vix >= 30) or (nikkei_5d is not None and nikkei_5d <= -8):
        return MarketContext(vix=vix, nikkei_5d=nikkei_5d, nikkei_20d=nikkei_20d, regime="恐怖", buy_dip_bonus=8, note="恐怖局面。高品質株は押し目を買う日")
    if (vix is not None and vix >= 25) or (nikkei_5d is not None and nikkei_5d <= -5):
        return MarketContext(vix=vix, nikkei_5d=nikkei_5d, nikkei_20d=nikkei_20d, regime="弱気", buy_dip_bonus=5, note="弱気相場。高品質株は前日比-3%~-5%の押し目を狙う")
    if (vix is not None and vix >= 20) or (nikkei_20d is not None and nikkei_20d <= -3):
        return MarketContext(vix=vix, nikkei_5d=nikkei_5d, nikkei_20d=nikkei_20d, regime="やや弱気", buy_dip_bonus=2, note="やや弱気。押し目確認で候補を前倒し")
    if (vix is not None and vix <= 16) and (nikkei_20d is not None and nikkei_20d >= 5):
        return MarketContext(vix=vix, nikkei_5d=nikkei_5d, nikkei_20d=nikkei_20d, regime="楽観", buy_dip_bonus=-4, note="楽観寄り。高値追いは避ける")
    return MarketContext(vix=vix, nikkei_5d=nikkei_5d, nikkei_20d=nikkei_20d, regime="中立", buy_dip_bonus=0, note="中立。品質と押し目を素直に見る")


def data_completeness(row: dict[str, str]) -> int:
    required = [
        "配当利回り(%)",
        "PER(倍)",
        "PBR(倍)",
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
        "前日終値(円)",
        "成行目安(円)",
        "25MA(円)",
        "75MA(円)",
        "52週高値(円)",
        "52週安値(円)",
        "前日比(%)",
        "5日騰落率(%)",
        "1ヶ月騰落率(%)",
    ]
    filled = sum(1 for field in required if parse_float(row.get(field, "")) is not None)
    return round((filled / len(required)) * 100)


def build_signal_fields(row: dict[str, str]) -> tuple[list[str], list[str], int, int]:
    buy_signals: list[str] = []
    wait_signals: list[str] = []
    setup_score = 0
    wait_penalty = 0

    last_price = parse_float(row.get("成行目安(円)", ""))
    ma25 = parse_float(row.get("25MA(円)", ""))
    ma75 = parse_float(row.get("75MA(円)", ""))
    year_low = parse_float(row.get("52週安値(円)", ""))
    year_high = parse_float(row.get("52週高値(円)", ""))
    daily_change = parse_float(row.get("前日比(%)", ""))
    five_day = parse_float(row.get("5日騰落率(%)", ""))
    month_change = parse_float(row.get("1ヶ月騰落率(%)", ""))

    if last_price and ma75 and last_price < ma75:
        buy_signals.append("75MA割れ")
        setup_score += 10
    elif last_price and ma25 and last_price < ma25:
        buy_signals.append("25MA割れ")
        setup_score += 6

    if last_price and year_low and last_price <= year_low * 1.10:
        buy_signals.append("52週安値圏")
        setup_score += 8

    if daily_change is not None and daily_change <= -5:
        buy_signals.append("前日比-5%下落")
        setup_score += 8
    elif daily_change is not None and daily_change <= -3:
        buy_signals.append("前日比-3%下落")
        setup_score += 5
    elif five_day is not None and five_day <= -5:
        buy_signals.append("5日で-5%下落")
        setup_score += 4

    if month_change is not None and month_change <= -10:
        buy_signals.append("1ヶ月-10%")
        setup_score += 5

    if daily_change is not None and daily_change >= 7:
        wait_signals.append("前日比+7%超上昇")
        wait_penalty += 12
    if five_day is not None and five_day >= 10:
        wait_signals.append("5日急騰")
        wait_penalty += 10
    if last_price and year_high and last_price >= year_high * 0.95:
        wait_signals.append("52週高値圏")
        wait_penalty += 8

    return buy_signals, wait_signals, min(setup_score, 25), wait_penalty


def priority_rank(priority: int) -> str:
    if priority >= 95:
        return "S"
    if priority >= 80:
        return "A"
    if priority >= 65:
        return "B"
    return "C"


def confidence_metrics(completeness: int, quality_score: int, setup_score: int, wait_signals: list[str]) -> tuple[int, str]:
    confidence = completeness
    if quality_score >= 70 and setup_score >= 10 and not wait_signals:
        confidence += 5
    if wait_signals:
        confidence -= 5
    if quality_score < 55:
        confidence -= 5
    confidence = max(0, min(100, confidence))

    if confidence >= 85:
        return confidence, "高"
    if confidence >= 70:
        return confidence, "中"
    return confidence, "低"


def calculate_priority(quality_score: int, setup_score: int, wait_penalty: int, completeness: int, context: MarketContext) -> tuple[int, int, int]:
    market_bonus = context.buy_dip_bonus if quality_score >= 60 else 0
    missing_penalty = 0
    if completeness < 90:
        missing_penalty += 3
    if completeness < 75:
        missing_penalty += 5
    total_penalty = wait_penalty + missing_penalty
    priority = max(0, quality_score + setup_score + market_bonus - total_penalty)
    return priority, market_bonus, total_penalty


def action_plan(
    row: dict[str, str],
    quality_score: int,
    setup_score: int,
    priority: int,
    completeness: int,
    wait_signals: list[str],
    context: MarketContext,
) -> tuple[str, str, float | None, float | None]:
    prev_close = parse_float(row.get("前日終値(円)", ""))
    daily_change = parse_float(row.get("前日比(%)", ""))

    watch_2 = prev_close * 0.98 if prev_close else None
    watch_3 = prev_close * 0.97 if prev_close else None
    buy_3 = prev_close * 0.97 if prev_close else None
    buy_5 = prev_close * 0.95 if prev_close else None

    if completeness < 70:
        return "データ確認が先", "数字が足りない。今日は買わずに決算・配当データを確認", None, None

    if wait_signals:
        if "52週高値圏" in wait_signals:
            target = buy_5 or prev_close
            return (
                "今は買わない（高値圏）",
                f"高値圏なので今は買わない。{format_number(watch_3)}円以下まで下がったら再確認、{format_number(target)}円以下で買い検討",
                watch_3,
                target,
            )
        return (
            "今は買わない（急騰後）",
            f"急騰直後なので今は追わない。{format_number(watch_3)}円以下まで落ち着くのを待ち、{format_number(buy_5)}円以下で買い検討",
            watch_3,
            buy_5,
        )

    if quality_score >= 70 and priority >= 88 and setup_score >= 10:
        if daily_change is not None and daily_change <= -5:
            return "今日の水準で1株", f"条件到達。{format_number(prev_close)}円前後なら1株買い", prev_close, prev_close
        if context.regime in {"恐怖", "弱気"}:
            return "前日比-3%で買い", f"{format_number(watch_2)}円以下で再確認、{format_number(buy_3)}円以下で1株買い", watch_2, buy_3
        return "前日比-5%で買い", f"{format_number(watch_3)}円以下で再確認、{format_number(buy_5)}円以下で1株買い", watch_3, buy_5

    if quality_score >= 65 and priority >= 78:
        if context.regime in {"恐怖", "弱気"} and setup_score >= 8:
            return "前日比-5%で買い", f"{format_number(watch_3)}円以下で再確認、{format_number(buy_5)}円以下で1株買い", watch_3, buy_5
        if quality_score >= 68 and context.regime in {"恐怖", "弱気", "やや弱気"}:
            return (
                "まあ1株エントリー可",
                f"強い押し目ではないが品質優先で少額なら可。{format_number(prev_close)}円前後で1株まで、余力は残す",
                prev_close,
                prev_close,
            )
        return (
            "押し目を待つ",
            f"まだ下げが足りない。{format_number(watch_3)}円以下まで待ち、{format_number(buy_5)}円以下で買い検討",
            watch_3,
            buy_5,
        )

    if quality_score >= 60 and setup_score >= 12:
        return "前日比-5%で買い", f"{format_number(watch_3)}円以下で再確認、{format_number(buy_5)}円以下で1株買い", watch_3, buy_5

    if quality_score >= 55 and setup_score >= 8:
        return (
            "条件待ち",
            f"今は監視だけ。{format_number(watch_3)}円以下で再確認、{format_number(buy_5)}円以下で買い検討",
            watch_3,
            buy_5,
        )

    return "見送り", "品質かタイミングが不足。今日は買わない", None, None


def build_reason_summary(
    row: dict[str, str],
    market_context: MarketContext,
    watch_price: float | None,
    buy_price: float | None,
) -> str:
    quality = row.get("品質スコア", "")
    timing = row.get("タイミングスコア", "")
    rank = row.get("優先ランク", "")
    action = row.get("アクション", "")
    buy_signals = row.get("買いシグナル", "-")
    wait_signals = row.get("待ちシグナル", "-")
    pieces = [
        f"優先ランク{rank}。品質{quality}点、タイミング{timing}点。",
        f"地合いは{market_context.regime}で {market_context.note}。",
        f"買いシグナル: {buy_signals}。",
    ]
    if wait_signals != "-":
        pieces.append(f"待ちシグナル: {wait_signals}。")
    if watch_price is not None:
        pieces.append(f"まだ待ち価格は {format_number(watch_price)}円。")
    if buy_price is not None:
        pieces.append(f"買い価格は {format_number(buy_price)}円。")
    pieces.append(
        "指標は "
        f"PER {row.get('PER(倍)', '-')}倍 / "
        f"PBR {row.get('PBR(倍)', '-')}倍 / "
        f"ROE {row.get('ROE(%)', '-')}% / "
        f"25MA {row.get('25MA(円)', '-')}円 / "
        f"75MA {row.get('75MA(円)', '-')}円。"
    )
    pieces.append(f"最終アクションは「{action}」。")
    return " ".join(pieces)


def build_score_summary(row: dict[str, str]) -> str:
    return (
        f"品質{row.get('品質スコア', '')}"
        f" / タイミング{row.get('タイミングスコア', '')}"
        f" / 地合い加点{row.get('地合い加点', '')}"
        f" / 減点{row.get('減点', '')}"
    )


def build_morning_note(row: dict[str, str]) -> str:
    action = row.get("アクション", "")
    buy_signals = row.get("買いシグナル", "-")
    wait_signals = row.get("待ちシグナル", "-")
    watch_price = row.get("まだ待ち価格(円)", "")
    buy_price = row.get("買い価格(円)", "")
    detail = row.get("アクション詳細", "")

    if action == "今は買わない（高値圏）":
        return f"高値圏。今は買わない。{watch_price}円以下まで下がったら再確認、{buy_price}円以下で買い検討。"
    if action == "押し目を待つ":
        return f"品質は十分。押し目不足。{watch_price}円以下まで待ち、{buy_price}円以下で買い検討。"
    if action == "条件待ち":
        return f"条件待ち。{watch_price}円以下で再確認、{buy_price}円以下で買い検討。"
    if action == "今は買わない（急騰後）":
        return f"急騰直後。今は追わない。{watch_price}円以下まで落ち着くのを待ち、{buy_price}円以下で買い検討。"
    if action in {"前日比-3%で買い", "前日比-5%で買い", "今日の水準で1株"}:
        return f"買い条件あり。{detail}。買いシグナル: {buy_signals}。"
    if action == "まあ1株エントリー可":
        return f"少額なら可。{watch_price}円前後で1株まで、余力は残す。買いシグナル: {buy_signals}。"
    if action == "見送り":
        return f"今日は見送り。待ちシグナル: {wait_signals}。"
    return detail


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def build_html(rows: list[dict[str, str]], context: MarketContext) -> str:
    cards = []
    table_rows = []

    for row in rows[:6]:
        cards.append(
            f"""
            <article class="card">
              <div class="top">
                <div>
                  <p class="code">{row.get("コード", "")}</p>
                  <h2>{row.get("銘柄名", "")}</h2>
                </div>
                <span class="badge rank-{row.get("優先ランク", "")}">{row.get("アクション", "")}</span>
              </div>
              <p class="price">まだ待ち {row.get("まだ待ち価格(円)", "-")} 円</p>
              <p class="meta">買い {row.get("買い価格(円)", "-")} 円</p>
              <p class="detail">{row.get("アクション", "")}</p>
            </article>
            """
        )
        table_rows.append(
            f"""
            <tr>
              <td>{row.get("表示順", "")}</td>
              <td>{row.get("コード", "")}</td>
              <td>{row.get("銘柄名", "")}</td>
              <td>{row.get("アクション", "")}</td>
              <td>{row.get("まだ待ち価格(円)", "")}</td>
              <td>{row.get("買い価格(円)", "")}</td>
            </tr>
            """
        )

    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Morning Stock Dashboard</title>
  <style>
    :root {{
      --bg: #f5f1e8;
      --panel: #fffdf8;
      --ink: #1f2a2e;
      --muted: #6f7b80;
      --line: #d9d1c3;
      --s: #1f7a4d;
      --a: #9a6700;
      --b: #8c5a00;
      --c: #7a3442;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Yu Gothic UI", "Hiragino Sans", sans-serif;
      background: linear-gradient(180deg, #efe4d1 0%, var(--bg) 100%);
      color: var(--ink);
    }}
    .wrap {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 20px;
    }}
    .hero h1 {{
      margin: 0 0 8px;
      font-size: 28px;
    }}
    .hero p {{
      margin: 4px 0;
      color: var(--muted);
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 14px;
      margin: 20px 0 24px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
      box-shadow: 0 10px 30px rgba(31, 42, 46, 0.06);
    }}
    .top {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: start;
    }}
    .code {{
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 0.08em;
    }}
    .card h2 {{
      margin: 4px 0 0;
      font-size: 20px;
    }}
    .badge {{
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
    }}
    .rank-S {{ background: #dff3e8; color: var(--s); }}
    .rank-A {{ background: #fff0c7; color: var(--a); }}
    .rank-B {{ background: #f6e0b6; color: var(--b); }}
    .rank-C {{ background: #f7d9de; color: var(--c); }}
    .price {{
      margin: 14px 0 8px;
      font-size: 21px;
      font-weight: 700;
    }}
    .meta, .signal, .detail {{
      margin: 6px 0 0;
      font-size: 14px;
      line-height: 1.5;
    }}
    .wait {{ color: var(--c); }}
    .detail {{ font-weight: 700; }}
    .table-wrap {{
      overflow-x: auto;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 8px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    th, td {{
      text-align: left;
      padding: 12px 10px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-weight: 700;
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="hero">
      <h1>朝の株候補ダッシュボード</h1>
      <p>地合い: {context.regime} / VIX {format_number(context.vix)} / 日経5日 {format_number(context.nikkei_5d)}%</p>
      <p>{context.note}</p>
    </section>
    <section class="grid">
      {''.join(cards)}
    </section>
    <section class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>順</th>
            <th>コード</th>
            <th>銘柄</th>
            <th>アクション</th>
            <th>まだ待ち</th>
            <th>買い</th>
          </tr>
        </thead>
        <tbody>
          {''.join(table_rows)}
        </tbody>
      </table>
    </section>
  </main>
</body>
</html>
"""


def build_summary(rows: list[dict[str, str]], context: MarketContext) -> str:
    top_rows = rows[:10]
    today = date.today().isoformat()
    lines = [
        f"# {today} 朝メモ",
        "",
        "## 地合い",
        "",
        f"- 判定: {context.regime}",
        f"- 恐怖指数 VIX: {format_number(context.vix)}",
        f"- 日経5日騰落率: {format_number(context.nikkei_5d)}%",
        f"- 日経20日騰落率: {format_number(context.nikkei_20d)}%",
        f"- コメント: {context.note}",
        "",
        "## 上位候補",
        "",
    ]
    for index, row in enumerate(top_rows[:5], start=1):
        lines.extend(
            [
                f"### {index}. {row.get('コード', '')} {row.get('銘柄名', '')}",
                "",
                f"- アクション: {row.get('アクション', '')}",
                f"- アクション詳細: {row.get('アクション詳細', '')}",
                f"- いまの目安: {row.get('SBI参考価格(円)', '')}円",
                f"- まだ待ち価格: {row.get('まだ待ち価格(円)', '')}円",
                f"- 買い価格: {row.get('買い価格(円)', '')}円",
                f"- 品質スコア: {row.get('品質スコア', '')}",
                f"- タイミングスコア: {row.get('タイミングスコア', '')}",
                f"- 総合優先度: {row.get('総合優先度', '')}",
                f"- 信頼度: {row.get('信頼度', '')}",
                f"- 買いシグナル: {row.get('買いシグナル', '-')}",
                f"- 待ちシグナル: {row.get('待ちシグナル', '-')}",
                "",
            ]
        )

    actionable = sum(
        1
        for row in top_rows
        if row.get("アクション") in {"今日の水準で1株", "前日比-3%で買い", "前日比-5%で買い", "まあ1株エントリー可"}
    )
    wait_count = sum(1 for row in top_rows if row.get("アクション") in {"今は買わない（高値圏）", "今は買わない（急騰後）", "押し目を待つ", "条件待ち"})
    skip_count = sum(1 for row in top_rows if row.get("アクション") in {"見送り", "データ確認が先"})
    lines.extend(
        [
            "## ざっくり方針",
            "",
            f"- すぐ買い候補: {actionable}件",
            f"- 待ち銘柄: {wait_count}件",
            f"- 見送り/補完: {skip_count}件",
            "",
            "- `候補一覧` シートを上から見れば、そのままSBIで確認順になります。",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    with INPUT_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        base_rows = list(csv.DictReader(handle))

    market_context = get_market_context()
    live_rows: list[dict[str, str]] = []

    for base_row in base_rows:
        row = dict(base_row)
        ticker_code = f"{row['コード']}.T"
        ticker = yf.Ticker(ticker_code)

        for key, value in infer_fundamentals(ticker).items():
            if isinstance(value, str):
                row[key] = value
            else:
                row[key] = format_number(value, 2) if not isinstance(value, int) else str(value)

        for key, value in infer_market_snapshot(ticker).items():
            if key == "出来高":
                row[key] = format_number(value, 0)
            else:
                row[key] = format_number(value, 2)

        breakdown: ScoreBreakdown = build_score(row)
        buy_signals, wait_signals, setup_score, wait_penalty = build_signal_fields(row)
        completeness = data_completeness(row)
        priority, market_bonus, total_penalty = calculate_priority(
            quality_score=breakdown.total,
            setup_score=setup_score,
            wait_penalty=wait_penalty,
            completeness=completeness,
            context=market_context,
        )
        confidence_score, confidence_label = confidence_metrics(
            completeness=completeness,
            quality_score=breakdown.total,
            setup_score=setup_score,
            wait_signals=wait_signals,
        )
        action, action_detail, watch_price, buy_price = action_plan(
            row=row,
            quality_score=breakdown.total,
            setup_score=setup_score,
            priority=priority,
            completeness=completeness,
            wait_signals=wait_signals,
            context=market_context,
        )

        row["配当スコア"] = str(breakdown.dividend)
        row["成長スコア"] = str(breakdown.growth)
        row["財務スコア"] = str(breakdown.financial)
        row["割安スコア"] = str(breakdown.valuation)
        row["品質スコア"] = str(breakdown.total)
        row["タイミングスコア"] = str(setup_score)
        row["地合い加点"] = str(market_bonus)
        row["減点"] = str(total_penalty)
        row["総合優先度"] = str(priority)
        row["優先ランク"] = priority_rank(priority)
        row["信頼度"] = str(confidence_score)
        row["信頼度ラベル"] = confidence_label
        row["地合い"] = market_context.regime
        row["VIX"] = format_number(market_context.vix)
        row["日経5日騰落率(%)"] = format_number(market_context.nikkei_5d)
        row["日経20日騰落率(%)"] = format_number(market_context.nikkei_20d)
        row["地合いメモ"] = market_context.note
        row["買いシグナル"] = " / ".join(buy_signals) if buy_signals else "-"
        row["待ちシグナル"] = " / ".join(wait_signals) if wait_signals else "-"
        row["アクション"] = action
        row["アクション詳細"] = action_detail
        row["まだ待ち価格(円)"] = format_number(watch_price)
        row["買い価格(円)"] = format_number(buy_price)
        row["根拠要約"] = build_reason_summary(row, market_context, watch_price, buy_price)
        row["スコア合計"] = str(breakdown.total)
        row["最終更新日"] = date.today().isoformat()

        live_rows.append(row)

    live_rows.sort(key=lambda item: (int(item["総合優先度"]), int(item["品質スコア"])), reverse=True)

    live_fields = list(live_rows[0].keys()) if live_rows else []
    write_csv(LIVE_OUTPUT_CSV, live_rows, live_fields)

    candidate_fields = [
        "コード",
        "銘柄名",
        "業種",
        "地合い",
        "VIX",
        "日経5日騰落率(%)",
        "SBI参考価格(円)",
        "成行目安下限(円)",
        "成行目安上限(円)",
        "成行想定変動率(%)",
        "前日終値(円)",
        "前日比(%)",
        "25MA(円)",
        "75MA(円)",
        "52週高値(円)",
        "52週安値(円)",
        "配当利回り(%)",
        "PER(倍)",
        "PBR(倍)",
        "品質スコア",
        "タイミングスコア",
        "地合い加点",
        "減点",
        "総合優先度",
        "信頼度",
        "優先ランク",
        "買いシグナル",
        "待ちシグナル",
        "アクション",
        "アクション詳細",
        "最終更新日",
    ]
    candidates = [
        row
        for row in live_rows
        if row["アクション"] in {"今日の水準で1株", "前日比-3%で買い", "前日比-5%で買い", "まあ1株エントリー可", "押し目を待つ", "条件待ち", "今は買わない（高値圏）", "今は買わない（急騰後）"}
    ]
    if not candidates:
        candidates = live_rows[:10]
    write_csv(CANDIDATES_OUTPUT_CSV, candidates, candidate_fields)
    sheet_source_rows = live_rows

    # モバイルアプリで左から見える優先順: 番号→銘柄→買値→待ち→アクション→配当→MA
    sheets_fields = [
        "表示順",
        "コード",
        "銘柄名",
        "買い価格(円)",
        "まだ待ち価格(円)",
        "アクション",
        "配当利回り(%)",
        "25MA(円)",
        "75MA(円)",
        "連続増配(年)",
        "過去10年減配回数",
        "配当性向(%)",
        "直近5年で無配あり",
        "PER(倍)",
        "PBR(倍)",
        "ROE(%)",
        "更新日",
    ]
    rationale_fields = [
        "銘柄名",
        "アクション",
        "総合優先度",
        "スコア要点",
        "配当利回り(%)",
        "連続増配(年)",
        "過去10年減配回数",
        "配当性向(%)",
        "直近5年で無配あり",
        "25MA(円)",
        "75MA(円)",
        "PER(倍)",
        "PBR(倍)",
        "ROE(%)",
        "買いシグナル",
        "待ちシグナル",
        "どう動く",
        "根拠要約",
        "更新日",
    ]
    memo_fields = [
        "銘柄名",
        "朝の判断",
        "どう動く",
        "配当利回り(%)",
        "連続増配(年)",
        "過去10年減配回数",
        "配当性向(%)",
        "直近5年で無配あり",
        "25MA(円)",
        "75MA(円)",
        "PER(倍)",
        "PBR(倍)",
        "ROE(%)",
        "更新日",
    ]
    sheets_rows: list[dict[str, str]] = []
    rationale_rows: list[dict[str, str]] = []
    memo_rows: list[dict[str, str]] = []
    for index, row in enumerate(sheet_source_rows, start=1):
        sheets_rows.append(
            {
                "表示順": str(index),
                "コード": row["コード"],
                "銘柄名": row["銘柄名"],
                "買い価格(円)": row["買い価格(円)"],
                "まだ待ち価格(円)": row["まだ待ち価格(円)"],
                "アクション": row["アクション"],
                "配当利回り(%)": row["配当利回り(%)"],
                "25MA(円)": row["25MA(円)"],
                "75MA(円)": row["75MA(円)"],
                "連続増配(年)": row["連続増配(年)"],
                "過去10年減配回数": row["過去10年減配回数"],
                "配当性向(%)": row["配当性向(%)"],
                "直近5年で無配あり": row["直近5年で無配あり"],
                "PER(倍)": row["PER(倍)"],
                "PBR(倍)": row["PBR(倍)"],
                "ROE(%)": row["ROE(%)"],
                "更新日": row["最終更新日"],
            }
        )
        rationale_rows.append(
            {
                "表示順": str(index),
                "コード": row["コード"],
                "銘柄名": row["銘柄名"],
                "アクション": row["アクション"],
                "総合優先度": row["総合優先度"],
                "スコア要点": build_score_summary(row),
                "配当利回り(%)": row["配当利回り(%)"],
                "連続増配(年)": row["連続増配(年)"],
                "過去10年減配回数": row["過去10年減配回数"],
                "配当性向(%)": row["配当性向(%)"],
                "直近5年で無配あり": row["直近5年で無配あり"],
                "25MA(円)": row["25MA(円)"],
                "75MA(円)": row["75MA(円)"],
                "PER(倍)": row["PER(倍)"],
                "PBR(倍)": row["PBR(倍)"],
                "ROE(%)": row["ROE(%)"],
                "買いシグナル": row["買いシグナル"],
                "待ちシグナル": row["待ちシグナル"],
                "どう動く": row["アクション詳細"],
                "根拠要約": row["根拠要約"],
                "更新日": row["最終更新日"],
            }
        )
        memo_rows.append(
            {
                "銘柄名": row["銘柄名"],
                "朝の判断": row["アクション"],
                "どう動く": build_morning_note(row),
                "配当利回り(%)": row["配当利回り(%)"],
                "連続増配(年)": row["連続増配(年)"],
                "過去10年減配回数": row["過去10年減配回数"],
                "配当性向(%)": row["配当性向(%)"],
                "直近5年で無配あり": row["直近5年で無配あり"],
                "25MA(円)": row["25MA(円)"],
                "75MA(円)": row["75MA(円)"],
                "PER(倍)": row["PER(倍)"],
                "PBR(倍)": row["PBR(倍)"],
                "ROE(%)": row["ROE(%)"],
                "更新日": row["最終更新日"],
            }
        )
    write_csv(SHEETS_OUTPUT_CSV, sheets_rows, sheets_fields)
    write_csv(RATIONALE_OUTPUT_CSV, rationale_rows, rationale_fields)
    write_csv(MEMO_OUTPUT_CSV, memo_rows, memo_fields)
    HTML_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    HTML_OUTPUT.write_text(build_html(sheets_rows, market_context), encoding="utf-8")
    SUMMARY_OUTPUT.write_text(build_summary(sheet_source_rows, market_context), encoding="utf-8")

    print(f"Wrote {LIVE_OUTPUT_CSV}")
    print(f"Wrote {CANDIDATES_OUTPUT_CSV}")
    print(f"Wrote {SHEETS_OUTPUT_CSV}")
    print(f"Wrote {RATIONALE_OUTPUT_CSV}")
    print(f"Wrote {MEMO_OUTPUT_CSV}")
    print(f"Wrote {HTML_OUTPUT}")
    print(f"Wrote {SUMMARY_OUTPUT}")


if __name__ == "__main__":
    main()
