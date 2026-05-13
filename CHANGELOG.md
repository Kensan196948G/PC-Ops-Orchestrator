# Changelog

All notable changes to PC-Ops Orchestrator are documented in this file.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
Versioning: [Semantic Versioning](https://semver.org/)

---

## [Unreleased]

### Added (PR #147 — CI 実行中)
- **API キー管理 CRUD** — `ApiKey` モデル追加
  - `GET/POST /api/api-keys`, `POST /api/api-keys/<id>/rotate`, `DELETE /api/api-keys/<id>`
  - agents.html 内に API キー一覧テーブル・作成モーダル・ローテートモーダル追加
  - 全操作 admin_required (キーは機密情報)
- **システム設定 CRUD** — `SystemSetting` モデル追加 (key-value テーブル)
  - `GET /api/settings`, `PUT /api/settings` (13 設定キー対応)
  - settings.html: フォーム入力有効化、設定保存ボタン実機能化
- **バックアップ管理** — `BackupJob` モデル追加
  - `GET /api/backups` (履歴一覧 + 統計), `POST /api/backups/trigger` (即時バックアップ)
  - `POST /api/backups/integrity-check` (SQLite PRAGMA integrity_check)
  - backups.html: 動的テーブル・stat カード・整合性チェック・リストア確認フロー
- **証明書 stat カード動的更新** — certificates.js で期限警戒件数をリアルタイム集計
- **E2E テスト追加** — 6 新規ページ (agents/certs/licenses/notifications/backups/settings) を E2E カバレッジに追加
- **RBAC テスト強化** — 新規 API 7 件を RBAC matrix テストに追加

### Changed (PR #147)
- 全テンプレートから `data-stub-alert` 完全削除 (0 件達成)
- `/api/api-keys` GET: `login_required` → `admin_required` (セキュリティ強化)
- certificates.js: `actionTd.style.display/gap` → `actionTd.className = 'd-flex-gap'` (CSP Phase 3 維持)
- テスト: 333 → 343 件 (+10: API キー 4 + バックアップ 3 + 設定 3)

---

## [1.0.0] — 2026-05-13 — 本番リリース: CSP Phase 3 完了

### Security (PR #139)
- **CSP Phase 3** — `style-src 'unsafe-inline'` 完全除去
  - 全 16 テンプレートのインライン `style=""` 属性をゼロに削減（script-src に続く最終段階）
  - `login.html` の `<style>` ブロック (~200行) を外部 `style.css` に完全移行
  - CSS ユーティリティクラス追加 (.hidden / .d-flex-gap / .mt-actions / .mb-lg / .ring-canvas-wrap / .swatch-* 等)
  - JS 7 ファイルで `style.display` → `classList.toggle/add/remove` に統一
  - `style-src 'self'` のみに更新 (XSS 攻撃面をさらに削減)
  - 回帰防止テスト追加: `test_csp_style_src_no_unsafe_inline` / `test_no_inline_style_in_templates` (329 tests)

---

## [0.7.0] — 2026-05-13 — WebUI 刷新・Agent/通知/証明書/ライセンス実機能化

### Added (PR #140 MERGED)
- **Agent管理 実機能化** — `/api/agents` 新規実装
  - PC モデルからエージェント一覧 (CPU/メモリ/バージョン/heartbeat) をリアルタイム表示
- **通知設定 CRUD** — `NotificationChannel` モデル + CRUD API + チャネル追加/編集/削除モーダル
- **証明書管理 CRUD** — `Certificate` モデル + CRUD API + 登録/編集/削除モーダル + 残り日数バッジ
- **ライセンス管理 CRUD** — `License` モデル + CRUD API + 登録/編集/削除 + 合計コスト自動集計

### Changed (PR #143/#144 MERGED)
- **WebUI 刷新** — KPI カード・フィード・モーダル UI の改善
  - Dashboard: KPI グリッド・健全性リング・OS 内訳チャート・最近のタスク/監査フィード
  - Agent 管理: CPU/メモリ リアルタイムバー・ハートビートバッジ
  - レポート: 月次レポート PDF/CSV エクスポートボタン修正
  - 全ページ対応ダミーデータシード (`/api/seed` エンドポイント)
- **スタブボタン修正** — `data-stub-alert` 属性統一・Agent CPU バグ修正

### Fixed (PR #143 MERGED)
- Agent 一覧 CPU 利用率計算バグ修正
- デモデータシードルート修正 (POST /api/seed)

---

## [0.6.0] — 2026-05-09 — M6 テスト拡充・N+1修正・セキュリティ強化

### Security
- **CSP Phase 2** (Issue #121, PR #129)
  - 全 16 テンプレートのインラインハンドラ (`onclick/oninput/onchange/onsubmit`) を外部 JS の `addEventListener` に完全移行
  - `stub-actions.js` 新規作成 — `data-stub-alert` 属性でアラートスタブを共通管理
  - `script-src` から `'unsafe-inline'` を除去 (Phase 1 → Phase 2 完了)
  - `test_csp_script_src_uses_nonce_not_unsafe_inline` — strict 版テスト追加

### Fixed
- **N+1 クエリ解消 — CSV エクスポート** (Issue #121, PR #130)
  - `alerts.py` / `tasks.py` CSV エクスポートで `joinedload(*.pc)` 追加
  - 最大 5000 行エクスポート時のクエリ数: 5001 → 2 に削減
- **N+1 クエリ解消 — groups 一覧** (PR #131)
  - `GET /api/groups` で N グループ × 1 COUNT クエリ → 2 クエリに削減 (IN バルク COUNT)
  - `PCGroup.to_dict()` に `pc_count` オプション引数を追加 (後方互換)
- **Alert.pc relationship 欠落バグ修正** (PR #131)
  - `PC.alerts` relationship (backref="pc") を追加
  - `GET /api/alerts/export.csv` が `AttributeError` で 500 Error になっていた本番バグを解消
- **E2E CDN タイムアウト修正** (PR #131)
  - `conftest.py` + 4 テストファイルの `page.goto()` に `wait_until="domcontentloaded"` を追加
  - CI で Chart.js CDN 遅延による 60s タイムアウトが恒久修正

### Added
- **テストカバレッジ拡張** (PR #131): `test_coverage_boost.py` 新規作成 — **+121 件**
  - alerts CSV エクスポート (BOM・Content-Type・フィルタ・acknowledge/resolve)
  - tasks CSV エクスポート / バリデーション / 認可
  - groups CRUD エラーケース (400/404/409)
  - pcs エンドポイント (CSV・フィルタ・サブリソース・404)
  - alert_rules CRUD / scheduled_tasks CRUD
  - セキュリティヘッダ検証 (CSP strict, X-Frame-Options, Referrer-Policy)
  - auth エッジケース (inactive/no-body/setup済み/PATCH 弱パスワード/削除保護)
  - 監査ログ フィルタ / CSV エクスポート
  - **合計テスト数: 205 → 326 件 (+121 件)**
  - **routes カバレッジ: 65% → 81% (+16%)**

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

[Unreleased]: https://github.com/Kensan196948G/PC-Ops-Orchestrator/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Kensan196948G/PC-Ops-Orchestrator/compare/v0.7.0...v1.0.0
[0.7.0]: https://github.com/Kensan196948G/PC-Ops-Orchestrator/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/Kensan196948G/PC-Ops-Orchestrator/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/Kensan196948G/PC-Ops-Orchestrator/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Kensan196948G/PC-Ops-Orchestrator/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Kensan196948G/PC-Ops-Orchestrator/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Kensan196948G/PC-Ops-Orchestrator/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Kensan196948G/PC-Ops-Orchestrator/releases/tag/v0.1.0
