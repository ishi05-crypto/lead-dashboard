# 公開手順（GitHub + Vercel + Neon + CloudMailin）

**どのメールアドレスでも「転送」さえできれば** 案件メールを自動で取り込めるようにする手順です。
費用は各サービスの無料枠を想定しています（無料枠の内容は変わることがあるので、各サービスの料金ページで確認してください）。

```
案件メールが届く受信箱（Gmail / Outlook / レンタルサーバー 等、何でも可）
   │ ① 送信元ドメインで絞って自動転送
   ▼
CloudMailin（xxxx@cloudmailin.net。受け取ったメールを Webhook に変換）
   │ ② POST https://<アプリ>.vercel.app/api/ingest?token=<合言葉>
   ▼
Vercel（api/ingest.py → 解析 → 保存）  ──→  Neon（PostgreSQL）
                                              ▲
ダッシュボード https://<アプリ>.vercel.app ───┘ ③ /api/leads（ID・パスワード付き）
```

作業は上から順に行ってください。所要時間は30〜40分ほどです。

---

## 1. GitHub にコードを置く

1. GitHub で空のリポジトリを作ります（例: `lead-dashboard`）。**Private（非公開）** を推奨します。
2. このフォルダーを push します（Claude に依頼する場合は、リポジトリ名を伝えてください）。
3. push すると、GitHub Actions がテスト（SQLite / PostgreSQL の両方）を自動で実行します。

## 2. Vercel にデプロイする

1. https://vercel.com に GitHub アカウントでログインします。
2. **Add New → Project** → 手順1のリポジトリを **Import**。
3. Framework Preset は **Other** のままにします。Build Command / Output Directory は空欄で構いません（`vercel.json` で設定済み）。
4. **Deploy** を押します。`https://<プロジェクト名>.vercel.app` が発行されます。
   この時点では、画面を開くと「DASHBOARD_PASSWORD が未設定です」と表示されます（正常です）。

## 3. データベース（Neon）をつなぐ

1. Vercel のプロジェクト画面 → **Storage** → **Create Database** → **Neon (Postgres)** を選びます。
   リージョンは、日本に近い場所（Tokyo や Singapore など、選べるもの）を選びます。
2. 作成するとプロジェクトに接続され、環境変数 `DATABASE_URL` が自動で追加されます。
   （`POSTGRES_URL` という名前で追加された場合も、そのまま使えます）
3. テーブルは、最初のアクセス時に自動で作られます。

## 4. 環境変数（合言葉・ログイン情報）を設定する

Vercel のプロジェクト → **Settings → Environment Variables** に、次の3つを追加します。

| 名前 | 値の例 | 用途 |
|---|---|---|
| `INGEST_TOKEN` | 長いランダム文字列（下のコマンドで作成） | メール取り込み口の合言葉。CloudMailin の URL に含める |
| `DASHBOARD_USER` | `admin` など | ダッシュボードのログイン ID |
| `DASHBOARD_PASSWORD` | 推測されにくいパスワード | ダッシュボードのパスワード |

ランダム文字列は、次のコマンドで作れます。

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(24))"
```

追加したら、**Deployments → 最新のデプロイ → Redeploy** を実行して反映させます。
その後ダッシュボードを開き、ID・パスワードを入力して空の一覧が出れば成功です。

## 5. CloudMailin で受信用アドレスを作る

1. https://www.cloudmailin.com でアカウントを作成し、Free プランを選びます。
2. 受信用アドレス（例: `1a2b3c4d5e@cloudmailin.net`）が発行されます。**このアドレスを控えておきます。**
3. アドレスの設定画面で、次のとおり設定します。
   - **Target URL**: `https://<プロジェクト名>.vercel.app/api/ingest?token=<INGEST_TOKEN の値>`
   - **POST Format**: **Raw**（Multipart - Raw）を選択します。
     JSON 形式でも取り込めますが、Raw の方がメールの内容をそのまま保存できます。
