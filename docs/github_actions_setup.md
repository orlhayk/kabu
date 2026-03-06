# GitHub Actions Setup

この workflow は [`morning-stock-screen.yml`](/Users/81908/Documents/Playground/.github/workflows/morning-stock-screen.yml) を使って、平日 08:00 JST に朝更新を走らせます。

## 必要な GitHub Secrets

- `GOOGLE_OAUTH_CLIENT_JSON`
  - `secrets/google-oauth-client.json` の中身をそのまま入れる
- `GOOGLE_TOKEN_JSON`
  - `secrets/google-token.json` の中身をそのまま入れる

## やること

1. このリポジトリを GitHub に push する
2. GitHub の `Settings > Secrets and variables > Actions` を開く
3. 上の 2 つの secret を追加する
4. `Actions` タブで `Morning Stock Screen` を有効にする
5. 必要なら `Run workflow` で手動実行する

## 補足

- workflow の cron は `UTC` なので、`08:00 JST` は `23:00 UTC` 前日です
- 今の実装は既存の Google OAuth token を使います
- token を Google 側で失効した場合は、ローカルで再認証して `GOOGLE_TOKEN_JSON` を更新してください
