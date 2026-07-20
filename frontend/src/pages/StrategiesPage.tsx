import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, ArrowRight, Check, Clock3, Lightbulb } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { api, ApiError } from '../api/client'
import type { Advice, Page, PaperAccount, Strategy } from '../api/types'
import { EmptyState } from '../components/EmptyState'
import { Loading } from '../components/Loading'
import { StatusBadge } from '../components/StatusBadge'

const RISK_LEVELS = [
    ['conservative', '保守', '最多3只'],
    ['balanced', '均衡', '最多5只'],
    ['aggressive', '进取', '最多8只']
] as const

const ACTION_LABELS: Record<string, string> = {
    watch: '观察',
    buy: '买入',
    hold: '持有',
    reduce: '减仓',
    sell: '卖出',
    waiting: '等待可卖',
    cooldown: '冷却'
}

export function StrategiesPage() {
    const navigate = useNavigate()
    const queryClient = useQueryClient()
    const strategies = useQuery({ queryKey: ['strategies'], queryFn: () => api.get<Page<Strategy>>('/strategies/?page_size=100') })
    const accounts = useQuery({ queryKey: ['paper-accounts'], queryFn: () => api.get<Page<PaperAccount>>('/paper/accounts?page_size=100') })
    const account = accounts.data?.results.find((item) => item.mode === 'manual' && item.status === 'active')
    const currentAdvice = useQuery({
        queryKey: ['paper-advice-current', account?.id, account?.strategy_id, account?.risk_level],
        queryFn: () => api.get<Advice>(`/paper/accounts/${account?.id}/advice/current`),
        enabled: Boolean(account?.id && account?.strategy_id),
        retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 1
    })
    const adviceHistory = useQuery({
        queryKey: ['paper-advice-history', account?.id],
        queryFn: () => api.get<Page<Advice>>(`/paper/accounts/${account?.id}/advice?page_size=10`),
        enabled: Boolean(account?.id)
    })
    const updatePreference = useMutation({
        mutationFn: (payload: { strategy_version_id?: string; risk_level?: PaperAccount['risk_level'] }) => api.patch<PaperAccount>(`/paper/accounts/${account?.id}`, payload),
        onSuccess: async () => {
            await Promise.all([
                queryClient.invalidateQueries({ queryKey: ['paper-accounts'] }),
                queryClient.invalidateQueries({ queryKey: ['paper-advice-current'] }),
                queryClient.invalidateQueries({ queryKey: ['paper-advice-history'] })
            ])
        }
    })

    if (strategies.isLoading || accounts.isLoading) return <Loading />

    const advice = currentAdvice.data

    return (
        <div className="page-stack">
            <header className="page-header">
                <div><p className="eyebrow">ADVICE</p><h1>建议</h1><p>策略只生成建议，委托必须由你确认。</p></div>
                {advice && <StatusBadge ok={!advice.stale && advice.status === 'ready'}>{advice.stale || advice.status === 'stale' ? '建议已过期' : `有效至 ${advice.expires_on}`}</StatusBadge>}
            </header>
            {!account ? <EmptyState title="自主账户尚未建立" detail="刷新页面或联系管理员检查账户迁移。" /> : (
                <>
                    <article className="panel preference-panel">
                        <div className="panel-heading"><div><p className="eyebrow">SETTINGS</p><h2>建议设置</h2></div><Lightbulb size={20} /></div>
                        <div className="preference-grid">
                            <div>
                                <span className="field-label">策略</span>
                                <div className="choice-grid strategy-choice-grid">
                                    {strategies.data?.results.map((strategy) => (
                                        <button key={strategy.id} className={account.strategy_id === strategy.id ? 'choice-button selected' : 'choice-button'} disabled={updatePreference.isPending} onClick={() => updatePreference.mutate({ strategy_version_id: strategy.id })}>
                                            <span>{strategy.name}</span><small>v{strategy.version}</small>{account.strategy_id === strategy.id && <Check size={15} />}
                                        </button>
                                    ))}
                                </div>
                            </div>
                            <div>
                                <span className="field-label">风险档位</span>
                                <div className="choice-grid risk-choice-grid">
                                    {RISK_LEVELS.map(([value, label, detail]) => (
                                        <button key={value} className={account.risk_level === value ? 'choice-button selected' : 'choice-button'} disabled={updatePreference.isPending} onClick={() => updatePreference.mutate({ risk_level: value })}>
                                            <span>{label}</span><small>{detail}</small>{account.risk_level === value && <Check size={15} />}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        </div>
                        {updatePreference.error && <p className="form-error">{updatePreference.error.message}</p>}
                    </article>

                    {!account.strategy_id ? <EmptyState title="请选择建议策略" detail="设置策略后，从下一个健康交易日开始确认候选。" /> : currentAdvice.isLoading ? <Loading /> : currentAdvice.error ? (
                        <article className="panel advice-unavailable"><AlertCircle size={20} /><div><strong>当前建议尚未生成</strong><span>{currentAdvice.error.message}</span></div></article>
                    ) : advice && (
                        <>
                            <section className="advice-summary">
                                <div><span>建议日期</span><strong>{advice.session_date}</strong></div>
                                <div><span>市场状态</span><strong>{marketStateText(advice.input_summary.market_state)}</strong></div>
                                <div><span>账户净值</span><strong>¥{Number(advice.input_summary.nav).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}</strong></div>
                                <div><span>建议策略</span><strong>{advice.strategy_name}</strong></div>
                            </section>
                            <article className="panel">
                                <div className="panel-heading"><div><p className="eyebrow">CURRENT</p><h2>当前持仓建议</h2></div><span className="muted-copy">刷新不会重新计算</span></div>
                                {advice.recommendations.length ? (
                                    <div className="table-wrap">
                                        <table className="advice-table">
                                            <thead><tr><th>ETF</th><th>状态</th><th>当前 / 计划份额</th><th>当前 / 目标权重</th><th>建议数量</th><th>理由</th><th>操作</th></tr></thead>
                                            <tbody>{advice.recommendations.map((item) => (
                                                <tr key={item.symbol}>
                                                    <td data-label="ETF"><strong>{item.symbol}</strong><span>{item.name}</span></td>
                                                    <td data-label="状态"><span className={`advice-tag advice-${item.action}`}>{ACTION_LABELS[item.action]}</span></td>
                                                    <td data-label="当前 / 计划">{item.current_shares.toLocaleString()} / {item.effective_shares.toLocaleString()}</td>
                                                    <td data-label="当前 / 目标">{percent(item.current_weight)} / {percent(item.target_weight)}</td>
                                                    <td data-label="建议数量">{item.quantity ? `${item.quantity.toLocaleString()} 份` : '—'}<span>{item.valid_on} 开盘</span></td>
                                                    <td data-label="理由" className="reason-cell">{item.reason}</td>
                                                    <td data-label="操作">{item.actionable && !advice.stale && <button className="text-button" onClick={() => navigate(`/trading?symbol=${item.symbol}&side=${item.action === 'buy' ? 'buy' : 'sell'}&shares=${item.quantity}`)}>采用建议 <ArrowRight size={13} /></button>}</td>
                                                </tr>
                                            ))}</tbody>
                                        </table>
                                    </div>
                                ) : <EmptyState title="暂无持仓调整" detail="当前策略没有形成可展示的候选。" />}
                            </article>
                        </>
                    )}

                    <article className="panel">
                        <div className="panel-heading"><div><p className="eyebrow">HISTORY</p><h2>建议历史</h2></div><Clock3 size={19} /></div>
                        {adviceHistory.data?.results.length ? <div className="table-wrap"><table><thead><tr><th>日期</th><th>策略</th><th>风险档位</th><th>目标数量</th><th>有效至</th></tr></thead><tbody>{adviceHistory.data.results.map((item) => <tr key={item.id}><td>{item.session_date}</td><td>{item.strategy_name}</td><td>{riskText(item.risk_level)}</td><td>{Object.keys(item.target_weights).length} 只</td><td>{item.expires_on}</td></tr>)}</tbody></table></div> : <EmptyState title="暂无历史建议" detail="健康行情完成处理后生成第一份建议。" />}
                    </article>
                    <div className="data-footnote">建议使用收盘后日线生成，不会自动创建订单或成交</div>
                </>
            )}
        </div>
    )
}

function percent(value: string): string {
    return `${(Number(value) * 100).toFixed(1)}%`
}

function marketStateText(value: string): string {
    return { strong: '强', neutral: '中性', weak: '弱' }[value] || value
}

function riskText(value: string): string {
    return { conservative: '保守', balanced: '均衡', aggressive: '进取' }[value] || value
}
