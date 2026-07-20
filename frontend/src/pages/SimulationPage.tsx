import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArchiveRestore, Clock3, WalletCards } from 'lucide-react'
import { useMemo, useState } from 'react'

import { api } from '../api/client'
import type { MarketStatus, Page, PaperAccount } from '../api/types'
import { Chart } from '../components/Chart'
import { EmptyState } from '../components/EmptyState'
import { Loading } from '../components/Loading'
import { Metric } from '../components/Metric'
import { StatusBadge } from '../components/StatusBadge'

interface Order {
    id: string
    symbol: string
    side: 'buy' | 'sell'
    shares: number
    eligible_on: string
    status: 'filled' | 'rejected'
    rejection_reason: string
    fill?: { price: string; fee: string; filled_on: string; estimated: boolean }
}

interface LedgerEntry {
    id: string
    kind: string
    symbol: string | null
    amount: string
    quantity: string
    occurred_on: string
}

export function SimulationPage() {
    const queryClient = useQueryClient()
    const accounts = useQuery({ queryKey: ['paper-accounts'], queryFn: () => api.get<Page<PaperAccount>>('/paper/accounts?page_size=100') })
    const market = useQuery({ queryKey: ['market-status'], queryFn: () => api.get<MarketStatus>('/market/status') })
    const [selectedId, setSelectedId] = useState<string | null>(null)
    const allAccounts = accounts.data?.results || []
    const active = allAccounts.filter((item) => item.status === 'active')
    const effectiveId = selectedId || active[0]?.id || allAccounts[0]?.id || null
    const detail = useQuery({ queryKey: ['paper-account', effectiveId], queryFn: () => api.get<PaperAccount>(`/paper/accounts/${effectiveId}`), enabled: Boolean(effectiveId) })
    const orders = useQuery({ queryKey: ['paper-orders', effectiveId], queryFn: () => api.get<Page<Order>>(`/paper/accounts/${effectiveId}/orders`), enabled: Boolean(effectiveId) })
    const nav = useQuery({ queryKey: ['paper-nav', effectiveId], queryFn: () => api.get<Page<{ date: string; value: string; cash: string }>>(`/paper/accounts/${effectiveId}/nav?page_size=100`), enabled: Boolean(effectiveId) })
    const ledger = useQuery({ queryKey: ['paper-ledger', effectiveId], queryFn: () => api.get<Page<LedgerEntry>>(`/paper/accounts/${effectiveId}/ledger?page_size=100`), enabled: Boolean(effectiveId) })
    const restart = useMutation({
        mutationFn: () => api.post<PaperAccount>(`/paper/accounts/${effectiveId}/restart`),
        onSuccess: async (account) => { setSelectedId(account.id); await queryClient.invalidateQueries({ queryKey: ['paper-accounts'] }) }
    })
    const option = useMemo(() => ({
        animation: false,
        tooltip: { trigger: 'axis' },
        grid: { left: 48, right: 18, top: 20, bottom: 36 },
        xAxis: { type: 'category', data: nav.data?.results.slice().reverse().map((item) => item.date) || [] },
        yAxis: { type: 'value', scale: true },
        series: [{ type: 'line', data: nav.data?.results.slice().reverse().map((item) => Number(item.value)) || [], showSymbol: false, lineStyle: { color: '#315efb', width: 2 } }]
    }), [nav.data])
    if (accounts.isLoading) return <Loading />

    return (
        <div className="page-stack">
            <header className="page-header"><div><p className="eyebrow">PAPER ACCOUNTS</p><h1>模拟</h1><p>自动执行策略信号，不接入券商。</p></div></header>
            {!allAccounts.length ? <EmptyState title="尚无模拟账户" detail="前往策略页面激活一个固定策略。" /> : (
                <>
                    <div className="account-tabs">{allAccounts.map((account) => <button key={account.id} className={effectiveId === account.id ? 'selected' : ''} onClick={() => setSelectedId(account.id)}><WalletCards size={16} />{account.strategy_name} · 第{account.generation}期{account.status === 'archived' ? '（归档）' : ''}</button>)}</div>
                    {detail.isLoading ? <Loading /> : detail.data && (
                        <>
                            <section className="metric-grid">
                                <Metric label="账户净值" value={`¥${Number(detail.data.latest_nav?.value || detail.data.cash).toLocaleString('zh-CN')}`} />
                                <Metric label="可用资金" value={`¥${Number(detail.data.cash).toLocaleString('zh-CN')}`} />
                                <Metric label="持仓数量" value={`${detail.data.positions?.filter((item) => item.shares > 0).length || 0}`} />
                                <Metric label="账户代次" value={`第 ${detail.data.generation} 期`} />
                            </section>
                            <section className="section-grid two-columns">
                                <article className="panel"><div className="panel-heading"><div><p className="eyebrow">NAV</p><h2>净值曲线</h2></div><StatusBadge ok={detail.data.status === 'active'}>{detail.data.status === 'active' ? '运行中' : '已归档'}</StatusBadge></div>{nav.data?.results.length ? <Chart option={option} height={300} /> : <EmptyState title="等待首个估值日" detail="行情更新后自动生成账户净值。" />}</article>
                                <article className="panel"><div className="panel-heading"><div><p className="eyebrow">POSITIONS</p><h2>当前持仓</h2></div></div>{detail.data.positions?.filter((item) => item.shares > 0).length ? <div className="table-wrap"><table><thead><tr><th>ETF</th><th>份额</th><th>成本</th></tr></thead><tbody>{detail.data.positions.filter((item) => item.shares > 0).map((position) => <tr key={position.symbol}><td><strong>{position.symbol}</strong><span>{position.name}</span></td><td>{position.shares.toLocaleString()}</td><td>¥{Number(position.average_cost).toFixed(4)}</td></tr>)}</tbody></table></div> : <EmptyState title="当前为空仓" detail="等待有效信号及下一交易日行情。" />}</article>
                            </section>
                            {detail.data.pending_rebalances?.map((item) => <div className="pending-banner" key={item.id}><Clock3 size={18} /><div><strong>待估算调仓</strong><span>预计使用 {item.eligible_on} 的真实开盘数据，收盘后写入估算成交。</span></div></div>)}
                            <article className="panel"><div className="panel-heading"><div><p className="eyebrow">ORDERS</p><h2>订单与成交</h2></div>{detail.data.status === 'active' && <button className="secondary-button" onClick={() => { if (window.confirm('旧账户将永久保留并归档，确定重新开始？')) restart.mutate() }} disabled={restart.isPending}><ArchiveRestore size={16} /> 归档并重启</button>}</div>{orders.data?.results.length ? <div className="table-wrap"><table><thead><tr><th>日期</th><th>ETF</th><th>方向</th><th>份额</th><th>估算价格</th><th>费用</th><th>状态</th></tr></thead><tbody>{orders.data.results.map((order) => <tr key={order.id}><td>{order.eligible_on}</td><td>{order.symbol}</td><td className={order.side === 'buy' ? 'number-up' : 'number-down'}>{order.side === 'buy' ? '买入' : '卖出'}</td><td>{order.shares}</td><td>{order.fill ? `¥${order.fill.price}` : '—'}</td><td>{order.fill ? `¥${order.fill.fee}` : '—'}</td><td>{order.status === 'filled' ? '估算成交' : `拒绝：${order.rejection_reason}`}</td></tr>)}</tbody></table></div> : <EmptyState title="暂无订单" detail="每月最后一个交易日收盘后生成调仓。" />}</article>
                            <article className="panel"><div className="panel-heading"><div><p className="eyebrow">LEDGER</p><h2>不可变账本</h2></div></div>{ledger.data?.results.length ? <div className="table-wrap"><table><thead><tr><th>日期</th><th>类型</th><th>ETF</th><th>金额</th><th>份额</th></tr></thead><tbody>{ledger.data.results.map((entry) => <tr key={entry.id}><td>{entry.occurred_on}</td><td>{entry.kind}</td><td>{entry.symbol || '—'}</td><td className={Number(entry.amount) >= 0 ? 'number-up' : 'number-down'}>{entry.amount}</td><td>{entry.quantity}</td></tr>)}</tbody></table></div> : <EmptyState title="暂无账本记录" detail="激活、成交和公司行动会自动入账。" />}</article>
                            <div className="data-footnote">数据截止 {market.data?.expected_session || '—'} · {market.data?.source || '东方财富'} · 原始价估算成交</div>
                        </>
                    )}
                </>
            )}
        </div>
    )
}
