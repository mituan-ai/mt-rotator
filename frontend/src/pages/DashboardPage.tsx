import { useQuery } from '@tanstack/react-query'
import { Activity, ArrowUpRight, Database, Lightbulb, WalletCards } from 'lucide-react'
import { Link } from 'react-router-dom'

import { api, ApiError } from '../api/client'
import type { Advice, MarketStatus, Page, PaperAccount } from '../api/types'
import { EmptyState } from '../components/EmptyState'
import { Loading } from '../components/Loading'
import { Metric } from '../components/Metric'
import { StatusBadge } from '../components/StatusBadge'

export function DashboardPage() {
    const market = useQuery({ queryKey: ['market-status'], queryFn: () => api.get<MarketStatus>('/market/status') })
    const accounts = useQuery({ queryKey: ['paper-accounts'], queryFn: () => api.get<Page<PaperAccount>>('/paper/accounts?page_size=100') })
    const account = accounts.data?.results.find((item) => item.mode === 'manual' && item.status === 'active')
    const advice = useQuery({
        queryKey: ['paper-advice-current', account?.id, account?.strategy_id, account?.risk_level],
        queryFn: () => api.get<Advice>(`/paper/accounts/${account?.id}/advice/current`),
        enabled: Boolean(account?.id && account?.strategy_id),
        retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 1
    })
    if (market.isLoading || accounts.isLoading) return <Loading />

    const actionable = advice.data?.recommendations.filter((item) => item.actionable) || []
    const status = market.data

    return (
        <div className="page-stack">
            <header className="page-header">
                <div><p className="eyebrow">OVERVIEW</p><h1>总览</h1></div>
                <StatusBadge ok={Boolean(status?.ready)}>{status?.ready ? '建议数据已就绪' : '新建议暂停'}</StatusBadge>
            </header>
            <section className="metric-grid">
                <Metric label="ETF目录" value={`${(status?.counts.catalog || 0).toLocaleString('zh-CN')} 只`} />
                <Metric label="可模拟交易" value={`${(status?.counts.trade_eligible || 0).toLocaleString('zh-CN')} 只`} />
                <Metric label="可进入建议" value={`${(status?.counts.advice_eligible || 0).toLocaleString('zh-CN')} 只`} />
                <Metric label="行情截止" value={status?.expected_session || '—'} />
            </section>
            <section className="section-grid two-columns">
                <article className="panel">
                    <div className="panel-heading"><div><p className="eyebrow">ACCOUNT</p><h2>自主账户</h2></div><Link to="/trading">交易 <ArrowUpRight size={15} /></Link></div>
                    {!account ? <EmptyState title="账户尚未建立" detail="刷新后仍未出现时请联系管理员。" /> : (
                        <div className="account-overview">
                            <div className="account-identity"><div className="row-icon"><WalletCards size={18} /></div><div><strong>#{account.account_number}</strong><span>{riskText(account.risk_level)} · {account.strategy_name || '未选择建议策略'}</span></div></div>
                            <strong className="account-nav">¥{Number(account.latest_nav?.value || account.cash).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>
                            <div className="account-cash"><span>现金</span><strong>¥{Number(account.cash).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}</strong></div>
                        </div>
                    )}
                </article>
                <article className="panel">
                    <div className="panel-heading"><div><p className="eyebrow">ADVICE</p><h2>最新建议</h2></div><Link to="/advice">详情 <ArrowUpRight size={15} /></Link></div>
                    {!account?.strategy_id ? <EmptyState title="尚未选择策略" detail="前往建议页选择策略和风险档位。" /> : advice.isLoading ? <Loading /> : advice.error ? <EmptyState title="建议尚未生成" detail={advice.error.message} /> : advice.data && (
                        <div className="advice-overview">
                            <div className="advice-overview-head"><div className="row-icon"><Lightbulb size={18} /></div><div><strong>{advice.data.strategy_name}</strong><span>{advice.data.session_date} · 有效至 {advice.data.expires_on}</span></div><StatusBadge ok={!advice.data.stale}>{advice.data.stale ? '已过期' : '有效'}</StatusBadge></div>
                            {actionable.length ? <div className="mini-advice-list">{actionable.slice(0, 4).map((item) => <div key={item.symbol}><strong>{item.symbol}</strong><span>{actionText(item.action)} {item.quantity.toLocaleString()}份</span></div>)}</div> : <p className="muted-copy">当前没有需要确认的持仓调整。</p>}
                        </div>
                    )}
                </article>
            </section>
            <article className="panel data-health-panel">
                <div className="panel-heading"><div><p className="eyebrow">MARKET DATA</p><h2>数据健康</h2></div><Link to="/etfs">ETF目录 <ArrowUpRight size={15} /></Link></div>
                <div className="health-counts">
                    <div><span className="health-dot ready" /><strong>{status?.counts.ready || 0}</strong><span>正常</span></div>
                    <div><span className="health-dot stale" /><strong>{status?.counts.stale || 0}</strong><span>陈旧</span></div>
                    <div><span className="health-dot missing" /><strong>{status?.counts.missing || 0}</strong><span>缺失</span></div>
                    <div><span className="health-dot blocked" /><strong>{status?.counts.blocked || 0}</strong><span>暂停</span></div>
                </div>
                {status?.instruments.length ? <div className="health-warning"><Activity size={17} /><span>{status.instruments.length} 只ETF需要更新或人工处理；其他正常ETF仍可查询和委托。</span></div> : null}
                <div className="trust-line"><Database size={15} /><span>{status?.source || '新浪财经，经 AKShare 获取'} · 原始日线 · 覆盖率 {`${(Number(status?.coverage || 0) * 100).toFixed(1)}%`}</span></div>
            </article>
        </div>
    )
}

function riskText(value: PaperAccount['risk_level']): string {
    return { conservative: '保守', balanced: '均衡', aggressive: '进取' }[value]
}

function actionText(value: string): string {
    return { buy: '买入', reduce: '减仓', sell: '卖出' }[value] || value
}
