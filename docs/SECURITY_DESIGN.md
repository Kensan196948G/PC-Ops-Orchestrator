# セキュリティ設計 — v1.0

本ドキュメントは v1.0 (2026-10-28 リリース) で維持すべきセキュリティ不変条件を定義する。
詳細な脅威モデルは `docs/セキュリティ.md` を参照。

## 1. 永続的不変条件 (リリース後も変更不可)

| カテゴリ | 不変条件 | 根拠 |
|---|---|---|
| 監査 | `audit_logs` 削除不可 (DELETE API/ロール禁止) | J-SOX / ISO 27001 改ざん防止要件 |
| Agent | Pull 型のみ (サーバー→Agent 能動接続禁止) | 内部ネットワーク隔離維持 |
| 実行 | PowerShell テンプレート制 (自由実行禁止) | 任意コード実行リスク低減 |
| XSS | `innerHTML` 動的禁止 (textContent/escapeHTML 必須) | OWASP A03:2021 |
| ログ | 機密情報 (PW/Token/APIKey) ログ禁止 | 情報漏洩防止 |
| 認証 | 認証なしエンドポイント追加禁止 | API 表面攻撃面最小化 |

## 2. CSP (Content Security Policy)

```
default-src 'self';
script-src 'self' 'nonce-{nonce}';
style-src 'self';
img-src 'self' data:;
font-src 'self' data:;
connect-src 'self';
frame-ancestors 'none';
base-uri 'self';
form-action 'self';
```

- CDN 配信禁止 (`.js.map` 自動 fetch が `connect-src 'self'` を破る)
- `unsafe-inline` 禁止 (Phase 3 完了済)
- nonce はリクエスト毎に再生成

## 3. セキュリティヘッダー

| ヘッダ | 値 |
|---|---|
| X-Content-Type-Options | nosniff |
| X-Frame-Options | DENY |
| X-XSS-Protection | 1; mode=block |
| Referrer-Policy | strict-origin-when-cross-origin |
| Permissions-Policy | geolocation=(), camera=(), microphone=(), payment=() |
| Strict-Transport-Security | max-age=31536000; includeSubDomains (production のみ) |

## 4. リスク 3 段階分類 (Phase B-2)

| レベル | 例 | 承認要件 |
|---|---|---|
| low | キャッシュクリア / 再起動 | operator 即時実行可 |
| medium | ソフトウェア配布 / グループポリシー更新 | admin 1 名承認 |
| high | レジストリ編集 / ユーザー削除 | admin 2 名承認 + 監査タグ |

## 5. 認証・認可

- JWT (HS256) + Refresh Token
- bcrypt password (cost=12)
- ロール: admin / operator / viewer
- 一括権限変更は監査ログに記録

## 6. DB セキュリティ

- Alembic マイグレーション必須 (手動 ALTER 禁止)
- SECRET_KEY / JWT_SECRET_KEY / AGENT_API_KEYS は `_require_secret` 経由で検証
- production では insecure default (changeme 等) を起動時拒否

## 7. レビュー必須項目 (PR チェックリスト)

- [ ] 新規エンドポイントに認証 decorator がついているか
- [ ] CSP nonce を壊していないか
- [ ] innerHTML 動的代入が混入していないか
- [ ] 監査対象操作に `log_audit()` 呼び出しがあるか
- [ ] DB 変更があれば Alembic migration が含まれているか
- [ ] 秘密情報がログ・コミットに含まれていないか
