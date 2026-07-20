import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, FlaskConical, RefreshCw, X } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'

import { api } from '../api/client'
import type { BacktestRun, Page, Strategy } from '../api/types'
import { Chart } from '../components/Chart'
import { EmptyState } from '../components/EmptyState'
import { Loading } from '../components/Loading'
import { Metric } from '../components/Metric'
import { StatusBadge } from '../components/StatusBadge'

const COLORS = ['#315efb', '#d64545', '#11835c', '#8b5cf6']
const TODAY = new Date().toISOString().slice(0, 10)
const ONE_YEAR_AGO = (() => {
    const value = new Date()
    value.setFullYear(value.getFullYear() - 1)
    return value.toISOString().slice(0, 10)
})()

export function BacktestsPage() {
    const queryClient = useQueryClient()
    const strategies = useQuery({
        queryKey: ['strategies'],
        queryFn: () => api.get<Page<Strategy>>('/strategies/')
    })
    const runs = useQuery({
        queryKey: ['backtests'],
        queryFn: () => api.get<Page<BacktestRun>>('/backtests/?page_size=100'),
        refetchInterval: (query) => query.state.data?.results.some((item) => ['queued', 'running'].includes(item.status)) ? 3000 : false
    })
    const [strategyId, setStrategyId] = useState('')
    const [startDate, setStartDate] = useState(ONE_YEAR_AGO)
    const [endDate, setEndDate] = useState(TODAY)
    const [selectedIds, setSelectedIds] = useState<string[]>([])
    const [selectionError, setSelectionError] = useState('')
    const details = useQueries({
        queries: selectedIds.map((id) => ({
            queryKey: ['backtest', id],
            queryFn: () => api.get<BacktestRun>(`/backtests/${id}`),
            refetchInterval: (query: { state: { data?: BacktestRun } }) => ['queued', 'running'].includes(query.state.data?.status || '') ? 2000 : false
        }))
    })
    const create = useMutation({
        mutationFn: () => api.post<{ id: string }>('/backtests/', {
            strategy_version_id: strategyId,
            start_date: startDate,
            end_date: endDate
        }),
        onSuccess: async (result) => {
            setSelectedIds([result.id])
            await queryClient.invalidateQueries({ queryKey: ['backtests'] })
        }
    })
    const cancel = useMutation({
        mutationFn: (id: string) => api.post(`/backtests/${id}/cancel`),
        onSuccess: async (_, id) => {
            await Promise.all([
                queryClient.invalidateQueries({ queryKey: ['backtests'] }),
                queryClient.invalidateQueries({ queryKey: ['backtest', id] })
            ])
        }
    })

    function submit(event: FormEvent) {
        event.preventDefault()
        if (strategyId) create.mutate()
    }

    function toggleRun(id: string) {
        setSelectionError('')
        setSelectedIds((current) => {
            if (current.includes(id)) return current.filter((item) => item !== id)
            if (current.length >= 4) {
                setSelectionError('最多同时比较 4 个回测结果')
                return current
            }
            return [...current, id]
        })
    }

    if (strategies.isLoading || runs.isLoading) return <Loading />
    const selectedRuns = details.flatMap((query) => query.data ? [query.data] : [])

    return (
        <div className="page-stack">
            <header className="page-header"><div><p className="eyebrow">RESEARCH</p><h1>回测</h1><p>从空仓开始自动采纳全部建议，用于评估建议政策。</p></div></header>
            <section className="backtest-layout">
                <form className="panel backtest-form" onSubmit={submit}>
                    <div className="panel-heading"><div><p className="eyebrow">NEW RUN</p><h2>新建回测</h2></div><FlaskConical size={20} /></div>
                    <label>策略<select required value={strategyId} onChange={(event) => setStrategyId(event.target.value)}><option value="">选择策略</option>{strategies.data?.results.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
                    <div className="form-row"><label>开始日期<input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label><label>结束日期<input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label></div>
                    <div className="assumption-box"><span>均衡风险档位</span><span>初始资金 ¥100,000</span><span>佣金 万3 / 最低¥5</span><span>滑点 5 bps</span><span>次日开盘估算成交</span></div>
                    {create.error && <p className="form-error">{create.error.message}</p>}
                    <button className="primary-button" disabled={create.isPending || !strategyId}>{create.isPending ? '正在创建' : '开始回测'}</button>
                </form>
                <article className="panel run-list">
                    <div className="panel-heading"><div><p className="eyebrow">HISTORY</p><h2>回测记录 · 已选 {selectedIds.length}/4</h2></div><button className="icon-button" onClick={() => runs.refetch()} aria-label="刷新回测"><RefreshCw size={16} /></button></div>
                    {selectionError && <p className="form-error">{selectionError}</p>}
                    {!runs.data?.results.length ? <EmptyState title="暂无回测" detail="选择策略和日期后创建第一条记录。" /> : runs.data.results.map((run) => (
                        <button className={`run-row ${selectedIds.includes(run.id) ? 'selected' : ''}`} key={run.id} onClick={() => toggleRun(run.id)}><div><strong>{run.strategy_name}</strong><span>{run.start_date} — {run.end_date}</span></div><StatusBadge ok={run.status === 'succeeded'}>{statusText(run.status)}</StatusBadge></button>
                    ))}
                </article>
            </section>
            {selectedIds.length > 0 && <BacktestComparison runs={selectedRuns} loading={details.some((query) => query.isLoading)} onRemove={toggleRun} onCancel={(id) => cancel.mutate(id)} />}
        </div>
    )
}

function BacktestComparison({ runs, loading, onRemove, onCancel }: { runs: BacktestRun[]; loading: boolean; onRemove: (id: string) => void; onCancel: (id: string) => void }) {
    const succeeded = runs.filter((run) => run.status === 'succeeded' && run.result)
    const option = useMemo(() => ({
        animation: false,
        grid: { left: 48, right: 18, top: 42, bottom: 36 },
        tooltip: { trigger: 'axis' },
        legend: { top: 0 },
        xAxis: { type: 'time', axisLabel: { hideOverlap: true } },
        yAxis: { type: 'value', scale: true },
        series: succeeded.map((run, index) => ({
            name: `${run.strategy_name} · ${run.end_date}`,
            type: 'line',
            data: run.result?.nav.map((item) => [item.date, item.value]) || [],
            showSymbol: false,
            lineStyle: { color: COLORS[index], width: 2 }
        }))
    }), [succeeded])
    if (loading && !runs.length) return <Loading />
    return (
        <article className="panel result-panel">
            <div className="panel-heading"><div><p className="eyebrow">COMPARISON</p><h2>结果对比</h2></div></div>
            <div className="comparison-grid">
                {runs.map((run, index) => {
                    const metrics = run.result?.metrics || {}
                    const total = Number(metrics.total_return || 0)
                    return (
                        <div className="comparison-card" key={run.id} style={{ borderTopColor: COLORS[index] }}>
                            <div><strong>{run.strategy_name}</strong><button className="icon-button" onClick={() => onRemove(run.id)} aria-label="移出对比"><X size={14} /></button></div>
                            <StatusBadge ok={run.status === 'succeeded'}>{statusText(run.status)}</StatusBadge>
                            {run.status === 'succeeded' ? <div className="comparison-metrics"><Metric label="累计收益" value={`${(total * 100).toFixed(2)}%`} tone={total >= 0 ? 'up' : 'down'} /><Metric label="最大回撤" value={`${(Number(metrics.max_drawdown || 0) * 100).toFixed(2)}%`} tone="down" /><Metric label="Sharpe" value={Number(metrics.sharpe || 0).toFixed(2)} /></div> : <>{run.error && <p className="form-error">{run.error}</p>}{run.status === 'queued' && <button className="secondary-button" onClick={() => onCancel(run.id)}>取消排队</button>}</>}
                            {run.status === 'succeeded' && <a className="secondary-button" href={`/api/v1/backtests/${run.id}/export?format=csv`}><Download size={15} /> 导出</a>}
                        </div>
                    )
                })}
            </div>
            {succeeded.length > 0 && <Chart option={option} height={360} />}
            {succeeded[0] && <div className="data-footnote">数据截止 {succeeded[0].data_snapshot.cutoff_date} · {succeeded[0].data_snapshot.provider} · 分红总收益研究 / 原始价成交</div>}
        </article>
    )
}

function statusText(status: BacktestRun['status']): string {
    return { queued: '排队中', running: '运行中', succeeded: '已完成', failed: '失败', cancelled: '已取消' }[status]
}
