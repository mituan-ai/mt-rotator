import { expect, test, type Page } from '@playwright/test'

const user = {
    id: 'user-admin', email: 'admin@example.com', display_name: '管理员', is_staff: true, is_active: true
}

const strategies = [
    { id: 'strategy-1', slug: 'equity-bond-trend', name: '趋势轮动', version: '2.1.0', description: '根据长期趋势选择强势ETF。', parameters: {}, risk_symbols: [], defensive_weights: {}, active: true, latest_signal: null },
    { id: 'strategy-2', slug: 'relative-momentum-top-n', name: '相对动量', version: '2.1.0', description: '综合多个周期筛选强势ETF。', parameters: {}, risk_symbols: [], defensive_weights: {}, active: true, latest_signal: null },
    { id: 'strategy-3', slug: 'moving-average-equal-weight', name: '均线趋势', version: '2.1.0', description: '筛选均线趋势向上的ETF。', parameters: {}, risk_symbols: [], defensive_weights: {}, active: true, latest_signal: null }
]

const instrument = {
    symbol: '510300', name: '沪深300ETF', exchange: 'XSHG', asset_class: 'equity', settlement_cycle: 't1', lot_size: 100,
    listed_on: '2012-05-28', enabled: true, catalog_active: true, data_status: 'ready', data_error: '', last_bar_date: '2026-07-17',
    average_amount_20d: '1960000000.00', trade_eligible: true, advice_eligible: true, latest_close: '4.1220'
}

const manualAccount = {
    id: 'account-1', account_number: 'a1b2c3d4', mode: 'manual', risk_level: 'balanced', strategy_id: 'strategy-1', strategy_name: '趋势轮动', strategy_slug: 'equity-bond-trend',
    generation: 1, status: 'active', initial_capital: '100000.00', cash: '58780.00', latest_nav: { date: '2026-07-17', value: '103420.00', cash: '58780.00' },
    positions: [{ symbol: '510300', name: '沪深300ETF', settlement_cycle: 't1', shares: 10000, sellable_shares: 10000, average_cost: '4.0020' }],
    pending_orders: [], created_at: '2026-05-10T08:00:00Z', archived_at: null
}

const archivedAccount = {
    ...manualAccount, id: 'account-archived', account_number: 'b2c3d4e5', mode: 'legacy_auto', strategy_name: '趋势轮动', status: 'archived', archived_at: '2026-07-01T08:00:00Z'
}

const advice = {
    id: 'advice-1', strategy_name: '趋势轮动', strategy_slug: 'equity-bond-trend', session_date: '2026-07-17', expires_on: '2026-07-20', status: 'ready', stale: false, risk_level: 'balanced',
    target_weights: { '510300': '0.600000', '159915': '0.200000' },
    recommendations: [
        { symbol: '159915', name: '创业板ETF', action: 'buy', quantity: 500, actionable: true, current_shares: 0, effective_shares: 0, current_weight: '0', target_weight: '0.2', estimated_price: '2.123', reason: '连续信号确认且低于目标仓位', valid_on: '2026-07-20' },
        { symbol: '510300', name: '沪深300ETF', action: 'hold', quantity: 0, actionable: false, current_shares: 10000, effective_shares: 10000, current_weight: '0.3985', target_weight: '0.6', estimated_price: '4.122', reason: '调整幅度不足，避免低价值换手', valid_on: '2026-07-20' }
    ],
    input_summary: { cash: '58780.00', nav: '103420.00', market_state: 'strong' }
}

const market = {
    ready: true, expected_session: '2026-07-17', source: '新浪财经，经 AKShare 获取', validation_source: '内部字段、日期与覆盖率校验', adjustments: ['raw', 'total_return'], coverage: '0.9820',
    counts: { catalog: 1024, trade_eligible: 486, advice_eligible: 318, ready: 990, stale: 20, missing: 10, blocked: 4 },
    last_batch: { id: 'batch-1', status: 'healthy', finished_at: '2026-07-17T12:05:00Z', errors: [], warnings: [] }, instruments: []
}

const backtests = [{
    id: 'run-1', strategy_name: '趋势轮动', strategy_slug: 'equity-bond-trend', start_date: '2025-07-01', end_date: '2026-06-30', initial_capital: '100000.00', status: 'succeeded', error: '', created_at: '2026-07-01T08:00:00Z',
    data_snapshot: { cutoff_date: '2026-06-30', provider: 'sina-akshare', digest: 'snapshot-one' },
    result: { assumptions: { commission_rate: '0.0003', slippage_bps: 5 }, metrics: { total_return: 0.1281, max_drawdown: -0.0864, sharpe: 1.12 }, nav: [{ date: '2025-07-01', value: 100000 }, { date: '2026-06-30', value: 112810 }], trades: [] }
}]

function pageOf<T>(results: T[]) {
    return { count: results.length, next: null, previous: null, results }
}

