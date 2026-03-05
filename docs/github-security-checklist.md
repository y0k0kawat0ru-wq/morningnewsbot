# GitHub セキュリティ設定チェックリスト

本ドキュメントはリポジトリのセキュリティ設定を確認・強化するための運用手順書です。
各項目を順番にチェックし、未対応のものは対応してください。

---

## 1. Branch Protection（main / master ブランチ）

GitHub の Settings → Branches → Branch protection rules で設定します。

- [ ] **直接pushの禁止** — main/master ブランチへの直接pushを禁止し、Pull Request 経由のみとする
- [ ] **PR必須化** — "Require a pull request before merging" を有効にする
- [ ] **Force push の禁止** — "Allow force pushes" を無効（デフォルト）にする
- [ ] **Required status checks** — lint / test などのCIチェックを必須にする（"Require status checks to pass before merging"）
- [ ] **Required review** — 最低1名のレビュー承認を必須にする（"Require approvals" → 1以上）
- [ ] **管理者にもルール適用** — "Do not allow bypassing the above settings" を有効にする（推奨）

---

## 2. Secret Scanning / Push Protection

GitHub の Settings → Code security and analysis で設定します。

### 有効化の確認

- [ ] **Secret scanning** が有効になっていることを確認する
- [ ] **Push protection** が有効になっていることを確認する（シークレットを含むpushを自動ブロック）

### 検知時の初動対応

- [ ] **キーの即時失効** — 検知されたAPIキー・トークンを発行元サービスで直ちに無効化する
- [ ] **新しいキーの発行** — 失効後、新しいキーを発行し環境変数またはシークレットストアに格納する
- [ ] **履歴からの削除は慎重に** — `git filter-branch` や BFG Repo-Cleaner による履歴削除は影響が大きいため、チームで判断する
- [ ] **再発防止** — `.gitignore` にシークレットファイルパターンが含まれているか再確認する
- [ ] **アラート対応の記録** — いつ・何が・どう対応されたかを記録する

### push前のローカル点検（追跡済みシークレットの確認）

> **重要：** `.gitignore` に追加しても、すでに `git add` / `git commit` で追跡されているファイルには効果がありません。追跡済みファイルに秘密情報が含まれていないか、push前に必ず確認してください。

- [ ] **追跡中ファイルの確認** — 以下のコマンド（提案）で、追跡中のファイルに秘密情報ファイルが含まれていないか確認する
  ```bash
  # .env / token / credential / secret を含むファイル名を検索（提案）
  git ls-files | grep -iE '\.env|token|credential|secret|webhook'
  ```
- [ ] **ソースコード内のキーワード検索** — 以下のコマンド（提案）で、ハードコードされた秘密情報がないか確認する
  ```bash
  # API_KEY, SECRET, TOKEN, WEBHOOK, 秘密鍵ヘッダーを検索（提案）
  git grep -n -iE 'API_KEY|SECRET_KEY|PRIVATE_KEY|TOKEN|WEBHOOK|-----BEGIN'
  ```
- [ ] **見つかった場合の初動：**
  1. 該当キー・トークンを発行元サービスで即時失効させる
  2. Discord Webhook が露出していた場合は Webhook を再発行する
  3. 影響範囲（どのサービス・データに影響するか）を確認する
  4. `git rm --cached <ファイル名>` で追跡を解除し、`.gitignore` に追加する
  5. git履歴からの削除（`git filter-branch` / BFG）は影響が大きいため慎重に判断する

---

## 3. Dependabot（依存パッケージの自動更新）

### 有効化手順

- [ ] GitHub の Settings → Code security and analysis → Dependabot alerts を有効にする
- [ ] Dependabot security updates を有効にする（脆弱性のあるパッケージの自動PR作成）

### 設定ファイルの配置（提案）

以下は `.github/dependabot.yml` の設定案です。リポジトリに合わせて調整してください。

