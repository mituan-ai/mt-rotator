import { useQuery } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, Minus, Trophy } from 'lucide-react'
import { useState } from 'react'

import { api } from '../api/client'
import type { LeaderboardPage } from '../api/types'
import { useAuth } from '../auth/AuthProvider'
import { EmptyState } from '../components/EmptyState'
import { Loading } from '../components/Loading'

const PERIODS = [
    ['mtd', '本月'],
    ['3m', '近3月'],
    ['1y', '近1年'],
    ['all', '成立以来']
] as const

export function LeaderboardPage() {
    const { user } = useAuth()
    const [period, setPeriod] = useState('mtd')
    const leaderboard = useQuery({
        queryKey: ['leaderboard', period],
        queryFn: () => api.get<LeaderboardPage>(`/paper/leaderboard?period=${period}&page_size=100`)
    })

    if (leaderboard.isLoading) return <Loading />

    return (
        <div className="page-stack">
            <header className="page-header">
                <div><p className="eyebrow">LEADERBOARD</p><h1>排行</h1><p>所有自主账户公开昵称参与展示。</p></div>
                <div className="period-control">{PERIODS.map(([value, label]) => <button key={value} className={period === value ? 'selected' : ''} onClick={() => setPeriod(value)}>{label}</button>)}</div>
            </header>
            {leaderboard.error && <p className="form-error">{leaderboard.error.message}</p>}
            <article className="panel leaderboard-panel">
                <div className="panel-heading"><div><p className="eyebrow">RANKING</p><h2>{PERIODS.find(([value]) => value === period)?.[1]}</h2></div><div className="ranking-date"><Trophy size={17} /><span>共同截止 {leaderboard.data?.as_of_date || '—'}</span></div></div>
                {leaderboard.data?.results.length ? (
                    <div className="table-wrap">
                        <table className="leaderboard-table">
                            <thead><tr><th>排名</th><th>用户</th><th>收益率</th><th>最大回撤</th><th>当前净值</th><th>账户年龄</th><th>变化</th></tr></thead>
                            <tbody>{leaderboard.data.results.map((row) => (
                                <tr key={row.account_number} className={row.display_name === user?.display_name ? 'current-user-row' : ''}>
                                    <td><span className={`rank-number rank-${row.rank || 'unranked'}`}>{row.rank || '—'}</span></td>
                                    <td><strong>{row.display_name}</strong><span>#{row.account_number}</span></td>
                                    <td className={Number(row.return) >= 0 ? 'number-up' : 'number-down'}><strong>{formatPercent(row.return)}</strong></td>
                                    <td className="number-down">{formatPercent(row.max_drawdown)}</td>
                                    <td>¥{Number(row.current_nav).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                                    <td>{row.account_age_sessions} 日{!row.eligible && <span>{row.eligibility_reason}</span>}</td>
                                    <td><RankChange value={row.rank_change} eligible={row.eligible} /></td>
                                </tr>
                            ))}</tbody>
                        </table>
                    </div>
                ) : <EmptyState title="暂无排行数据" detail="自主账户生成净值后会在此公开展示。" />}
            </article>
            <div className="data-footnote">不足20个交易日的账户仍展示但不参与正式排名；不公开邮箱和持仓</div>
        </div>
    )
}

function RankChange({ value, eligible }: { value: number | null; eligible: boolean }) {
    if (!eligible) return <span className="rank-change flat"><Minus size={13} /> 未入榜</span>
    if (!value) return <span className="rank-change flat"><Minus size={13} /> 0</span>
    return value > 0
        ? <span className="rank-change up"><ArrowUp size={13} /> {value}</span>
        : <span className="rank-change down"><ArrowDown size={13} /> {Math.abs(value)}</span>
}

function formatPercent(value: string): string {
    return `${(Number(value) * 100).toFixed(2)}%`
}
