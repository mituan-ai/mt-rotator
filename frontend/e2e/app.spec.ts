import { expect, test, type Page } from '@playwright/test'

const user = {
    id: 'user-admin',
    email: 'admin@example.com',
    display_name: '管理员',
    is_staff: true,
    is_active: true
}

const signal = {
    id: 'signal-1',
    strategy_slug: 'equity-bond-trend',
    strategy_name: '股债趋势轮动',
    signal_date: '2026-06-30',
    tradable_on: '2026-07-01',
    target_weights: { '510300': 0.35, '511160': 0.455, '511990': 0.13, '511010': 0.065 },
    rationale: { trend_open: true },
    data_source: { provider: '东方财富', cutoff_date: '2026-06-30', adjustment: '后复权' }
}

const strategies = [
    {
        id: 'strategy-1', slug: 'equity-bond-trend', name: '股债趋势轮动', version: '1.0.0',
        description: '趋势开启时配置最强风险资产，其余资金进入防御篮子。', parameters: {},
        risk_symbols: ['510300', '510500', '159915', '510880', '515300'],
        defensive_weights: { '511160': 0.7, '511990': 0.2, '511010': 0.1 }, active: true, latest_signal: signal
    },
    {
        id: 'strategy-2', slug: 'relative-momentum-top-n', name: 'ETF相对动量Top-N', version: '1.0.0',
        description: '从正动量资产中选择前两名，其余资金进入防御篮子。', parameters: {},
        risk_symbols: ['510300', '510500', '159915', '510880', '515300'],
        defensive_weights: { '511160': 0.7, '511990': 0.2, '511010': 0.1 }, active: true,
        latest_signal: { ...signal, id: 'signal-2', strategy_slug: 'relative-momentum-top-n', strategy_name: 'ETF相对动量Top-N', target_weights: { '159915': 0.5, '510500': 0.5 } }
    },
    {
        id: 'strategy-3', slug: 'moving-average-equal-weight', name: '均线趋势等权', version: '1.0.0',
        description: '对高于200日均线的风险资产等权配置。', parameters: {},
        risk_symbols: ['510300', '510500', '159915', '510880', '515300'],
        defensive_weights: { '511160': 0.7, '511990': 0.2, '511010': 0.1 }, active: true,
        latest_signal: { ...signal, id: 'signal-3', strategy_slug: 'moving-average-equal-weight', strategy_name: '均线趋势等权', target_weights: { '510300': 0.5, '510880': 0.5 } }
    }
]

const activeAccount = {
    id: 'account-1', strategy_id: 'strategy-1', strategy_name: '股债趋势轮动', strategy_slug: 'equity-bond-trend',
    generation: 2, status: 'active', initial_capital: '100000.00', cash: '33820.50',
    latest_nav: { date: '2026-07-17', value: '106820.50', cash: '33820.50' },
    positions: [{ symbol: '510300', name: '沪深300ETF', shares: 15000, average_cost: '4.8667' }],
    pending_rebalances: [{ id: 'rebalance-1', eligible_on: '2026-08-03', target_weights: { '510300': 0.35 }, source: 'monthly_signal', status: 'pending' }]
}

const archivedAccount = {
    ...activeAccount,
    id: 'account-archived',
    generation: 1,
    status: 'archived',
    cash: '32115.20',
    latest_nav: { date: '2026-06-30', value: '103115.20', cash: '32115.20' },
    pending_rebalances: []
}

const market = {
    ready: true,
    expected_session: '2026-07-17',
    source: 'AKShare / 东方财富',
    validation_source: '新浪',
    adjustments: ['raw', 'hfq'],
    last_batch: { id: 'batch-1', status: 'healthy', finished_at: '2026-07-17T12:05:00Z', errors: [], warnings: [] },
    instruments: strategies[0].risk_symbols.map((symbol) => ({ symbol, name: symbol, latest_date: '2026-07-17', raw_latest_date: '2026-07-17', hfq_latest_date: '2026-07-17', state: 'ready' }))
}