async function mockAuthenticatedApp(page: Page) {
    const orders: Record<string, unknown>[] = []
    await page.route('**/api/v1/**', async (route) => {
        const request = route.request()
        const url = new URL(request.url())
        const path = url.pathname
        const method = request.method()

        if (path === '/api/v1/auth/csrf') return route.fulfill({ json: { detail: 'ok' } })
        if (path === '/api/v1/auth/me') return route.fulfill({ json: user })
        if (path === '/api/v1/auth/password/change' && method === 'POST') return route.fulfill({ status: 204, body: '' })
        if (path === '/api/v1/market/status') return route.fulfill({ json: market })
        if (path === '/api/v1/market/instruments' && method === 'GET') return route.fulfill({ json: pageOf([instrument, { ...instrument, symbol: '159915', name: '创业板ETF', exchange: 'XSHE', latest_close: '2.1230' }]) })
        if (path === '/api/v1/market/instruments/510300') return route.fulfill({ json: instrument })
        if (path === '/api/v1/market/instruments/159915') return route.fulfill({ json: { ...instrument, symbol: '159915', name: '创业板ETF', exchange: 'XSHE', latest_close: '2.1230' } })
        if (path.endsWith('/bars')) return route.fulfill({ json: { instrument, adjustment: 'raw', source: market.source, bars: [{ date: '2026-07-16', open: '4.08', high: '4.13', low: '4.06', close: '4.10', volume: '1000000', amount: '410000000' }, { date: '2026-07-17', open: '4.10', high: '4.14', low: '4.09', close: '4.122', volume: '1200000', amount: '494640000' }] } })
        if (path === '/api/v1/strategies/' && method === 'GET') return route.fulfill({ json: pageOf(strategies) })
        if (path === '/api/v1/paper/accounts' && method === 'GET') return route.fulfill({ json: pageOf([manualAccount, archivedAccount]) })
        if (path === '/api/v1/paper/accounts/account-1' && method === 'GET') return route.fulfill({ json: { ...manualAccount, pending_orders: orders.filter((item) => item.status === 'pending') } })
        if (path === '/api/v1/paper/accounts/account-archived') return route.fulfill({ json: archivedAccount })
        if (path.endsWith('/advice/current')) return route.fulfill({ json: advice })
        if (path.endsWith('/advice')) return route.fulfill({ json: pageOf([advice]) })
        if (path.endsWith('/orders') && method === 'GET') return route.fulfill({ json: pageOf(orders) })
        if (path.endsWith('/orders') && method === 'POST') {
            const payload = request.postDataJSON()
            const order = { id: 'order-new', symbol: payload.instrument, name: '创业板ETF', side: payload.side, shares: payload.shares, origin: 'user', eligible_on: '2026-07-20', expires_on: '2026-07-20', reserved_cash: '1066.82', status: 'pending', rejection_reason: '', cancellable: true, created_at: '2026-07-19T08:00:00Z' }
            orders.splice(0, orders.length, order)
            return route.fulfill({ status: 201, json: order })
        }
        if (path.endsWith('/fills')) return route.fulfill({ json: pageOf([{ id: 'fill-1', order_id: 'old-order', symbol: '510300', side: 'buy', shares: 10000, price: '4.0020', fee: '12.01', filled_on: '2026-05-12', estimated: true, created_at: '2026-05-12T11:00:00Z' }]) })
        if (path.endsWith('/nav')) return route.fulfill({ json: pageOf([{ date: '2026-07-17', value: '103420.00', cash: '58780.00' }, { date: '2026-05-12', value: '100000.00', cash: '59968.00' }]) })
        if (path.endsWith('/ledger')) return route.fulfill({ json: pageOf([{ id: 'ledger-1', kind: 'buy', symbol: '510300', amount: '-40020.00', quantity: '10000', occurred_on: '2026-05-12', detail: {}, created_at: '2026-05-12T11:00:00Z' }]) })
        if (path === '/api/v1/paper/leaderboard') return route.fulfill({ json: { ...pageOf([{ rank: 1, rank_change: 1, display_name: '管理员', account_number: 'a1b2c3d4', return: '0.0342', max_drawdown: '-0.0120', current_nav: '103420.00', account_age_sessions: 48, eligible: true, eligibility_reason: '', started_at: '2026-05-10T08:00:00Z' }, { rank: null, rank_change: null, display_name: '新用户', account_number: 'd4e5f6a7', return: '0', max_drawdown: '0', current_nav: '100000.00', account_age_sessions: 4, eligible: false, eligibility_reason: '账户不足20个交易日', started_at: '2026-07-14T08:00:00Z' }]), period: url.searchParams.get('period'), as_of_date: '2026-07-17' } })
        if (path === '/api/v1/backtests/' && method === 'GET') return route.fulfill({ json: pageOf(backtests) })
        if (path === '/api/v1/backtests/run-1') return route.fulfill({ json: backtests[0] })
        if (path === '/api/v1/paper/admin/cycles') return route.fulfill({ json: pageOf([{ id: 'cycle-1', session_date: '2026-07-17', status: 'succeeded', attempt_count: 1, started_at: '2026-07-17T12:05:00Z', finished_at: '2026-07-17T12:05:10Z', error: '' }]) })
        if (path === '/api/v1/auth/admin/invitations' && method === 'GET') return route.fulfill({ json: pageOf([]) })
        if (path === '/api/v1/auth/admin/invitations' && method === 'POST') return route.fulfill({ status: 201, json: { id: 'invite-2', email: 'new@example.com', note: '测试邀请', expires_at: '2026-07-27T08:00:00Z', state: 'active', created_at: '2026-07-20T08:00:00Z', link: 'https://mt.example/register#token=one-time-admin-token' } })
        if (path === '/api/v1/auth/admin/users') return route.fulfill({ json: pageOf([user]) })
        if (path === '/api/v1/market/admin/batches') return route.fulfill({ json: pageOf([{ id: 'batch-1', status: 'healthy', expected_session: '2026-07-17', errors: [], warnings: [], started_at: '2026-07-17T10:30:00Z', finished_at: '2026-07-17T12:05:00Z', triggered_by: 'schedule' }]) })
        if (path === '/api/v1/strategies/admin') return route.fulfill({ json: pageOf(strategies) })
        if (path === '/api/v1/admin/audit') return route.fulfill({ json: pageOf([]) })

        return route.fulfill({ status: 404, contentType: 'application/problem+json', body: JSON.stringify({ detail: `Unhandled mock: ${method} ${path}` }) })
    })
}

