# MT Rotator（MT轮动）

基于免费真实日线数据的 A 股 ETF 轮动研究与自动模拟交易系统。

## 核心规则

- 管理员邀请注册，多用户数据相互隔离。
- 内置股债趋势轮动、ETF 相对动量 Top-N、均线趋势等权三种固定策略。
- 月末收盘后生成信号，下一交易日按真实开盘价加固定滑点估算成交。
- 统一使用 100,000 元初始资金、万分之三佣金、最低 5 元费用和 5 bps 滑点。
- 行情来自 AKShare 东方财富接口，使用新浪接口交叉校验；系统不接入券商，不执行实盘订单。

## 启动

需要 Docker Engine 与 Docker Compose。

```bash
cp .env.example .env
docker compose up --build -d
docker compose exec api python manage.py create_admin --email admin@example.com
```

启动前必须修改 `.env` 中的 Django 密钥、数据库密码、域名和 HTTPS 配置。管理员创建完成后，通过管理页签发邀请、检查数据任务并管理策略状态。

## 开发验证

后端使用 Python 3.12 与 [uv](https://docs.astral.sh/uv/)，前端使用 Node.js 22。

```bash
cd backend
uv sync --all-groups
MT_TESTING=1 uv run pytest
```

```bash
cd frontend
npm ci
npm run typecheck
npm test
npm run build
npm run e2e
```

完整质量检查也可以从项目根目录运行 `make test` 和 `make e2e`。

## 数据与风险

免费行情接口可能延迟、变更或暂时不可用。必需资产数据不完整时，MT轮动会暂停新信号和模拟成交。所有成交均为基于日线 OHLC 的估算结果，仅用于研究，不构成投资建议。

## License

[MIT](LICENSE)
