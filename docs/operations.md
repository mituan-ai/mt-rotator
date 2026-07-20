# 运维手册

## 首次部署

服务器部署目录固定为 `/opt/mt-rotator`。安装 Docker Engine、Compose 插件、restic 和 `flock`，创建生产 `.env`，并确保部署用户可以运行 Docker。

在 `/etc/mt-rotator/backup.env` 配置独立于 VPS 的 restic 仓库，并将权限限制为部署用户可读：

```bash
RESTIC_REPOSITORY=s3:s3.example.com/mt-rotator
RESTIC_PASSWORD_FILE=/etc/mt-rotator/restic-password
```

对象存储所需的访问变量放在同一环境文件中，不写入 Git。然后执行首个已发布版本：

```bash
set -a
. /etc/mt-rotator/backup.env
set +a
restic snapshots >/dev/null 2>&1 || restic init
./ops/mt-rotator update v1.0.0
docker compose exec api python manage.py create_admin --email admin@example.com --display-name 管理员
```

该命令交互式读取管理员密码，不会把密码写入 shell 历史或 `.env`。首次登录后在管理页执行“回填24个月”，Worker 会单线程限速同步新浪 ETF 目录和历史日线；中断后可重复执行，已有修订不会被静默覆盖。

## 更新与回退

```bash
./ops/mt-rotator update v1.1.0
./ops/mt-rotator status
./ops/mt-rotator rollback
```

更新命令使用项目级文件锁，先备份，再拉取并解析 GHCR 镜像摘要，停止业务容器、运行迁移、启动并等待健康。失败时恢复上一版应用镜像；绝不执行 `down -v`、全局镜像清理或数据库反向迁移。

## 定时备份

将 `infra/systemd/` 下四个 unit 安装到 `/etc/systemd/system/`，然后启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mt-rotator-backup.timer mt-rotator-restore-verify.timer
systemctl list-timers 'mt-rotator-*'
```

每日备份包含 PostgreSQL、自身校验计数、加密后的 `.env` 和部署版本状态。每月恢复到临时数据库，检查当前迁移，并比较关键表计数及账本金额、份额汇总。Redis 和 Caddy 证书不备份，均可重建。

手动检查：

```bash
./ops/mt-rotator backup
./ops/mt-rotator restore-verify
journalctl -u mt-rotator-backup.service
```

正式恢复生产数据库是有损操作，不由自动脚本提供。应先停止 API、Worker 和 Beat，保留当前数据库的额外转储，在新数据库完成恢复验证后再切换连接配置。