async function expectViewportLayout(page: Page) {
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
    await expect(page.locator('.app-main > footer')).toBeVisible()
}

test.beforeEach(async ({ page }) => {
    await mockAuthenticatedApp(page)
})

test('overview reports ETF health and supports password change', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { name: '总览' })).toBeVisible()
    await expect(page.getByText('1,024 只')).toBeVisible()
    await expect(page.getByText('趋势轮动').first()).toBeVisible()
    await page.getByRole('button', { name: '修改密码' }).click()
    await page.getByLabel('当前密码').fill('current-password')
    await page.getByLabel('新密码').fill('new-secure-password')
    await page.getByRole('button', { name: '保存' }).click()
    await expect(page.getByRole('dialog')).toBeHidden()
    await expectViewportLayout(page)
})

test('ETF directory shows raw history and opens an order ticket', async ({ page }) => {
    await page.goto('/etfs')
    await expect(page.getByRole('heading', { name: 'ETF', exact: true })).toBeVisible()
    await expect(page.getByRole('cell', { name: /510300/ })).toBeVisible()
    await expect(page.getByText('20日均成交额')).toBeVisible()
    await page.getByRole('button', { name: '委托' }).click()
    await expect(page).toHaveURL(/\/trading\?symbol=510300/)
    await expect(page.getByLabel('ETF代码或名称')).toHaveValue('510300')
    await expectViewportLayout(page)
})

test('advice only fills the ticket and user confirms the order', async ({ page }) => {
    await page.goto('/advice')
    await expect(page.getByText('买入').first()).toBeVisible()
    await page.getByRole('button', { name: /采用建议/ }).click()
    await expect(page).toHaveURL(/symbol=159915.*side=buy.*shares=500/)
    await expect(page.getByLabel('委托份额')).toHaveValue('500')
    page.once('dialog', (dialog) => dialog.accept())
    await page.getByRole('button', { name: '确认买入委托' }).click()
    await expect(page.getByText('委托已提交')).toBeVisible()
    const pendingPanel = page.locator('article').filter({ has: page.getByRole('heading', { name: '待处理委托' }) })
    await expect(pendingPanel.getByText('159915')).toBeVisible()
    await expectViewportLayout(page)
})

test('leaderboard is named and marks young accounts unranked', async ({ page }) => {
    await page.goto('/leaderboard')
    await expect(page.getByRole('cell', { name: /管理员/ })).toBeVisible()
    await expect(page.getByText('#a1b2c3d4')).toBeVisible()
    await expect(page.getByText('账户不足20个交易日')).toBeVisible()
    await expect(page.locator('.leaderboard-panel').getByText('admin@example.com')).toHaveCount(0)
    await expectViewportLayout(page)
})

test('policy backtest can be inspected with a rendered chart', async ({ page }) => {
    await page.goto('/backtests')
    await page.locator('.run-row').filter({ hasText: '趋势轮动' }).click()
    await expect(page.getByRole('heading', { name: '结果对比' })).toBeVisible()
    await expect(page.getByText('12.81%')).toBeVisible()
    const chart = page.getByRole('img', { name: '绩效曲线' })
    await expect(chart.locator('canvas')).toBeVisible()
    await expect.poll(() => chart.locator('canvas').evaluate((canvas) => (canvas as HTMLCanvasElement).toDataURL().length)).toBeGreaterThan(1000)
    await expectViewportLayout(page)
})

test('administrator can create a one-time invitation', async ({ page }) => {
    await page.goto('/admin')
    await expect(page.getByText('允许生成新建议')).toBeVisible()
    await page.getByLabel('邮箱').fill('new@example.com')
    await page.getByLabel('备注').fill('测试邀请')
    await page.getByRole('button', { name: '生成一次性链接' }).click()
    await expect(page.getByText(/one-time-admin-token/)).toBeVisible()
    await expectViewportLayout(page)
})