const backtests = [
    {
        id: 'run-1', strategy_name: '股债趋势轮动', strategy_slug: 'equity-bond-trend', start_date: '2015-01-01', end_date: '2026-06-30',
        initial_capital: '100000.00', status: 'succeeded', error: '', created_at: '2026-07-01T08:00:00Z',
        data_snapshot: { cutoff_date: '2026-06-30', provider: '东方财富', digest: 'snapshot-one' },
        result: {
            assumptions: { commission_rate: '0.0003', slippage_bps: 5 },
            metrics: { total_return: 0.4281, max_drawdown: -0.1264, sharpe: 1.12 },
            nav: [{ date: '2015-01-05', value: 100000 }, { date: '2020-01-02', value: 121300 }, { date: '2026-06-30', value: 142810 }],
            trades: []
        }
    },
    {
        id: 'run-2', strategy_name: 'ETF相对动量Top-N', strategy_slug: 'relative-momentum-top-n', start_date: '2015-01-01', end_date: '2026-06-30',
        initial_capital: '100000.00', status: 'queued', error: '', created_at: '2026-07-01T08:01:00Z',
        data_snapshot: { cutoff_date: '2026-06-30', provider: '东方财富', digest: 'snapshot-two' }
    }
]

function pageOf<T>(results: T[]) {
    return { count: results.length, next: null, previous: null, results }
}

async function mockAuthenticatedApp(page: Page) {
    await page.route('**/api/v1/**', async (route) => {
        const request = route.request()
        const url = new URL(request.url())
        const path = url.pathname
        const method = request.method()

        if (path === '/api/v1/auth/csrf') return route.fulfill({ json: { detail: 'ok' } })
        if (path === '/api/v1/auth/me') return route.fulfill({ json: user })
        if (path === '/api/v1/auth/password/change' && method === 'POST') return route.fulfill({ status: 204, body: '' })
        if (path === '/api/v1/market/status') return route.fulfill({ json: market })
        if (path === '/api/v1/strategies/' && method === 'GET') return route.fulfill({ json: pageOf(strategies) })
        if (path === '/api/v1/paper/accounts' && method === 'GET') return route.fulfill({ json: pageOf([activeAccount, archivedAccount]) })
        if (path === '/api/v1/paper/accounts/account-1') return route.fulfill({ json: activeAccount })
        if (path === '/api/v1/paper/accounts/account-archived') return route.fulfill({ json: archivedAccount })
        if (path.endsWith('/orders')) return route.fulfill({ json: pageOf([{ id: 'order-1', symbol: '510300', side: 'buy', shares: 15000, eligible_on: '2026-07-01', status: 'filled', rejection_reason: '', fill: { price: '4.8667', fee: '21.90', filled_on: '2026-07-01', estimated: true } }]) })
        if (path.endsWith('/nav')) return route.fulfill({ json: pageOf([{ date: '2026-07-17', value: '106820.50', cash: '33820.50' }, { date: '2026-07-01', value: '100000.00', cash: '26978.10' }]) })
        if (path.endsWith('/ledger')) return route.fulfill({ json: pageOf([{ id: 'ledger-1', kind: 'trade', symbol: '510300', amount: '-73021.90', quantity: '15000', occurred_on: '2026-07-01' }]) })
        if (path === '/api/v1/backtests/' && method === 'GET') return route.fulfill({ json: pageOf(backtests) })
        if (path === '/api/v1/backtests/run-1') return route.fulfill({ json: backtests[0] })
        if (path === '/api/v1/backtests/run-2') return route.fulfill({ json: backtests[1] })
        if (path === '/api/v1/auth/admin/invitations' && method === 'GET') return route.fulfill({ json: pageOf([{ id: 'invite-1', email: 'member@example.com', note: '首批用户', expires_at: '2026-07-27T08:00:00Z', state: 'active', created_at: '2026-07-20T08:00:00Z' }]) })
        if (path === '/api/v1/auth/admin/invitations' && method === 'POST') return route.fulfill({ status: 201, json: { id: 'invite-2', email: 'new@example.com', note: '测试邀请', expires_at: '2026-07-27T08:00:00Z', state: 'active', created_at: '2026-07-20T08:00:00Z', link: 'https://mt.example/register#token=one-time-admin-token' } })
        if (path === '/api/v1/auth/admin/users') return route.fulfill({ json: pageOf([user, { ...user, id: 'user-member', email: 'member@example.com', display_name: '普通用户', is_staff: false }]) })
        if (path === '/api/v1/market/admin/batches') return route.fulfill({ json: pageOf([{ id: 'batch-1', status: 'healthy', expected_session: '2026-07-17', errors: [], warnings: [], started_at: '2026-07-17T10:30:00Z', finished_at: '2026-07-17T12:05:00Z', triggered_by: 'schedule' }]) })
        if (path === '/api/v1/strategies/admin') return route.fulfill({ json: pageOf(strategies) })
        if (path === '/api/v1/admin/audit') return route.fulfill({ json: pageOf([{ id: 'audit-1', actor_email: 'admin@example.com', event_type: 'invitation.created', target_type: 'invitation', target_id: 'invite-1', created_at: '2026-07-20T08:00:00Z' }]) })

        return route.fulfill({ status: 404, contentType: 'application/problem+json', body: JSON.stringify({ detail: `Unhandled mock: ${method} ${path}` }) })
    })
}

