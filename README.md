# MT Rotator（MT轮动）

**中文** | [English](README_EN.md)

基于真实免费日线行情的 A 股 ETF 策略建议与自主模拟交易系统。

MT Rotator 面向受邀用户。策略只给出与账户持仓相关的建议，买卖委托必须由用户确认；系统不连接券商，也不执行实盘交易。

## 主要功能

- 管理员邀请注册，多用户数据隔离。
- 搜索新浪财经 ETF 目录，并查看日线行情、成交额、交收规则和数据状态。
- 趋势轮动、相对动量和均线趋势三种版本化策略。
- 单一自主模拟账户，初始资金 100,000 元。
- 下一交易日开盘估算成交，支持整手、佣金、滑点和 T+0/T+1 可卖控制。
- 不可变订单、成交、持仓批次和资金账本。
- 按共同净值截止日计算的非匿名收益排行榜。
- 管理页面覆盖邀请、用户、行情任务、策略状态和审计日志。

行情来自 AKShare 接入的新浪财经免费接口。系统使用日线数据，不提供实时行情；所有成交均为估算结果。

## 本地启动

### 1. 准备环境

只需要安装：

- Git
- Docker Engine
- Docker Compose 插件（使用 `docker compose` 命令）

Ubuntu 的 Docker 官方安装方法见 [Install Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)。安装后确认：

```bash
docker --version
docker compose version
```

如果出现 `/var/run/docker.sock: permission denied`，将当前用户加入 `docker` 组，然后退出并重新登录：

```bash
sudo usermod -aG docker "$USER"
```

### 2. 获取代码并配置

```bash
git clone https://github.com/mituan-ai/mt-rotator.git
cd mt-rotator
cp .env.example .env
openssl rand -hex 32
```

编辑 `.env`，至少替换下面两项：

```env
DJANGO_SECRET_KEY=上一步生成的随机字符串
POSTGRES_PASSWORD=单独设置的强数据库密码
```

本地使用 `https://localhost` 时，其他域名配置可以保持 `.env.example` 的默认值。

### 3. 启动全部服务

```bash
docker compose up --build -d --wait
docker compose ps
```

Docker Compose 会启动 PostgreSQL、Redis、Django API、Celery Worker、Celery Beat 和 Caddy。数据库迁移由一次性 `migrate` 服务自动执行。

检查状态：

```bash
curl -k https://localhost/api/v1/health/ready
```

返回 `{"status":"ready",...}` 即表示基础服务正常。

### 4. 创建第一个管理员

```bash
docker compose exec api python manage.py create_admin \
  --email admin@example.com \
  --display-name 管理员
```

命令会在终端中要求输入并确认密码。密码不会写入 `.env` 或 shell 历史。

### 5. 登录并同步数据