```yaml
# .github/dependabot.yml（提案）
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 5
    labels:
      - "dependencies"
      - "security"
    # 必要に応じて GitHub Actions も追加
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
    labels:
      - "dependencies"
```

- [ ] 上記設定を参考に `.github/dependabot.yml` を作成する
- [ ] Dependabot が生成した PR を定期的に確認・マージする運用ルールを決める

---

## 4. GitHub Actions の権限最小化

### GITHUB_TOKEN の権限設定

- [ ] **リポジトリ設定で制限** — Settings → Actions → General → "Workflow permissions" を "Read repository contents and packages permissions" に設定する
- [ ] **ワークフローごとに明示指定** — 各ワークフローファイル（`.github/workflows/*.yml`）で `permissions` を明示的に指定する

```yaml
# 例：最小権限の指定
permissions:
  contents: read    # リポジトリ内容の読み取りのみ
  # 必要に応じて追加（write は必要最小限に）
```

- [ ] `permissions: write-all` や無制限の設定がないことを確認する

### Secrets の取り扱い

- [ ] シークレットは Settings → Secrets and variables → Actions で管理する
- [ ] ワークフローログにシークレットが出力されないことを確認する（`::add-mask::` の活用）
- [ ] 不要になったシークレットは速やかに削除する
- [ ] 環境（Environment）ごとにシークレットを分離する（dev / staging / production）

---

## 5. リリース前点検

### 依存パッケージの監査

- [ ] **pip の場合** — `pip audit` または `safety check` で既知の脆弱性を確認する
- [ ] **npm の場合** — `npm audit` で既知の脆弱性を確認する
- [ ] 脆弱性が検出された場合、重大度に応じて修正またはリスク受容の判断を行う

### 秘密情報の混入確認

- [ ] `.env` ファイルがリポジトリに含まれていないことを確認する（`git ls-files | grep -i env`）
- [ ] APIキー・トークンがソースコードにハードコードされていないことを確認する
- [ ] `git log --all -p | grep -i "api_key\|token\|secret\|password"` で履歴を簡易チェックする（大規模リポジトリでは時間がかかるため注意）

### Discord Webhook の露出確認

- [ ] Discord Webhook URL がソースコードやコミット履歴に含まれていないことを確認する
- [ ] Webhook URL は環境変数経由で読み込む設計になっていることを確認する
- [ ] `.gitignore` に `*webhook*` パターンが含まれていることを確認する

---

## 6. インシデント時の止血手順（10分でやること）

セキュリティインシデント（キー漏洩、不正アクセスなど）が発生した場合の初動手順です。

### 即座に実行（0〜5分）

- [ ] **漏洩したキー・トークンの即時失効** — 発行元サービス（J-Quants, Discord, GitHub 等）の管理画面でキーを無効化する
- [ ] **Discord Webhook の再発行** — 漏洩した Webhook を削除し、新しい Webhook URL を発行する
- [ ] **GitHub Personal Access Token の再発行** — Settings → Developer settings → Personal access tokens で該当トークンを Revoke する

### 被害範囲の確認（5〜10分）

- [ ] **権限の見直し** — 漏洩したキーに紐づく権限スコープを確認し、不正利用の可能性を評価する
- [ ] **ログの確認** — 各サービスのアクセスログ・監査ログを確認し、不審なアクティビティがないか調べる
- [ ] **影響範囲の特定** — どのリポジトリ・サービス・データが影響を受けた可能性があるかリストアップする

### 事後対応（10分以降）

- [ ] **新しいキーの設定** — 新しいキーを発行し、環境変数・シークレットストアに格納する
- [ ] **再発防止策の実施** — `.gitignore` の確認、Secret scanning の有効化確認、運用ルールの見直し
- [ ] **インシデント記録の作成** — 発生日時、原因、影響範囲、対応内容、再発防止策を文書化する

---

## 更新履歴

| 日付 | 内容 |
|------|------|
| 2026-03-05 | 初版作成 |
