# Changelog

All notable changes to PC-Ops Orchestrator are documented in this file.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
Versioning: [Semantic Versioning](https://semver.org/)

---

## [Unreleased] — M6 リリース準備中

### Added (M6 進行中)
- **CSP Phase 2** (Issue #121, PR #129)
  - 全 16 テンプレートのインラインハンドラ (`onclick/oninput/onchange/onsubmit`) を外部 JS の `addEventListener` に完全移行
  - `stub-actions.js` 新規作成 — `data-stub-alert` 属性でアラートスタブを共通管理
  - `script-src` から `'unsafe-inline'` を除去 (Phase 1 → Phase 2 完了)
  - `test_csp_script_src_uses_nonce_not_unsafe_inline` — strict 版テスト追加

### Fixed
- **N+1 クエリ解消** (Issue #121, PR #130)
  - `alerts.py` / `tasks.py` CSV エクスポートで `joinedload(*.pc)` 追加
  - 最大 5000 行エクスポート時のクエリ数: 5001 → 2 に削減
- **groups.py N+1 解消** (PR #131)
  - `GET /api/groups` で N グループ × 1 COUNT クエリ → 2 クエリに削減
  - `PCGroup.to_dict()` に `pc_count` オプション引数を追加
  - `create_group()` のログ内 `group.pcs.count()` を `len(pc_names)` に置換
- **Alert.pc relationship 欠落バグ修正** (PR #131)
  - `PC.alerts` relationship (backref="pc") を追加
  - `joinedload(Alert.pc)` が AttributeError になる本番バグを解消

### Added
- **テストカバレッジ拡張** (PR #131): `test_coverage_boost.py` — 46 件追加
  - alerts CSV エクスポート (BOM・Content-Type・フィルタ)
  - tasks CSV エクスポート
  - groups CRUD エラーケース (400/404/409)
  - セキュリティヘッダ検証 (CSP strict, X-Frame-Options, Referrer-Policy)
  - 合計テスト数: 205 → 251 件

### Planned
- CHANGELOG / GitHub Release v0.6.0 タグ
- style-src 'unsafe-inline' Phase 3 (CSS inline style 外部化)

---

## [0.5.0] — 2026-05-06 — M5 完了

### Added
- **M5-3 月次レポート API** (Issue #76, PR #116)
  - `GET /api/reports/monthly` — PC/タスク/アラート/SLA 集計 JSON
  - `GET /api/reports/monthly/list` — 過去 N ヶ月アーカイブ
  - `GET /api/reports/monthly/export.csv` — UTF-8 BOM CSV ダウンロード
  - `GET /api/reports/monthly/export.pdf` — IPA Gothic 日本語 PDF (reportlab)
  - `reports.html` をダミーデータから実 API 接続に更新
- **M5-5 ユーザー管理 WebUI 強化** (Issue #78, PR #117)
  - ログイン失敗 5 回でアカウント自動ロック
  - `POST /api/auth/users/<id>/unlock` — ロック解除 API (admin のみ)
  - パスワードポリシー強化: 大小英字+数字+記号+8文字以上
  - ユーザー一覧: 最終ログイン / 失敗回数 / ロック状態 カラム追加
  - パスワード入力欄: リアルタイム強度インジケーター
  - Flask-Migrate: `users` テーブルに 4 カラム追加 (DB マイグレーション)
- **E2E テスト追加** (PR #120): 月次レポートページ + ユーザー強化 (6 件)
- **OpenAPI v1.1.0**: reports/* + unlock エンドポイント追加

### Changed
- User モデル: `last_login`, `failed_login_count`, `is_locked`, `locked_at` 追加
- `requirements.txt`: `reportlab==4.2.5` 追加

---

## [0.4.0] — 2026-05-06 — XSS 防御 / セキュリティ強化

### Security
- **innerHTML XSS 防御 Step 2** (Issue #102, PR #114)
  - `tasks.js`: 7 値を `escapeHTML()` でラップ
  - `dashboard.js`: 4 値を `escHtml()` でラップ
  - `pc_detail.js`: 5 値を `escapeHTML()` でラップ
- **Security Headers 強化** (Issue #101, PR #103)
  - `Content-Security-Policy` / `Strict-Transport-Security` (本番のみ) / `Permissions-Policy`
- **9 CVE 全件解消** (Issue #87, PR #100 + #105)
  - Flask 3.1.3 / PyJWT 2.12.0 / Werkzeug 3.1.6 / python-dotenv 1.2.2 / flask-cors 6.0.0

### Added
- `window.escapeHTML` ヘルパを `base.html` に追加 (PR #109)

---

## [0.3.0] — 2026-05-06 — M5 UI 強化 / ダークモード

### Added
- **M5-4 ダークモード + WCAG 2.1 AA** (Issue #77, PR #107)
  - CSS Variables `[data-theme="dark"]` トークン体系
  - Topbar トグルボタン (sun/moon アイコン)
  - FOUC 防止 inline script
  - E2E 6 件追加
- **Topbar + Sidebar Badge** (Issue #93, PR #94)
  - 検索 (⌘K) / 環境ピル / 通知バッジ / 同期ボタン / タスク作成
  - Sidebar カウントバッジ (PC/Alert/Task)
- **Claude Design WebUI** (Issue #88, PR #89)
  - 監査ログ + 7 新規 Admin ページ (reports/agents/settings/certs/backups/notifications-config/licenses)
  - ライトテーマ / Login 2カラム / サイドバー SVG アイコン

### Fixed
- CI E2E タイムアウト修正: `wait_until="domcontentloaded"` 統一 (PR #99)
- syncBtn 失敗時トースト表示修正

---

## [0.2.0] — 2026-05-04 — M4 RBAC / 通知 / E2E

### Added
- **M4-1 RBAC** (PR #60 + #61): admin/operator/viewer 3 ロール + `@require_role` デコレータ
- **M4-2 通知統合** (PR #62): Slack / Teams / Generic Webhook / Email
- **M4-3 E2E テスト** (PR #64): Playwright 94 項目 (UI/RBAC/forms/responsive)
- **M5-1 監査ログ高度化** (Issue #74): 日付範囲フィルタ + CSV エクスポート
- **M5-2 PC 一括タスク実行** (Issue #75): チェックボックス選択 + bulk API
- Prometheus メトリクス (`/api/metrics`)
- Swagger UI (`/api/docs/`)

---

## [0.1.0] — 2026-04-29 — M1〜M3 基盤

### Added
- **M1 Flask 管理サーバー基盤**: Application Factory / 9 Blueprint / JWT + API Key 二重認証
- **M2 PC/タスク/アラート CRUD**: PC一覧・詳細・CSV / タスク管理 / アラート
- **M3 スケジュール/グループ/Swagger**: APScheduler / PC グループ / OpenAPI 3.0

---

[Unreleased]: https://github.com/Kensan196948G/PC-Ops-Orchestrator/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/Kensan196948G/PC-Ops-Orchestrator/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Kensan196948G/PC-Ops-Orchestrator/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Kensan196948G/PC-Ops-Orchestrator/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Kensan196948G/PC-Ops-Orchestrator/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Kensan196948G/PC-Ops-Orchestrator/releases/tag/v0.1.0
