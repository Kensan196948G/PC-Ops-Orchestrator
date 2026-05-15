# アーキテクチャ — v1.0

本ドキュメントは v1.0 (2026-10-28 リリース) のシステム構成と責務分離を定義する。
詳細仕様は `docs/アーキテクチャ.md` を参照。

## 1. 全体構成

```mermaid
graph LR
    subgraph "管理対象 PC"
        Agent[Agent<br/>PowerShell]
    end
    subgraph "サーバー"
        Web[Flask WebUI/API]
        DB[(SQLite/PostgreSQL)]
        Sched[Scheduler<br/>APScheduler]
    end
    subgraph "外部"
        AD[Active Directory]
        Slack[Slack/Email]
    end

    Agent -- HTTPS Pull --> Web
    Web --> DB
    Sched --> DB
    Sched --> Web
    Web -.連携.-> AD
    Web -- 通知 --> Slack
```

**Pull 型維持**: サーバー → Agent への能動接続は行わない。Agent が定期的にサーバーへ
ハートビート/結果報告を送る。

## 2. レイヤー責務

| レイヤー | 責務 | 主要ファイル |
|---|---|---|
| Routes | HTTP エンドポイント、認証/認可、入力検証 | `server/routes/*.py` |
| Models | データ永続化、relationship 定義 | `server/models.py` |
| Extensions | Flask 拡張統合 (db/migrate/limiter/cors) | `server/extensions.py` |
| Scheduler | 定期ジョブディスパッチ | `server/scheduler.py` |
| Agent | 収集スクリプト、ジョブ実行 | `agent/` |
| Templates | Jinja2 + CSP nonce | `server/templates/` |
| Static | CSS/JS (CDN なし、すべて self-host) | `server/static/` |

## 3. データフロー

### 収集 (Pull)
```
Agent (cron 5min)
  → POST /api/collect
    → routes/collect.py: 入力検証 + alert rule 評価
      → models.PC.last_seen 更新
      → models.Alert (条件成立時)
```

### ジョブ実行 (Phase B-1)
```
Operator → POST /api/jobs (テンプレ ID + パラメータ)
  → JobTemplate 検証 + 承認要件チェック
    → DB.tasks に queued 投入
      → Agent が次回 poll で取得 → 実行 → 結果 POST
```

## 4. 主要モジュール状態 (2026-05-15)

| モジュール | カバレッジ | 状態 |
|---|---|---|
| app.py | 100% | PR #171 達成 |
| config.py | 100% | PR #169 達成 |
| scheduler.py | 100% | PR #167 達成 |
| collect.py | 100% | PR #161 達成 |
| routes/* | 95% (seed.py 除く) | PR #164 達成 |
| Agent (PS) | Pester | 既存 |

## 5. Phase A での拡張予定

### A-1: DB スキーマ拡張 (Alembic 導入)
- 新規テーブル: `hardware_inventory`, `software_inventory`, `network_interfaces`
- 既存テーブル拡張: `pcs` に `os_build`, `cpu_model`, `ram_gb`, `disk_total_gb`
- マイグレーション運用: `migrations/` ディレクトリ新設、`alembic.ini` 設定

### A-2: Agent 収集拡張
- 新コレクタ: `Get-HardwareInfo.ps1`, `Get-SoftwareInfo.ps1`, `Get-NetworkInfo.ps1`
- `/api/collect` ペイロードスキーマ拡張 (後方互換維持)

### A-3: PC 詳細画面
- 既存 `templates/pc_detail.html` を本実装
- ハードウェア/ソフトウェア/ネットワーク タブ構造
- 履歴グラフ (Chart.js, self-hosted)

### A-4: ダッシュボード KPI
- 稼働率/アラート発生率/ジョブ成功率の可視化
- 期間選択 (24h/7d/30d)

## 6. 不変条件 (Phase B/C でも維持)

- Pull 型 Agent
- audit_logs 削除不可
- PowerShell テンプレート制
- CSP 'self' のみ (CDN 禁止)
- 認証なしエンドポイント追加禁止

詳細: `docs/SECURITY_DESIGN.md`
