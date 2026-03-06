# 株スクリーニング作業場

ZIP の内容を、このワークスペースで継続運用しやすい形に整理した作業場です。

## 構成

- `docs/rules/`
  - 元の運用ルール一式
- `docs/system_blueprint.md`
  - 実装用の設計図
- `docs/data_dictionary.md`
  - CSV 列定義と運用メモ
- `data/watchlist.csv`
  - 監視銘柄リストの原本
- `data/purchases.csv`
  - 購入・売却履歴
- `data/dividends.csv`
  - 配当履歴
- `scripts/score_watchlist.py`
  - 監視銘柄リストをルールに沿って採点する下準備スクリプト
- `scripts/build_morning_candidates.py`
  - 朝の数値取得、候補絞り込み、CSV 出力
- `scripts/run_morning_job.ps1`
  - Windows から実行しやすい朝バッチ入口
- `data/sheets_candidates.csv`
  - Google スプレッドシートに入れやすい列順の一覧
- `reports/dashboard.html`
  - スマホでも見やすい簡易ダッシュボード

## 使い方の基本

1. `docs/rules/README.md` から全体像を確認
2. `docs/system_blueprint.md` で実装方針を確認
3. `data/watchlist.csv` に指標を埋める
4. `python scripts/score_watchlist.py` でスコア計算する
5. `powershell -ExecutionPolicy Bypass -File scripts/run_morning_job.ps1` で朝の候補 CSV を更新する

## 補足

- この作業場は投資助言ではなく、手元ルールの整理と自動化準備を目的としています。
- 元 ZIP の展開物は `tmp_stock_screening/` に残しています。
