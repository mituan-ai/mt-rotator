import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, Check, Clock3, Layers3 } from 'lucide-react'

import { api } from '../api/client'
import type { Page, PaperAccount, Strategy } from '../api/types'
import { EmptyState } from '../components/EmptyState'
import { Loading } from '../components/Loading'
import { StatusBadge } from '../components/StatusBadge'

export function StrategiesPage() {
    const queryClient = useQueryClient()
    const strategies = useQuery({ queryKey: ['strategies'], queryFn: () => api.get<Page<Strategy>>('/strategies/') })
    const accounts = useQuery({ queryKey: ['paper-accounts'], queryFn: () => api.get<Page<PaperAccount>>('/paper/accounts') })
    const activateAccount = useMutation({
        mutationFn: (strategy: Strategy) => api.post('/paper/accounts', { strategy_version_id: strategy.id }),
        onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['paper-accounts'] })
    })
    if (strategies.isLoading || accounts.isLoading) return <Loading />

    return (
        <div className="page-stack">
            <header className="page-header"><div><p className="eyebrow">STRATEGIES</p><h1>策略</h1><p>固定版本、透明规则、统一成交假设。</p></div></header>
            <section className="strategy-grid">
                {strategies.data?.results.map((strategy, index) => {
                    const active = accounts.data?.results.some((item) => item.strategy_id === strategy.id && item.status === 'active')
                    return <StrategyCard key={strategy.id} strategy={strategy} index={index + 1} active={Boolean(active)} activating={activateAccount.isPending && activateAccount.variables?.id === strategy.id} onActivate={() => activateAccount.mutate(strategy)} />
                })}
            </section>
            {activateAccount.error && <p className="form-error">{activateAccount.error.message}</p>}
            <div className="data-footnote">东方财富日线 · 后复权信号 / 原始价成交 · 新浪交叉校验</div>
        </div>
    )
}

function StrategyCard({ strategy, index, active, activating, onActivate }: { strategy: Strategy; index: number; active: boolean; activating: boolean; onActivate: () => void }) {
    const signal = strategy.latest_signal
    return (
        <article className="strategy-card">
            <div className="strategy-index">0{index}</div>
            <div className="strategy-title"><div><h2>{strategy.name}</h2><span>v{strategy.version}</span></div><StatusBadge ok={Boolean(signal)}>{signal ? '信号有效' : '等待数据'}</StatusBadge></div>
            <p>{strategy.description}</p>
            <div className="strategy-facts">
                <div><Layers3 size={16} /><span>风险资产</span><strong>{strategy.risk_symbols.length} 只</strong></div>
                <div><Clock3 size={16} /><span>调仓频率</span><strong>每月</strong></div>
                <div><Activity size={16} /><span>最早成交</span><strong>次日开盘</strong></div>
            </div>
            {signal ? (
                <div className="allocation-list">
                    <div className="subheading">当前目标权重 · {signal.signal_date}</div>
                    {Object.entries(signal.target_weights).map(([symbol, weight]) => (
                        <div className="allocation-row" key={symbol}><span>{symbol}</span><div><i style={{ width: `${weight * 100}%` }} /></div><strong>{(weight * 100).toFixed(1)}%</strong></div>
                    ))}
                </div>
            ) : <EmptyState title="尚无信号" detail="行情完整并到达月末后自动生成。" />}
            <button className={active ? 'secondary-button' : 'primary-button'} disabled={active || activating} onClick={onActivate}>{active ? <><Check size={16} /> 已激活</> : activating ? '正在激活' : '激活模拟账户'}</button>
        </article>
    )
}
