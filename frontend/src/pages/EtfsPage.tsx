import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight, Search, ShoppingCart } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import type { Instrument, InstrumentBarsResponse, Page } from '../api/types'
import { Chart } from '../components/Chart'
import { EmptyState } from '../components/EmptyState'
import { Loading } from '../components/Loading'
import { StatusBadge } from '../components/StatusBadge'

const ASSET_CLASSES = [
    ['', '全部分类'],
    ['equity', '股票'],
    ['bond', '债券'],
    ['money', '货币'],
    ['gold', '黄金'],
    ['cross_border', '跨境'],
    ['commodity', '商品'],
    ['unknown', '未分类']
] as const

const ASSET_LABELS = Object.fromEntries(ASSET_CLASSES) as Record<string, string>

export function EtfsPage() {
    const navigate = useNavigate()
    const [draft, setDraft] = useState('')
    const [query, setQuery] = useState('')
    const [assetClass, setAssetClass] = useState('')
    const [tradable, setTradable] = useState(false)
    const [page, setPage] = useState(1)
    const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)

    const instruments = useQuery({
        queryKey: ['instruments', query, assetClass, tradable, page],
        queryFn: () => {
            const params = new URLSearchParams({ page: String(page), page_size: '25' })
            if (query) params.set('q', query)
            if (assetClass) params.set('asset_class', assetClass)
            if (tradable) params.set('tradable', 'true')
            return api.get<Page<Instrument>>(`/market/instruments?${params}`)
        }
    })
    const effectiveSymbol = selectedSymbol || instruments.data?.results[0]?.symbol || null
    const bars = useQuery({
        queryKey: ['instrument-bars', effectiveSymbol],
        queryFn: () => api.get<InstrumentBarsResponse>(`/market/instruments/${effectiveSymbol}/bars`),
        enabled: Boolean(effectiveSymbol)
    })
    const option = useMemo(() => ({
        animation: false,
        tooltip: { trigger: 'axis' },
        grid: { left: 54, right: 18, top: 20, bottom: 38 },
        xAxis: {
            type: 'category',
            data: bars.data?.bars.map((item) => item.date) || [],
            axisLabel: { hideOverlap: true }
        },
        yAxis: { type: 'value', scale: true },
        series: [{
            name: '收盘价',
            type: 'line',
            data: bars.data?.bars.map((item) => Number(item.close)) || [],
            showSymbol: false,
            lineStyle: { color: '#315efb', width: 2 }
        }]
    }), [bars.data])

    function submitSearch(event: FormEvent) {
        event.preventDefault()
        setPage(1)
        setSelectedSymbol(null)
        setQuery(draft.trim())
    }

    const selected = bars.data?.instrument

    return (
        <div className="page-stack">
            <header className="page-header">
                <div><p className="eyebrow">ETF DIRECTORY</p><h1>ETF</h1><p>新浪财经日线，完整目录可搜索。</p></div>
            </header>
            <form className="filter-bar" onSubmit={submitSearch}>
                <label className="search-field"><span>代码或名称</span><div><Search size={16} /><input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="510300 或 沪深300" /></div></label>
                <label><span>资产分类</span><select value={assetClass} onChange={(event) => { setAssetClass(event.target.value); setPage(1); setSelectedSymbol(null) }}>{ASSET_CLASSES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
                <label className="checkbox-field"><input type="checkbox" checked={tradable} onChange={(event) => { setTradable(event.target.checked); setPage(1); setSelectedSymbol(null) }} /><span>只看可交易</span></label>
                <button className="primary-button" type="submit"><Search size={15} /> 搜索</button>
            </form>
            {instruments.error && <p className="form-error">{instruments.error.message}</p>}
            <section className="etf-layout">
                <article className="panel etf-list-panel">
                    <div className="panel-heading"><div><p className="eyebrow">RESULTS</p><h2>{instruments.data?.count || 0} 只ETF</h2></div></div>
                    {instruments.isLoading ? <Loading /> : instruments.data?.results.length ? (
                        <>
                            <div className="table-wrap">
                                <table className="interactive-table">
                                    <thead><tr><th>ETF</th><th>分类</th><th>最新收盘</th><th>20日均成交额</th><th>交收</th><th>状态</th></tr></thead>
                                    <tbody>{instruments.data.results.map((item) => (
                                        <tr key={item.symbol} className={effectiveSymbol === item.symbol ? 'selected-row' : ''} onClick={() => setSelectedSymbol(item.symbol)}>
                                            <td><strong>{item.symbol}</strong><span>{item.name}</span></td>
                                            <td>{ASSET_LABELS[item.asset_class] || '未分类'}</td>
                                            <td>{item.latest_close ? `¥${Number(item.latest_close).toFixed(4)}` : '—'}<span>{item.last_bar_date || '暂无日期'}</span></td>
                                            <td>{formatAmount(item.average_amount_20d)}</td>
                                            <td>{item.settlement_cycle === 't0' ? 'T+0' : 'T+1'}</td>
                                            <td><StatusBadge ok={item.trade_eligible}>{item.trade_eligible ? '可交易' : statusText(item.data_status)}</StatusBadge></td>
                                        </tr>
                                    ))}</tbody>
                                </table>
                            </div>
                            <div className="pagination-bar">
                                <button className="icon-button" aria-label="上一页" disabled={!instruments.data.previous} onClick={() => setPage((value) => Math.max(1, value - 1))}><ArrowLeft size={15} /></button>
                                <span>第 {page} 页</span>
                                <button className="icon-button" aria-label="下一页" disabled={!instruments.data.next} onClick={() => setPage((value) => value + 1)}><ArrowRight size={15} /></button>
                            </div>
                        </>
                    ) : <EmptyState title="没有匹配的ETF" detail="调整代码、名称或分类筛选。" />}
                </article>
                <article className="panel etf-detail-panel">
                    {!effectiveSymbol ? <EmptyState title="选择ETF" detail="从目录中选择一只ETF查看日线。" /> : bars.isLoading ? <Loading /> : bars.error ? <p className="form-error">{bars.error.message}</p> : selected && (
                        <>
                            <div className="panel-heading">
                                <div><p className="eyebrow">{selected.symbol}</p><h2>{selected.name}</h2></div>
                                <button className="secondary-button" disabled={!selected.trade_eligible} onClick={() => navigate(`/trading?symbol=${selected.symbol}`)}><ShoppingCart size={15} /> 委托</button>
                            </div>
                            <div className="instrument-facts">
                                <div><span>最新收盘</span><strong>{selected.latest_close ? `¥${Number(selected.latest_close).toFixed(4)}` : '—'}</strong></div>
                                <div><span>交易规则</span><strong>{selected.settlement_cycle === 't0' ? 'T+0' : 'T+1'}</strong></div>
                                <div><span>数据日期</span><strong>{selected.last_bar_date || '—'}</strong></div>
                                <div><span>建议资格</span><strong>{selected.advice_eligible ? '可进入建议池' : '暂不符合'}</strong></div>
                            </div>
                            {bars.data?.bars.length ? <Chart option={option} height={330} /> : <EmptyState title="暂无历史日线" detail="等待行情任务完成回填。" />}
                            <div className="data-footnote">{bars.data?.source} · 原始日线 · 非实时行情</div>
                        </>
                    )}
                </article>
            </section>
        </div>
    )
}

function formatAmount(value: string): string {
    const amount = Number(value)
    if (!Number.isFinite(amount) || amount <= 0) return '—'
    if (amount >= 100_000_000) return `${(amount / 100_000_000).toFixed(2)}亿`
    return `${(amount / 10_000).toFixed(0)}万`
}

function statusText(status: Instrument['data_status']): string {
    return { ready: '流动性不足', stale: '数据陈旧', missing: '数据缺失', blocked: '已暂停' }[status]
}