4. 動作確認として、普段使いのメールから控えたアドレス宛てに、試しにメールを送ります。
   ダッシュボードに「未判別」として1件出れば、経路はつながっています。
   確認後、そのテスト行は状態を「対象外」にしておきます。

## 6. 受信箱から自動転送を設定する

送信元ドメインが次のどれかのメールだけを、手順5で控えたアドレスに転送します（案件以外のメールを外部に送らないため）。

```
partner.rits-orange.jp
oniwa.link329.com
ibaraki.hayabusa-oniwa.com
kanagawa.hayabusa-oniwa.com
call.omnidatabank.jp
rehome-navi.com
```

### Gmail / Google Workspace

1. 設定 → **転送と POP/IMAP** → **転送先アドレスを追加** に、CloudMailin のアドレスを入力します。
2. Google から確認メールが送られます。このメールはダッシュボードに「未判別」として届くので、
   件名または備考欄の **確認コード** を Gmail の画面に入力します（または備考欄のリンクを開きます）。
3. 「すべての受信メールを転送」は **選ばず**、フィルタで絞ります。
   検索欄に次を入力 → **フィルタを作成** → **次のアドレスに転送する** にチェックを入れます。
   ```
   from:(partner.rits-orange.jp OR oniwa.link329.com OR ibaraki.hayabusa-oniwa.com OR kanagawa.hayabusa-oniwa.com OR call.omnidatabank.jp OR rehome-navi.com)
   ```
   Google Workspace では、管理者が外部への自動転送を禁止していることがあります。その場合は管理者に許可を依頼してください。

### Outlook / Microsoft 365

1. 設定 → メール → **ルール** → 新しいルールを追加します。
2. 条件「差出人のアドレスに次の文字列が含まれる」に、上記の6ドメインを登録します。
3. アクションは **リダイレクト**（元の差出人が残るため、転送よりこちらを推奨）で、CloudMailin のアドレスを指定します。
   Microsoft 365 は、初期設定で外部への自動転送がブロックされていることがあります。その場合は管理者に、送信スパムポリシーで自動転送を許可してもらう必要があります。

### レンタルサーバーのメール（Xserver、さくら、ロリポップ 等）

コントロールパネルの「メール転送」や「振り分け設定」で、差出人が上記ドメインのメールを CloudMailin のアドレスに転送します。
差出人で振り分けできない場合は全件転送でも動作します（案件以外のメールは「未判別」に入ります）。

### 送信元が判別されなかった場合

転送の方式によって差出人が書き換わっても、本文の特徴（「取次日時」「計測番号＋入電ID」など）から送客元を判定します。
それでも「未判別」になる場合は、`mail_dashboard/parsers.py` の `BODY_SIGNATURES` に特徴を追加し、
`python3 manage.py reparse` で保存済みのメールを再解析できます（`DATABASE_URL` を設定して実行すると本番 DB が対象になります）。

---

## デモ用にサンプルを入れる（任意）

同梱のサンプルメール8通を、本番の取り込み口に送ります（CloudMailin を経由しない直接投入です）。

```bash
for f in samples/*.eml; do curl -sS -X POST -H "Content-Type: message/rfc822" --data-binary @"$f" "https://<プロジェクト名>.vercel.app/api/ingest?token=<INGEST_TOKEN>"; echo; done
```

デモ用のサンプルを消したい場合は、状態を「対象外」にするか、Neon の管理画面（SQL Editor）で次を実行します。

```sql
DELETE FROM leads WHERE message_id LIKE '%@sample>';
```

## セキュリティ上の注意

- 顧客の氏名・電話番号を扱います。`DASHBOARD_PASSWORD` は必ず設定してください（未設定の間、API はデータを返しません）。
- `INGEST_TOKEN` を知っている人は、誰でもデータを送り込めます。漏れた場合は値を変更し、CloudMailin の Target URL も更新してください。
- 合言葉や DB の接続情報は Vercel の環境変数にだけ置き、GitHub には絶対にコミットしないでください（`.env*` は `.gitignore` 済み）。
