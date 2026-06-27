# APIリファレンス — ラボAIナレッジエージェント

ベースURL（ローカル）: `http://localhost:8000`  
すべてのリクエストボディのContent-Type: `application/json`  
CORSはハッカソン用に全オリジン（`*`）で開放されています。

サーバー起動中はインタラクティブなドキュメントも利用できます：
- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)

このドキュメントがAPIの仕様書です。Pythonのコードを読まなくてもフロントエンド開発が可能です。

---

## 共通ルール

- JSONレスポンスはWindows PowerShellの `Invoke-WebRequest` / `curl`
  エイリアスでも日本語を正しく表示できるよう、UTF-8を明示します
  （`application/json; charset=utf-8`）。
- フロントエンドは**使わないフィールドを無視してOK** — すべてのフィールドは常に含まれるため、バックエンドとフロントエンドは独立して開発できます。
- タイムスタンプはISO-8601 UTC形式です（例: `2026-06-27T09:30:00+00:00`）。

---

## `POST /ask`

メインのRAGエンドポイント。ラボの資料から質問に回答し、出典・信頼度スコア・ビジュアルハイライトデータ・ナレッジギャップフラグを返します。

### リクエストボディ
| フィールド | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `message` | string | はい | ユーザーの質問（言語不問、日本語推奨） |
| `session_id` | string | いいえ | セッションID。高度パスでの会話履歴管理に使用 |
| `current_state` | object | いいえ | フロントエンドのUI状態。`active_figure_id` を読み取る |
| `current_state.active_figure_id` | string | いいえ | ユーザーが見ている図のID。指定なければ `panel_01` を使用 |

```json
{
  "message": "輝度つまみはどこですか？",
  "session_id": "session_98765",
  "current_state": { "active_figure_id": "panel_01" }
}
```

### レスポンスボディ
| フィールド | 型 | 説明 |
|-----------|-----|------|
| `answer_text` | string | 根拠のある回答。`is_gap` が true の場合は「記録なし」メッセージ |
| `next_step_hint` | string \| null | advancedパスの次アクション提案。easyパスとギャップ時は `null` |
| `visual_data` | object \| null | ハイライトする図・ホットスポットの情報 |
| `visual_data.figure_id` | string \| null | アクティブな図のID（リクエストの値またはデフォルト） |
| `visual_data.highlight_item` | string \| null | ハイライトするホットスポット名。なければ `null` |
| `citations` | array | 回答の根拠となった出典。`is_gap` が true の場合は空配列 |
| `citations[].source` | string | 出典ドキュメント名（例: ファイル名） |
| `citations[].snippet` | string | 出典からの抜粋（300文字以内） |
| `confidence` | number | 根拠あり回答の検索スコア。ギャップ時は `0.0` |
| `is_gap` | boolean | **本システムの特徴機能。** `true` = 資料に答えなし。質問は `/gaps` に記録される |

**回答ありの場合:**
```json
{
  "answer_text": "照射系を調整するには、パネル右上の輝度つまみを時計回りに回します。",
  "next_step_hint": "次に、対物レンズのフォーカスを確認してください。",
  "visual_data": { "figure_id": "panel_01", "highlight_item": "輝度つまみ" },
  "citations": [
    { "source": "顕微鏡マニュアル.pdf", "snippet": "輝度つまみはパネル右上にあり…" }
  ],
  "confidence": 0.82,
  "is_gap": false
}
```

### ナレッジギャップレスポンス（本システムの特徴的な動作）
検索スコアが `GAP_THRESHOLD`（デフォルト `0.20`）を下回る場合、またはスコアが高くてもSonnetが資料に直接の根拠がないと判定した場合、ナレッジギャップになります。低スコア時は生成を行わず、モデル判定によるギャップでは生成した下書きと出典を破棄します。どちらも正直なメッセージ、`is_gap: true`、`confidence: 0.0`、空の `citations` を返し、質問を記録します。

```json
{
  "answer_text": "ご質問の内容は、まだ研究室の資料に記録されていないようです。この質問は記録しましたので、先生が後で確認できます。お急ぎの場合は、先輩や先生に直接確認することをおすすめします。",
  "next_step_hint": null,
  "visual_data": { "figure_id": "panel_01", "highlight_item": null },
  "citations": [],
  "confidence": 0.0,
  "is_gap": true
}
```

### 有効な図IDとホットスポット名
`highlight_item` は必ず以下のいずれかの値か `null` になります：

