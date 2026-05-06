# 本番デプロイ手順書

## 概要

PC-Ops Orchestrator のサーバーコンポーネント (Flask + Gunicorn) を Linux 本番環境にデプロイする手順です。

---

## 必要条件

| 項目 | バージョン |
|---|---|
| OS | Ubuntu 22.04 LTS / RHEL 9 |
| Python | 3.12 以上 |
| SQLite | 3.37 以上 (または PostgreSQL 14+) |
| Gunicorn | 23.0.0 |
| Nginx | 1.24+ (リバースプロキシ) |

---

## 1. リポジトリ取得

```bash
git clone https://github.com/Kensan196948G/PC-Ops-Orchestrator.git /opt/pc-ops
cd /opt/pc-ops/server
```

---

## 2. Python 仮想環境とパッケージインストール

```bash
python3 -m venv /opt/pc-ops-venv
source /opt/pc-ops-venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 3. 環境変数設定 (.env)

```bash
cp /opt/pc-ops/server/.env.example /opt/pc-ops/server/.env
# 以下を編集する
```

`.env` に設定すべき最低限の変数:

```dotenv
# JWT 署名シークレット (32 文字以上のランダム文字列を推奨)
SECRET_KEY=your-very-secret-key-change-this

# エージェント認証 API キー (カンマ区切りで複数指定可)
AGENT_API_KEYS=key1,key2

# DB (デフォルトは SQLite / PostgreSQL に切り替える場合は以下を設定)
# DATABASE_URL=postgresql://user:pass@localhost:5432/pc_ops

# CORS 許可オリジン (WebUI のオリジン)
CORS_ORIGINS=https://your-domain.example.com

# CSP カスタマイズ (省略すると安全なデフォルト値が使用される)
# CONTENT_SECURITY_POLICY=default-src 'self'; ...

# Swagger UI の有効化 (本番では false 推奨)
SWAGGER_ENABLED=false
```

---

## 4. DB マイグレーション

```bash
cd /opt/pc-ops/server
source /opt/pc-ops-venv/bin/activate
python3 -c "
from app import create_app
from extensions import db
app = create_app('production')
with app.app_context():
    db.create_all()
    print('DB schema created')
"
```

Flask-Migrate を使う場合:

```bash
FLASK_APP=app flask db upgrade
```

---

## 5. 管理者ユーザー作成

```bash
curl -X POST http://localhost:5300/api/auth/setup \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "AdminPass1!"}'
```

> パスワードポリシー: 大小英字+数字+記号+8文字以上

---

## 6. Gunicorn 起動スクリプト

`/opt/pc-ops/server/wsgi.py`:

```python
from app import create_app
app = create_app('production')
```

手動起動:

```bash
cd /opt/pc-ops/server
source /opt/pc-ops-venv/bin/activate
gunicorn --workers 4 --bind 0.0.0.0:5300 --timeout 120 \
  --access-logfile /var/log/pc-ops/access.log \
  --error-logfile /var/log/pc-ops/error.log \
  wsgi:app
```

---

## 7. Systemd サービス設定

`/etc/systemd/system/pc-ops.service`:

```ini
[Unit]
Description=PC-Ops Orchestrator
After=network.target

[Service]
Type=simple
User=pc-ops
WorkingDirectory=/opt/pc-ops/server
EnvironmentFile=/opt/pc-ops/server/.env
ExecStart=/opt/pc-ops-venv/bin/gunicorn \
    --workers 4 \
    --bind 0.0.0.0:5300 \
    --timeout 120 \
    --access-logfile /var/log/pc-ops/access.log \
    --error-logfile /var/log/pc-ops/error.log \
    wsgi:app
ExecReload=/bin/kill -s HUP $MAINPID
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable pc-ops
sudo systemctl start pc-ops
```

---

## 8. Nginx リバースプロキシ設定

`/etc/nginx/sites-available/pc-ops`:

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.example.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5300;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    listen 80;
    server_name your-domain.example.com;
    return 301 https://$host$request_uri;
}
```

```bash
sudo ln -s /etc/nginx/sites-available/pc-ops /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

## 9. Gunicorn グレースフルリロード (コード更新時)

```bash
# コード更新後、Gunicorn マスタープロセスに HUP シグナルを送る
# (ダウンタイムなし)
sudo kill -HUP $(cat /var/run/pc-ops.pid)
# または
sudo systemctl reload pc-ops
```

---

## 10. ヘルスチェック確認

```bash
curl -s http://localhost:5300/health | python3 -m json.tool
```

正常時のレスポンス例:

```json
{
  "status": "ok",
  "version": "1.0.0"
}
```

---

## 11. セキュリティチェックリスト

- [ ] `SECRET_KEY` を本番用ランダム文字列に変更
- [ ] `SWAGGER_ENABLED=false` に設定
- [ ] HTTPS (SSL/TLS) を有効化
- [ ] `CORS_ORIGINS` を本番ドメインのみに制限
- [ ] `AGENT_API_KEYS` を推測困難なキーに設定
- [ ] ファイアウォールで 5300 ポートを外部から遮断 (Nginx 経由のみ許可)
- [ ] 定期 pip-audit CI (毎週月曜) が GREEN であることを確認

---

## 12. ロールバック手順

```bash
# 前のリリースタグに戻す例
git checkout v0.4.0
cd server
pip install -r requirements.txt
sudo systemctl reload pc-ops
```
