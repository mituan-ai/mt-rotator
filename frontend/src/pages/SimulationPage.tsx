import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Ban, CheckCircle2, Clock3, Search, WalletCards, X } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'

import { api } from '../api/client'
import type { Fill, Instrument, LedgerEntry, NavPoint, Order, Page, PaperAccount } from '../api/types'
import { Chart } from '../components/Chart'
import { EmptyState } from '../components/EmptyState'
import { Loading } from '../components/Loading'
import { Metric } from '../components/Metric'
import { StatusBadge } from '../components/StatusBadge'

export function SimulationPage() {
    const queryClient = useQueryClient()
    const [searchParams] = useSearchParams()
    const [selectedId, setSelectedId] = useState<string | null>(null)
    const [symbol, setSymbol] = useState(searchParams.get('symbol') || '')
    const [side, setSide] = useState<'buy' | 'sell'>(searchParams.get('side') === 'sell' ? 'sell' : 'buy')
    const [shares, setShares] = useState(searchParams.get('shares') || '100')
    const [clientRequestId, setClientRequestId] = useState('')
    const [confirmedOrder, setConfirmedOrder] = useState<Order | null>(null)

    const accounts = useQuery({ queryKey: ['paper-accounts'], queryFn: () => api.get<Page<PaperAccount>>('/paper/accounts?page_size=100') })
    const allAccounts = accounts.data?.results || []
    const manual = allAccounts.find((item) => item.mode === 'manual' && item.status === 'active')
    const effectiveId = selectedId || manual?.id || allAccounts[0]?.id || null
    const selectedSummary = allAccounts.find((item) => item.id === effectiveId)
    const canTrade = selectedSummary?.mode === 'manual' && selectedSummary.status === 'active'

    const detail = useQuery({ queryKey: ['paper-account', effectiveId], queryFn: () => api.get<PaperAccount>(`/paper/accounts/${effectiveId}`), enabled: Boolean(effectiveId) })
    const orders = useQuery({ queryKey: ['paper-orders', effectiveId], queryFn: () => api.get<Page<Order>>(`/paper/accounts/${effectiveId}/orders?page_size=100`), enabled: Boolean(effectiveId) })
    const fills = useQuery({ queryKey: ['paper-fills', effectiveId], queryFn: () => api.get<Page<Fill>>(`/paper/accounts/${effectiveId}/fills?page_size=100`), enabled: Boolean(effectiveId) })
    const nav = useQuery({ queryKey: ['paper-nav', effectiveId], queryFn: () => api.get<Page<NavPoint>>(`/paper/accounts/${effectiveId}/nav?page_size=100`), enabled: Boolean(effectiveId) })
    const ledger = useQuery({ queryKey: ['paper-ledger', effectiveId], queryFn: () => api.get<Page<LedgerEntry>>(`/paper/accounts/${effectiveId}/ledger?page_size=100`), enabled: Boolean(effectiveId) })
    const instrument = useQuery({
        queryKey: ['instrument-detail', symbol],
        queryFn: () => api.get<Instrument>(`/market/instruments/${symbol}`),
        enabled: /^\d{6}$/.test(symbol)
    })
    const suggestions = useQuery({
        queryKey: ['instrument-suggestions', symbol],
        queryFn: () => api.get<Page<Instrument>>(`/market/instruments?q=${encodeURIComponent(symbol)}&page_size=8&tradable=true`),
        enabled: symbol.trim().length >= 2 && !/^\d{6}$/.test(symbol)
    })
    const createOrder = useMutation({
        mutationFn: (payload: { instrument: string; side: 'buy' | 'sell'; shares: number; client_request_id: string }) => api.post<Order>(`/paper/accounts/${effectiveId}/orders`, payload),
        onSuccess: async (order) => {
            setConfirmedOrder(order)
            setClientRequestId('')
            await Promise.all([
                queryClient.invalidateQueries({ queryKey: ['paper-account', effectiveId] }),
                queryClient.invalidateQueries({ queryKey: ['paper-orders', effectiveId] })
            ])
        }
    })
    const cancelOrder = useMutation({
        mutationFn: (orderId: string) => api.post<Order>(`/paper/accounts/${effectiveId}/orders/${orderId}/cancel`),
        onSuccess: async () => {
            await Promise.all([
                queryClient.invalidateQueries({ queryKey: ['paper-account', effectiveId] }),
                queryClient.invalidateQueries({ queryKey: ['paper-orders', effectiveId] })
            ])
        }
    })

    const navOption = useMemo(() => ({
        animation: false,
        tooltip: { trigger: 'axis' },
        grid: { left: 52, right: 18, top: 20, bottom: 36 },
        xAxis: { type: 'category', data: nav.data?.results.slice().reverse().map((item) => item.date) || [], axisLabel: { hideOverlap: true } },
        yAxis: { type: 'value', scale: true },
        series: [{ type: 'line', data: nav.data?.results.slice().reverse().map((item) => Number(item.value)) || [], showSymbol: false, lineStyle: { color: '#315efb', width: 2 } }]
    }), [nav.data])

    const pendingReserved = detail.data?.pending_orders?.filter((item) => item.side === 'buy').reduce((sum, item) => sum + Number(item.reserved_cash), 0) || 0

    function submitOrder(event: FormEvent) {
        event.preventDefault()
        setConfirmedOrder(null)
        const quantity = Number(shares)
        if (!canTrade || !instrument.data || !Number.isInteger(quantity) || quantity <= 0) return
        const eligible = nextOrderDateText()
        const accepted = window.confirm(`确认${side === 'buy' ? '买入' : '卖出'} ${instrument.data.symbol} ${quantity.toLocaleString()} 份？\n委托将在${eligible}开盘批次按真实日线估算成交。`)
        if (!accepted) return
        const requestId = clientRequestId || crypto.randomUUID()
        setClientRequestId(requestId)
        createOrder.mutate({ instrument: instrument.data.symbol, side, shares: quantity, client_request_id: requestId })
    }

    if (accounts.isLoading) return <Loading />

    return (
        <div className="page-stack">
            <header className="page-header">
                <div><p className="eyebrow">PAPER TRADING</p><h1>交易</h1><p>自主确认委托，下一交易日开盘估算成交。</p></div>
            </header>
            {!allAccounts.length ? <EmptyState title="尚无模拟账户" detail="登录后系统会自动创建唯一自主账户。" /> : (
                <>
                    <div className="account-tabs">{allAccounts.map((account) => <button key={account.id} className={effectiveId === account.id ? 'selected' : ''} onClick={() => setSelectedId(account.id)}><WalletCards size={16} />{account.mode === 'manual' ? `自主账户 ${account.account_number}` : `${account.strategy_name || '历史策略'}（只读）`}</button>)}</div>
                    {detail.isLoading ? <Loading /> : detail.error ? <p className="form-error">{detail.error.message}</p> : detail.data && (
                        <>
                            <section className="metric-grid">
                                <Metric label="账户净值" value={`¥${Number(detail.data.latest_nav?.value || detail.data.cash).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`} />
                                <Metric label="账户现金" value={`¥${Number(detail.data.cash).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`} />
                                <Metric label="已预留资金" value={`¥${pendingReserved.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`} />
                                <Metric label="持仓ETF" value={`${detail.data.positions?.filter((item) => item.shares > 0).length || 0} 只`} />
                            </section>

                            {canTrade && (
                                <section className="trade-layout">
                                    <form className="panel order-ticket" onSubmit={submitOrder}>
                                        <div className="panel-heading"><div><p className="eyebrow">ORDER</p><h2>开盘委托</h2></div><Clock3 size={19} /></div>
                                        <div className="side-control"><button type="button" className={side === 'buy' ? 'selected buy-side' : ''} onClick={() => setSide('buy')}>买入</button><button type="button" className={side === 'sell' ? 'selected sell-side' : ''} onClick={() => setSide('sell')}>卖出</button></div>
                                        <label>ETF代码或名称<div className="search-input"><Search size={16} /><input required value={symbol} onChange={(event) => setSymbol(event.target.value.trim())} placeholder="输入代码或名称" /></div></label>
                                        {suggestions.data?.results.length ? <div className="suggestion-list">{suggestions.data.results.map((item) => <button type="button" key={item.symbol} onClick={() => setSymbol(item.symbol)}><strong>{item.symbol}</strong><span>{item.name}</span></button>)}</div> : null}
                                        {instrument.data && <div className="instrument-selection"><div><strong>{instrument.data.symbol} {instrument.data.name}</strong><span>{instrument.data.settlement_cycle === 't0' ? 'T+0' : 'T+1'} · 最新收盘 {instrument.data.latest_close ? `¥${instrument.data.latest_close}` : '—'}</span></div><StatusBadge ok={instrument.data.trade_eligible}>{instrument.data.trade_eligible ? '可交易' : '不可交易'}</StatusBadge></div>}
                                        {instrument.error && <p className="form-error">{instrument.error.message}</p>}
                                        <label>委托份额<input type="number" min="100" step="100" required value={shares} onChange={(event) => setShares(event.target.value)} /></label>
                                        <div className="assumption-box"><span>100份整数倍</span><span>5 bps滑点</span><span>佣金万三，最低5元</span><span>整单成交或拒绝</span></div>
                                        <button className={side === 'buy' ? 'primary-button buy-order-button' : 'primary-button sell-order-button'} disabled={createOrder.isPending || !instrument.data?.trade_eligible}>{createOrder.isPending ? '正在提交' : `确认${side === 'buy' ? '买入' : '卖出'}委托`}</button>
                                        {createOrder.error && <p className="form-error">{createOrder.error.message}</p>}
                                        {confirmedOrder && <div className="order-confirmed"><CheckCircle2 size={17} /><div><strong>委托已提交</strong><span>{confirmedOrder.eligible_on} 开盘处理，届时可成交、拒绝或过期。</span></div></div>}
                                    </form>
                                    <article className="panel">
                                        <div className="panel-heading"><div><p className="eyebrow">POSITIONS</p><h2>当前持仓</h2></div><StatusBadge ok>{detail.data.account_number}</StatusBadge></div>
                                        {detail.data.positions?.some((item) => item.shares > 0) ? <div className="table-wrap"><table><thead><tr><th>ETF</th><th>持仓</th><th>可卖</th><th>成本</th><th>交收</th></tr></thead><tbody>{detail.data.positions.filter((item) => item.shares > 0).map((position) => <tr key={position.symbol}><td><strong>{position.symbol}</strong><span>{position.name}</span></td><td>{position.shares.toLocaleString()}</td><td>{position.sellable_shares.toLocaleString()}</td><td>¥{Number(position.average_cost).toFixed(4)}</td><td>{position.settlement_cycle === 't0' ? 'T+0' : 'T+1'}</td></tr>)}</tbody></table></div> : <EmptyState title="当前为空仓" detail="提交买入委托后，在有效交易日开盘处理。" />}
                                    </article>
                                </section>
                            )}

                            {!canTrade && <div className="readonly-banner"><Ban size={18} /><div><strong>历史自动账户只读</strong><span>旧订单、持仓和账本完整保留，不能继续下单或重启。</span></div></div>}

                            <section className="section-grid two-columns">
                                <article className="panel"><div className="panel-heading"><div><p className="eyebrow">NAV</p><h2>净值曲线</h2></div></div>{nav.data?.results.length ? <Chart option={navOption} height={300} /> : <EmptyState title="等待首个估值日" detail="行情处理完成后写入净值。" />}</article>
                                <article className="panel"><div className="panel-heading"><div><p className="eyebrow">PENDING</p><h2>待处理委托</h2></div></div>{orders.data?.results.some((item) => item.status === 'pending') ? <div className="table-wrap"><table><thead><tr><th>ETF</th><th>方向</th><th>份额</th><th>有效日</th><th>预留</th><th>操作</th></tr></thead><tbody>{orders.data.results.filter((item) => item.status === 'pending').map((order) => <tr key={order.id}><td>{order.symbol}<span>{order.name}</span></td><td className={order.side === 'buy' ? 'number-up' : 'number-down'}>{order.side === 'buy' ? '买入' : '卖出'}</td><td>{order.shares.toLocaleString()}</td><td>{order.eligible_on}</td><td>¥{Number(order.reserved_cash).toLocaleString('zh-CN')}</td><td>{order.cancellable && <button className="icon-button" aria-label="撤销委托" disabled={cancelOrder.isPending} onClick={() => cancelOrder.mutate(order.id)}><X size={14} /></button>}</td></tr>)}</tbody></table></div> : <EmptyState title="没有待处理委托" detail="用户委托只在下一交易日开盘批次有效。" />}{cancelOrder.error && <p className="form-error">{cancelOrder.error.message}</p>}</article>
                            </section>

                            <article className="panel"><div className="panel-heading"><div><p className="eyebrow">FILLS</p><h2>成交记录</h2></div></div>{fills.data?.results.length ? <div className="table-wrap"><table><thead><tr><th>日期</th><th>ETF</th><th>方向</th><th>份额</th><th>价格</th><th>费用</th><th>口径</th></tr></thead><tbody>{fills.data.results.map((fill) => <tr key={fill.id}><td>{fill.filled_on}</td><td>{fill.symbol}</td><td className={fill.side === 'buy' ? 'number-up' : 'number-down'}>{fill.side === 'buy' ? '买入' : '卖出'}</td><td>{fill.shares.toLocaleString()}</td><td>¥{Number(fill.price).toFixed(4)}</td><td>¥{Number(fill.fee).toFixed(2)}</td><td>{fill.estimated ? '估算成交' : '—'}</td></tr>)}</tbody></table></div> : <EmptyState title="暂无成交" detail="成交后会保留对应订单和费用。" />}</article>

                            <article className="panel"><div className="panel-heading"><div><p className="eyebrow">ORDERS</p><h2>全部订单</h2></div></div>{orders.data?.results.length ? <div className="table-wrap"><table><thead><tr><th>提交时间</th><th>ETF</th><th>方向</th><th>份额</th><th>有效日</th><th>状态</th></tr></thead><tbody>{orders.data.results.map((order) => <tr key={order.id}><td>{new Date(order.created_at).toLocaleString('zh-CN')}</td><td>{order.symbol}<span>{order.name}</span></td><td className={order.side === 'buy' ? 'number-up' : 'number-down'}>{order.side === 'buy' ? '买入' : '卖出'}</td><td>{order.shares.toLocaleString()}</td><td>{order.eligible_on}</td><td>{orderStatus(order)}{order.rejection_reason && <span>{order.rejection_reason}</span>}</td></tr>)}</tbody></table></div> : <EmptyState title="暂无订单" detail="所有委托都由用户主动确认。" />}</article>

                            <article className="panel"><div className="panel-heading"><div><p className="eyebrow">LEDGER</p><h2>不可变账本</h2></div></div>{ledger.data?.results.length ? <div className="table-wrap"><table><thead><tr><th>日期</th><th>类型</th><th>ETF</th><th>金额</th><th>份额</th></tr></thead><tbody>{ledger.data.results.map((entry) => <tr key={entry.id}><td>{entry.occurred_on}</td><td>{ledgerKind(entry.kind)}</td><td>{entry.symbol || '—'}</td><td className={Number(entry.amount) >= 0 ? 'number-up' : 'number-down'}>{entry.amount}</td><td>{entry.quantity}</td></tr>)}</tbody></table></div> : <EmptyState title="暂无账本记录" detail="入金、成交和公司行动会写入账本。" />}</article>
                            <div className="data-footnote">真实免费日线 · 次日开盘估算成交 · 不接入券商</div>
                        </>
                    )}
                </>
            )}
        </div>
    )
}

function nextOrderDateText(): string {
    return '下一交易日'
}

function orderStatus(order: Order): string {
    return { pending: '待处理', filled: '已成交', rejected: '已拒绝', cancelled: '已撤销', expired: '已过期' }[order.status]
}

function ledgerKind(kind: LedgerEntry['kind']): string {
    return { deposit: '入金', buy: '买入', sell: '卖出', fee: '费用', dividend: '分红', split: '拆分' }[kind]
}