浏览器打开 [https://localhost](https://localhost)。本地证书由 Caddy 生成，浏览器可能提示证书不受信任；该提示只出现在本地环境。

登录管理员账户后进入“管理”页面：

1. 在“邀请”中生成其他用户的一次性注册链接。
2. 在“数据状态”中点击“回填24个月”。
3. 等待数据任务完成，再使用 ETF、建议、交易、回测和排行功能。

首次回填会单线程限速访问免费接口，耗时取决于 ETF 数量和新浪接口状态。任务中断后可以再次执行，系统会继续补齐缺失区间。

### 常用本地命令

```bash
# 查看状态和日志
docker compose ps
docker compose logs -f api worker beat

# 重新构建并启动更新后的代码
docker compose up --build -d --wait

# 停止服务；不会删除 PostgreSQL 命名卷
docker compose down

# 后端和前端检查
make test
make e2e
```

不要执行 `docker compose down -v`，该命令会删除项目的数据库卷。

## 腾讯云生产部署

### 正确顺序

1. 确定最终域名和腾讯云公网 IP。
2. 将域名 A 记录解析到服务器；不使用 IPv6 时删除错误的 AAAA 记录。
3. 在腾讯云安全组中开放 TCP `80`、TCP `443` 和 UDP `443`。
4. 在服务器安装 Docker、Compose、Git、restic 和 `flock`。
5. 发布 GitHub 版本，使 CI 构建对应的 GHCR 镜像。
6. 在服务器配置生产 `.env` 和远端备份。
7. 执行首次部署，创建管理员并回填行情。
8. 验证备份恢复后再开放用户邀请。

域名需要在首次正式启动 Caddy 前确定。只要 DNS 已指向服务器且 `80/443` 可访问，Caddy 会自动申请和续期公开 HTTPS 证书，不需要手工上传证书文件。

### 1. 安装服务器环境

在腾讯云 Ubuntu 服务器中安装 Git、restic、`flock` 和 Docker 官方软件源：

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git restic util-linux
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

退出 SSH 并重新登录，使 `docker` 组权限生效，然后确认：

```bash
docker --version
docker compose version
```

### 2. 发布版本

推送 `main` 会运行 CI，但只有 `v*` Tag 会构建并发布生产镜像：

```bash
git push origin main
git tag v1.0.0
git push origin v1.0.0
```

等待 GitHub Actions 中的后端、前端、E2E、Docker 和镜像扫描全部通过。镜像发布到：

```text
ghcr.io/mituan-ai/mt-rotator-api
ghcr.io/mituan-ai/mt-rotator-web
```

如果 GHCR 包是私有的，需要先在服务器执行 `docker login ghcr.io`。

### 3. 准备服务器目录

```bash
sudo mkdir -p /opt/mt-rotator
sudo chown "$USER":"$USER" /opt/mt-rotator
git clone https://github.com/mituan-ai/mt-rotator.git /opt/mt-rotator
cd /opt/mt-rotator
git checkout v1.0.0
cp .env.example .env
```

### 4. 配置生产环境

假设域名为 `etf.example.com`，生产 `.env` 至少需要设置：

```env
DJANGO_SECRET_KEY=至少50位的随机密钥
POSTGRES_PASSWORD=独立的强数据库密码
DJANGO_ALLOWED_HOSTS=etf.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://etf.example.com
PUBLIC_BASE_URL=https://etf.example.com
SITE_ADDRESS=etf.example.com
CADDY_HEALTH_URL=https://etf.example.com/api/v1/health/live
```

保持 `DJANGO_DEBUG=false`、`DJANGO_SECURE_COOKIES=true` 和 `DJANGO_SECURE_SSL_REDIRECT=true`。

生产环境不得让其他 Nginx、Apache 或面板占用公网 `80/443`。如果域名前面使用腾讯云 CDN 或负载均衡，则 HTTPS 终止方式需要单独配置，不能直接套用上述直连方案。

### 5. 配置远端备份

更新脚本要求使用 restic 将 PostgreSQL 备份保存到 VPS 之外。创建 `/etc/mt-rotator/backup.env`：

```bash
sudo mkdir -p /etc/mt-rotator
sudo touch /etc/mt-rotator/backup.env
sudo chmod 600 /etc/mt-rotator/backup.env
```

文件内容取决于所使用的 S3 兼容对象存储，例如：

```env
RESTIC_REPOSITORY=s3:s3.example.com/mt-rotator
RESTIC_PASSWORD_FILE=/etc/mt-rotator/restic-password
```

对象存储访问凭据也放在该文件中，不写入 Git。初始化仓库：

```bash
set -a
. /etc/mt-rotator/backup.env
set +a
restic snapshots >/dev/null 2>&1 || restic init
```

### 6. 首次部署

```bash
cd /opt/mt-rotator
./ops/mt-rotator update v1.0.0
./ops/mt-rotator status
docker compose exec api python manage.py create_admin \
  --email admin@example.com \
  --display-name 管理员
```

访问正式域名，登录后在管理页面执行“回填24个月”。随后安装每日备份和每月恢复验证定时器：

```bash
sudo cp infra/systemd/mt-rotator-* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now \
  mt-rotator-backup.timer \
  mt-rotator-restore-verify.timer
```

手动验证一次：

```bash
./ops/mt-rotator backup
./ops/mt-rotator restore-verify
```

### 发布后自动更新

GitHub `production` Environment 需要配置以下 Secrets：

```text
PRODUCTION_HOST
PRODUCTION_USER
PRODUCTION_SSH_PRIVATE_KEY
PRODUCTION_KNOWN_HOSTS
```

`PRODUCTION_SSH_PRIVATE_KEY` 应使用仅供部署的 SSH 私钥，对应公钥写入服务器部署用户的 `authorized_keys`。`PRODUCTION_KNOWN_HOSTS` 保存经过人工核对的服务器 SSH 主机公钥，不能在工作流中临时信任扫描结果。

推送语义化版本 Tag 后，CI 会先完成测试、构建和漏洞扫描，再发布固定版本镜像并自动更新服务器：

```bash
git tag v1.1.0
git push origin v1.1.0
```

部署 Job 使用短期 GitHub 令牌拉取 GHCR 镜像，完成后立即退出镜像仓库。服务器仍由 `./ops/mt-rotator update` 执行部署锁、远端备份、镜像摘要固定、数据库迁移和健康检查。失败时自动恢复上一组应用镜像；它不会删除 PostgreSQL 卷，也不会自动反向迁移数据库。

应用镜像回退：

```bash
./ops/mt-rotator rollback
```

完整备份、恢复和故障处理说明见 [docs/operations.md](docs/operations.md)，领域边界见 [docs/architecture.md](docs/architecture.md)。

## 开发检查

本地完整检查：

```bash
make test
make e2e
```

后端开发使用 Python 3.12 和 [uv](https://docs.astral.sh/uv/)：

```bash
cd backend
uv sync --all-groups
MT_TESTING=1 uv run pytest
```

前端开发使用 Node.js 22：

```bash
cd frontend
npm ci
npm run lint
npm run typecheck
npm test
npm run build
```

## 数据与风险

免费行情接口可能延迟、变更或暂时不可用。单只 ETF 异常只暂停该标的，主要池覆盖不足会暂停新建议；已有历史仍可查看。模拟结果和策略建议只用于研究，不构成投资建议。

## License

[MIT](LICENSE)