| `figure_id` | 有効な `highlight_item` |
|-------------|------------------------|
| `panel_01` | 輝度つまみ, 対物レンズ, フォーカスノブ, ステージ, 電源スイッチ |
| `microscope_overview` | 接眼レンズ, 対物レンズ, ステージ, 光源, 粗動ハンドル, 微動ハンドル |
| `control_panel` | 電源スイッチ, 輝度つまみ, シャッターボタン, 緊急停止ボタン |

---

## `GET /gaps`

検出されたナレッジギャップを一覧表示します（質問回数が多い順）。教授のレビューダッシュボード向けです。

### レスポンスボディ
| フィールド | 型 | 説明 |
|-----------|-----|------|
| `gaps` | array | 検出されたギャップの一覧 |
| `gaps[].question` | string | 資料に答えがなかった質問 |
| `gaps[].count` | integer | 質問された回数（同じ文章は重複カウントなし） |
| `gaps[].first_seen` | string | 最初に質問されたISO-8601 UTCタイムスタンプ |

```json
{
  "gaps": [
    { "question": "懇親会の予算は？", "count": 3, "first_seen": "2026-06-27T09:30:00+00:00" },
    { "question": "古い液体窒素タンクの場所は？", "count": 1, "first_seen": "2026-06-27T10:05:00+00:00" }
  ]
}
```

---

## `POST /onboarding`

ラボの資料をもとに、役割別のオンボーディングガイドを生成します。

### リクエストボディ
| フィールド | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `role` | string | はい | `"M1"` または `"D1"` |
| `field` | string | いいえ | 研究分野（ガイドの内容を調整するために使用） |

```json
{ "role": "M1", "field": "光学" }
```

### レスポンスボディ
| フィールド | 型 | 説明 |
|-----------|-----|------|
| `guide` | string | 生成されたオンボーディングガイド（日本語）、ラボ資料に基づく |

```json
{ "guide": "M1向けオンボーディングガイド\n\n1. 最初の1週間でやるべきこと…" }
```

---

## `GET /faq`

よくある質問と回答を返します。

### レスポンスボディ
| フィールド | 型 | 説明 |
|-----------|-----|------|
| `items` | array | FAQエントリーの一覧 |
| `items[].q` | string | 質問 |
| `items[].a` | string | 回答 |

```json
{
  "items": [
    { "q": "研究室のコアタイムは何時ですか？", "a": "コアタイムは研究室の資料を確認してください。" }
  ]
}
```

---

## `POST /feedback`

回答へのサムズアップ/サムズダウンを記録します。

### リクエストボディ
| フィールド | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `session_id` | string | はい | フィードバック対象のセッションID |
| `message` | string | はい | 評価対象の質問・回答 |
| `rating` | string | はい | `"up"` または `"down"` |
| `note` | string | いいえ | 任意のフリーテキストコメント |

```json
{ "session_id": "session_98765", "message": "輝度つまみはどこですか？", "rating": "up", "note": "分かりやすかった" }
```

### レスポンスボディ
| フィールド | 型 | 説明 |
|-----------|-----|------|
| `ok` | boolean | 成功時は常に `true` |

```json
{ "ok": true }
```

---

## `GET /health`

サーバーの死活確認。AWSへの通信なし — 頻繁にポーリングしても問題ありません。

### レスポンスボディ
```json
{ "status": "ok" }
```

---

## `GET /ready`

LLMを呼び出さず、ローカルデータベースとプロバイダー設定を確認します。

```json
{
  "status": "ready",
  "mode": "live",
  "database": "ok",
  "provider": "configured"
}
```

依存関係に問題がある場合、`status` は `degraded` になります。

---

## エラーについて

- バリデーションエラー（フィールド不正・欠落）は **HTTP 422** とFastAPIの標準エラーボディを返します。
- Bedrockに接続できない場合（KBが未同期、リージョン誤り、モデルアクセス未設定）でも、`/ask` と `/onboarding` は **HTTP 200** とフォールバックメッセージを返します。デモ中も動作が止まらないようにするための設計です — ステータスコードではなく `is_gap` / `answer_text` の内容で判断してください。
- フィードバックを保存できない場合、`/feedback` は **HTTP 503**、ギャップを読み込めない場合、`/gaps` は **HTTP 503** を返します。
- 不明な図ID、空文字、未対応のrole/ratingは **HTTP 422** を返します。