async function expectViewportLayout(page: Page) {
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
    const footer = page.locator('.app-main > footer')
    await expect(footer).toBeVisible()
}

test.beforeEach(async ({ page }) => {
    await mockAuthenticatedApp(page)
})

test('overview and password change work for an authenticated user', async ({ page }, testInfo) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { name: '总览' })).toBeVisible()
    await expect(page.getByText('数据已就绪')).toBeVisible()
    await expect(page.getByText('股债趋势轮动').first()).toBeVisible()

    await page.getByRole('button', { name: '修改密码' }).click()
    await page.getByLabel('当前密码').fill('current-password')
    await page.getByLabel('新密码').fill('new-secure-password')
    await page.getByRole('button', { name: '保存' }).click()
    await expect(page.getByRole('dialog')).toBeHidden()

    await expectViewportLayout(page)
    await page.screenshot({ path: testInfo.outputPath('overview.png'), fullPage: true })
})

test('completed backtest can be inspected with a rendered chart', async ({ page }, testInfo) => {
    await page.goto('/backtests')
    await page.locator('.run-row').filter({ hasText: '股债趋势轮动' }).click()
    await expect(page.getByRole('heading', { name: '结果对比' })).toBeVisible()
    await expect(page.getByText('42.81%')).toBeVisible()
    const chart = page.getByRole('img', { name: '绩效曲线' })
    await expect(chart.locator('canvas')).toBeVisible()
    await expect.poll(() => chart.locator('canvas').evaluate((canvas) => (canvas as HTMLCanvasElement).toDataURL().length)).toBeGreaterThan(1000)

    await expectViewportLayout(page)
    await page.screenshot({ path: testInfo.outputPath('backtests.png'), fullPage: true })
})

test('paper account shows pending rebalance, fills and archived history', async ({ page }, testInfo) => {
    await page.goto('/simulation')
    await expect(page.getByText('待估算调仓')).toBeVisible()
    await expect(page.getByRole('cell', { name: '估算成交' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '不可变账本' })).toBeVisible()
    await page.getByRole('button', { name: /股债趋势轮动 · 第1期/ }).click()
    await expect(page.getByText('已归档')).toBeVisible()

    await expectViewportLayout(page)
    await page.screenshot({ path: testInfo.outputPath('simulation.png'), fullPage: true })
})

test('administrator can create a one-time invitation', async ({ page }, testInfo) => {
    await page.goto('/admin')
    await expect(page.getByRole('heading', { name: '管理' })).toBeVisible()
    await expect(page.getByText('允许信号与成交')).toBeVisible()
    await page.getByLabel('邮箱').fill('new@example.com')
    await page.getByLabel('备注').fill('测试邀请')
    await page.getByRole('button', { name: '生成一次性链接' }).click()
    await expect(page.getByText(/one-time-admin-token/)).toBeVisible()

    await expectViewportLayout(page)
    await page.screenshot({ path: testInfo.outputPath('admin.png'), fullPage: true })
})
