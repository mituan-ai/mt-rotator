import { useQuery } from '@tanstack/react-query'
import { Activity, ArrowUpRight, Clock3, Database, WalletCards } from 'lucide-react'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import type { MarketStatus, Page, PaperAccount, Strategy } from '../api/types'
import { EmptyState } from '../components/EmptyState'
import { Loading } from '../components/Loading'
import { Metric } from '../components/Metric'
import { StatusBadge } from '../components/StatusBadge'

export function DashboardPage() {
    const market = useQuery({ queryKey: ['market-status'], queryFn: () => api.get<MarketStatus>('/market/status') })
    const strategies = useQuery({ queryKey: ['strategies'], queryFn: () => api.get<Page<Strategy>>('/strategies/') })
    const accounts = useQuery({ queryKey: ['paper-accounts'], queryFn: () => api.get<Page<PaperAccount>>('/paper/accounts') })
    if (market.isLoading || strategies.isLoading || accounts.isLoading) return <Loading />

    return (
        <div className="page-stack">
            <header className="page-header">
                <div><p className="eyebrow">OVERVIEW</p><h1>总览</h1></div>
                <StatusBadge ok={Boolean(market.data?.ready)}>{market.data?.ready ? '数据已就绪' : '数据不可用'}</StatusBadge>
            </header>
            <section className="metric-grid">
                <Metric label="行情截止" value={market.data?.expected_session || '—'} />
                <Metric label="运行策略" value={`${strategies.data?.count || 0}`} />
                <Metric label="模拟账户" value={`${accounts.data?.results.filter((item) => item.status === 'active').length || 0}`} />
                <Metric label="数据来源" value="东方财富" />
            </section>
            <section className="section-grid two-columns">
                <article className="panel">
                    <div className="panel-heading"><div><p className="eyebrow">SIGNALS</p><h2>最新信号</h2></div><Link to="/strategies">全部策略 <ArrowUpRight size={15} /></Link></div>
                    <div className="list-stack">
                        {strategies.data?.results.map((strategy) => <SignalRow key={strategy.id} strategy={strategy} />)}
                    </div>
                </article>
                <article className="panel">
                    <div className="panel-heading"><div><p className="eyebrow">ACCOUNTS</p><h2>模拟账户</h2></div><Link to="/simulation">账户详情 <ArrowUpRight size={15} /></Link></div>
                    {!accounts.data?.results.some((item) => item.status === 'active') ? <EmptyState title="尚未激活账户" detail="选择策略后即可开始自动模拟。" /> : (
                        <div className="list-stack">
                            {accounts.data.results.filter((item) => item.status === 'active').map((account) => (
                                <div className="account-row" key={account.id}>
                                    <div className="row-icon"><WalletCards size={18} /></div>
                                    <div><strong>{account.strategy_name}</strong><span>第 {account.generation} 期</span></div>
                                    <div className="row-value"><strong>¥{Number(account.latest_nav?.value || account.cash).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}</strong><span>可用 ¥{Number(account.cash).toLocaleString('zh-CN')}</span></div>
                                </div>
                            ))}
                        </div>
                    )}
                </article>
            </section>
            <article className="panel data-trust-panel">
                <div className="trust-item"><Database size={18} /><div><strong>{market.data?.source}</strong><span>日线收盘后更新，不作为实时行情</span></div></div>
                <div className="trust-item"><Activity size={18} /><div><strong>{market.data?.last_batch?.status || '尚无批次'}</strong><span>校验来源：{market.data?.validation_source}</span></div></div>
                <div className="trust-item"><Clock3 size={18} /><div><strong>次日开盘估算</strong><span>信号不会使用同日收盘价成交</span></div></div>
            </article>
        </div>
    )
}

function SignalRow({ strategy }: { strategy: Strategy }) {
    const signal = strategy.latest_signal
    return (
        <div className="signal-row">
            <div className="row-icon"><Activity size={18} /></div>
            <div><strong>{strategy.name}</strong><span>版本 {strategy.version}</span></div>
            <div className="row-value"><strong>{signal ? '已有信号' : '等待信号'}</strong><span>{signal ? `${signal.signal_date} 收盘后` : '月末收盘后生成'}</span></div>
        </div>
    )
}
