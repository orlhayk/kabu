# 今ある武器

今この作業場で使えるものを、実務ベースでまとめる。

## 1. ルール本体

- [`docs/rules/設計書.md`](/Users/81908/Documents/Playground/docs/rules/設計書.md)
  - 100点満点の採点基準
- [`docs/rules/買いルールブック.md`](/Users/81908/Documents/Playground/docs/rules/買いルールブック.md)
  - いつ買うかの判断
- [`docs/rules/売り・撤退ルール.md`](/Users/81908/Documents/Playground/docs/rules/売り・撤退ルール.md)
  - いつ売るかの例外条件
- [`docs/rules/ポートフォリオ管理ルール.md`](/Users/81908/Documents/Playground/docs/rules/ポートフォリオ管理ルール.md)
  - 偏り管理

## 2. 元データ

- [`data/watchlist.csv`](/Users/81908/Documents/Playground/data/watchlist.csv)
  - 監視銘柄の原本
- [`data/purchases.csv`](/Users/81908/Documents/Playground/data/purchases.csv)
  - 売買記録
- [`data/dividends.csv`](/Users/81908/Documents/Playground/data/dividends.csv)
  - 配当記録

## 3. 朝バッチで増えるデータ

- [`data/watchlist_live.csv`](/Users/81908/Documents/Playground/data/watchlist_live.csv)
  - 当日価格、移動平均、52週高値安値、採点込みの一覧
- [`data/sbi_candidates.csv`](/Users/81908/Documents/Playground/data/sbi_candidates.csv)
  - SBIで朝見る用の候補だけを抜いた一覧

## 4. 実行コマンド

- `python scripts/score_watchlist.py`
  - 監視銘柄を採点
- `powershell -ExecutionPolicy Bypass -File scripts/run_morning_job.ps1`
  - 朝の数字取得と候補CSV更新

## 5. 今できること

- 監視銘柄の朝の価格更新
- 25MA / 75MA / 52週レンジ確認
- 配当利回り、PER、PBR、ROE、営業利益率の自動取得
- 自動スコア計算
- SBIで見る優先順のCSV出力

## 6. まだ足りないもの

- 決算予定日
- 権利確定日
- 保有株数
- 上場年数
- 無配転落歴
- 業種内比較用のPER平均

この不足分を足すと、候補精度はかなり上がる。
