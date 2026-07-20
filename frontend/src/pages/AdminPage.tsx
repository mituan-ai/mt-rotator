import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Clipboard, Database, RefreshCw, ShieldCheck, Upload, UserPlus, Wrench } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { api } from '../api/client'
import type { Instrument, MarketStatus, Page, Strategy, User } from '../api/types'
import { useAuth } from '../auth/AuthProvider'
import { EmptyState } from '../components/EmptyState'
import { StatusBadge } from '../components/StatusBadge'

interface Invitation {
    id: string
    email: string
    note: string
    expires_at: string
    state: 'active' | 'used' | 'expired' | 'revoked'
    created_at: string
    link?: string
}

interface AuditEvent {
    id: string
    actor_email: string | null
    event_type: string
    target_type: string
    target_id: string
    created_at: string
}

interface MarketBatch {
    id: string
    status: 'running' | 'healthy' | 'degraded' | 'failed'
    expected_session: string | null
    errors: Array<Record<string, unknown>>
    warnings: Array<Record<string, unknown>>
    started_at: string
    finished_at: string | null
    triggered_by: string
}

interface PaperCycle {
    id: string
    session_date: string
    status: 'pending' | 'running' | 'succeeded' | 'failed'
    attempt_count: number
    started_at: string | null
    finished_at: string | null
    error: string
}

export function AdminPage() {
    const queryClient = useQueryClient()
    const { user: currentUser } = useAuth()
    const [email, setEmail] = useState('')
    const [note, setNote] = useState('')
    const [newLink, setNewLink] = useState('')
    const [uploadError, setUploadError] = useState('')
    const [instrumentSymbol, setInstrumentSymbol] = useState('510300')
    const [splitDate, setSplitDate] = useState('')
    const [splitFactor, setSplitFactor] = useState('')
    const invitations = useQuery({ queryKey: ['admin-invitations'], queryFn: () => api.get<Page<Invitation>>('/auth/admin/invitations?page_size=100') })
    const users = useQuery({ queryKey: ['admin-users'], queryFn: () => api.get<Page<User>>('/auth/admin/users?page_size=100') })
    const market = useQuery({ queryKey: ['market-status'], queryFn: () => api.get<MarketStatus>('/market/status') })
    const batches = useQuery({ queryKey: ['admin-batches'], queryFn: () => api.get<Page<MarketBatch>>('/market/admin/batches?page_size=25') })
    const cycles = useQuery({ queryKey: ['admin-paper-cycles'], queryFn: () => api.get<Page<PaperCycle>>('/paper/admin/cycles?page_size=25') })
    const strategies = useQuery({ queryKey: ['admin-strategies'], queryFn: () => api.get<Page<Strategy>>('/strategies/admin?page_size=100') })
    const audit = useQuery({ queryKey: ['admin-audit'], queryFn: () => api.get<Page<AuditEvent>>('/admin/audit?page_size=50') })
    const instrument = useQuery({
        queryKey: ['admin-instrument', instrumentSymbol],
        queryFn: () => api.get<Instrument>(`/market/instruments/${instrumentSymbol}`),
        enabled: /^\d{6}$/.test(instrumentSymbol)
    })
    const createInvite = useMutation({
        mutationFn: () => api.post<Invitation>('/auth/admin/invitations', { email, note, days: 7 }),
        onSuccess: async (result) => {
            setNewLink(result.link || '')
            setEmail('')
            setNote('')
            await queryClient.invalidateQueries({ queryKey: ['admin-invitations'] })
        }
    })
    const revokeInvite = useMutation({
        mutationFn: (id: string) => api.post(`/auth/admin/invitations/${id}/revoke`),
        onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['admin-invitations'] })
    })
    const reissueInvite = useMutation({
        mutationFn: (id: string) => api.post<Invitation>(`/auth/admin/invitations/${id}/reissue`),
        onSuccess: async (result) => {
            setNewLink(result.link || '')
            await queryClient.invalidateQueries({ queryKey: ['admin-invitations'] })
        }
    })
    const updateUser = useMutation({
        mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) => api.patch(`/auth/admin/users/${id}`, { is_active }),
        onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['admin-users'] })
    })
    const revokeSessions = useMutation({
        mutationFn: (id: string) => api.post(`/auth/admin/users/${id}/sessions/revoke`)
    })
    const updateStrategy = useMutation({
        mutationFn: ({ id, active }: { id: string; active: boolean }) => api.patch(`/strategies/admin/${id}`, { active }),
        onSuccess: async () => Promise.all([
            queryClient.invalidateQueries({ queryKey: ['admin-strategies'] }),
            queryClient.invalidateQueries({ queryKey: ['strategies'] })
        ])
    })
    const generateSignal = useMutation({
        mutationFn: (slug: string) => api.post(`/strategies/${slug}/signals/generate`),
        onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['admin-strategies'] })
    })
    const updateData = useMutation({
        mutationFn: (fullRefresh: boolean) => api.post('/market/admin/batches', { full_refresh: fullRefresh }),
        onSuccess: async () => Promise.all([
            queryClient.invalidateQueries({ queryKey: ['market-status'] }),
            queryClient.invalidateQueries({ queryKey: ['admin-batches'] })
        ])
    })
    const reconcilePaper = useMutation({
        mutationFn: () => api.post('/paper/admin/reconcile'),
        onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['admin-paper-cycles'] })
    })
    const repairInstrument = useMutation({
        mutationFn: () => api.post(`/market/admin/instruments/${instrumentSymbol}/repair`),
        onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['market-status'] })
    })
    const updateInstrument = useMutation({
        mutationFn: (payload: { enabled?: boolean; settlement_cycle?: 't0' | 't1' }) => api.patch<Instrument>(`/market/admin/instruments/${instrumentSymbol}`, payload),
        onSuccess: async () => Promise.all([
            queryClient.invalidateQueries({ queryKey: ['admin-instrument', instrumentSymbol] }),
            queryClient.invalidateQueries({ queryKey: ['market-status'] }),
            queryClient.invalidateQueries({ queryKey: ['instruments'] })
        ])
    })
    const recordSplit = useMutation({
        mutationFn: () => api.post(`/market/admin/instruments/${instrumentSymbol}/actions`, {
            kind: 'split',
            effective_date: splitDate,
            value: splitFactor
        }),
        onSuccess: async () => {
            setSplitDate('')
            setSplitFactor('')
            await Promise.all([
                queryClient.invalidateQueries({ queryKey: ['admin-instrument', instrumentSymbol] }),
                queryClient.invalidateQueries({ queryKey: ['market-status'] })
            ])
        }
    })

    function submit(event: FormEvent) {
        event.preventDefault()
        createInvite.mutate()
    }

    async function uploadCsv(file?: File) {
        if (!file) return
        setUploadError('')
        const form = new FormData()
        form.set('file', file)
        try {
            const result = await api.upload<{ created: Invitation[]; errors: Array<{ row: number; error: string }> }>('/auth/admin/invitations/import', form)
            setNewLink(result.created[0]?.link || '')
            if (result.errors.length) setUploadError(`${result.errors.length} 行未导入，请检查邮箱或重复邀请。`)
            await invitations.refetch()
        } catch (reason) {
            setUploadError(reason instanceof Error ? reason.message : 'CSV 导入失败')
        }
    }

    const actionError = [revokeInvite.error, reissueInvite.error, updateUser.error, revokeSessions.error, updateStrategy.error, generateSignal.error, updateData.error, reconcilePaper.error, repairInstrument.error, updateInstrument.error, recordSplit.error].find(Boolean)

    return (
        <div className="page-stack">
            <header className="page-header"><div><p className="eyebrow">ADMINISTRATION</p><h1>管理</h1><p>邀请、用户、ETF数据、策略和审计。</p></div><StatusBadge ok={Boolean(market.data?.ready)}>{market.data?.ready ? '建议数据正常' : '新建议暂停'}</StatusBadge></header>
            {(actionError || uploadError) && <p className="form-error">{actionError instanceof Error ? actionError.message : uploadError}</p>}
            <section className="section-grid two-columns">
                <form className="panel" onSubmit={submit}><div className="panel-heading"><div><p className="eyebrow">INVITATION</p><h2>创建邀请</h2></div><UserPlus size={19} /></div><label>邮箱<input type="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label><label>备注<input maxLength={240} value={note} onChange={(event) => setNote(event.target.value)} /></label>{createInvite.error && <p className="form-error">{createInvite.error.message}</p>}<button className="primary-button" disabled={createInvite.isPending}>生成一次性链接</button><label className="upload-button"><Upload size={16} /> 导入CSV<input type="file" accept=".csv,text/csv" onChange={(event) => uploadCsv(event.target.files?.[0])} /></label>{newLink && <div className="invite-link"><code>{newLink}</code><button type="button" className="icon-button" onClick={() => navigator.clipboard.writeText(newLink)} aria-label="复制邀请链接"><Clipboard size={16} /></button></div>}</form>
                <article className="panel"><div className="panel-heading"><div><p className="eyebrow">DATA PIPELINE</p><h2>数据状态</h2></div><Database size={19} /></div><div className="data-admin-status"><StatusBadge ok={Boolean(market.data?.ready)}>{market.data?.ready ? '允许生成新建议' : '暂停生成新建议'}</StatusBadge><strong>预期交易日 {market.data?.expected_session || '—'}</strong><span>{market.data?.source}</span><div className="admin-counts"><span>目录 {market.data?.counts.catalog || 0}</span><span>可交易 {market.data?.counts.trade_eligible || 0}</span><span>可建议 {market.data?.counts.advice_eligible || 0}</span><span>异常 {(market.data?.counts.stale || 0) + (market.data?.counts.missing || 0) + (market.data?.counts.blocked || 0)}</span></div><div className="table-actions"><button className="secondary-button" onClick={() => updateData.mutate(false)} disabled={updateData.isPending}>{updateData.isPending ? '已提交任务' : '立即更新'}</button><button className="secondary-button" onClick={() => updateData.mutate(true)} disabled={updateData.isPending}>回填24个月</button></div></div></article>
            </section>
            <article className="panel">
                <div className="panel-heading"><div><p className="eyebrow">ETF CONTROL</p><h2>单标的维护</h2></div><Wrench size={19} /></div>
                <div className="instrument-admin-grid">
                    <label>ETF代码<input inputMode="numeric" maxLength={6} value={instrumentSymbol} onChange={(event) => setInstrumentSymbol(event.target.value.replace(/\D/g, ''))} /></label>
                    <div className="instrument-admin-summary">{instrument.isLoading ? <span>正在查询</span> : instrument.error ? <span className="form-error">{instrument.error.message}</span> : instrument.data && <><strong>{instrument.data.symbol} {instrument.data.name}</strong><span>{instrument.data.data_status} · {instrument.data.last_bar_date || '无日线'} · {instrument.data.settlement_cycle === 't0' ? 'T+0' : 'T+1'}</span></>}</div>
                    <div className="table-actions"><button className="secondary-button" disabled={!instrument.data || repairInstrument.isPending} onClick={() => repairInstrument.mutate()}>修复行情</button><button className="secondary-button" disabled={!instrument.data || updateInstrument.isPending} onClick={() => updateInstrument.mutate({ settlement_cycle: instrument.data?.settlement_cycle === 't0' ? 't1' : 't0' })}>改为 {instrument.data?.settlement_cycle === 't0' ? 'T+1' : 'T+0'}</button><button className="secondary-button" disabled={!instrument.data || updateInstrument.isPending} onClick={() => updateInstrument.mutate({ enabled: !instrument.data?.enabled })}>{instrument.data?.enabled ? '暂停标的' : '恢复标的'}</button></div>
                    <div className="split-form"><label>拆分生效日<input type="date" value={splitDate} onChange={(event) => setSplitDate(event.target.value)} /></label><label>拆分比例<input inputMode="decimal" placeholder="例如 2" value={splitFactor} onChange={(event) => setSplitFactor(event.target.value)} /></label><button className="secondary-button" disabled={!instrument.data || !splitDate || !splitFactor || recordSplit.isPending} onClick={() => recordSplit.mutate()}>录入拆分</button></div>
                </div>
                {market.data?.instruments.length ? <div className="problem-instruments"><span>最近异常</span>{market.data.instruments.slice(0, 12).map((item) => <button key={item.symbol} onClick={() => setInstrumentSymbol(item.symbol)}>{item.symbol} · {item.state}</button>)}</div> : null}
            </article>
            <section className="section-grid two-columns">
                <article className="panel"><div className="panel-heading"><div><p className="eyebrow">INVITATIONS</p><h2>邀请记录</h2></div></div>{invitations.data?.results.length ? <div className="table-wrap"><table><thead><tr><th>邮箱</th><th>状态</th><th>过期</th><th>操作</th></tr></thead><tbody>{invitations.data.results.map((item) => <tr key={item.id}><td>{item.email}<span>{item.note}</span></td><td>{item.state}</td><td>{item.expires_at.slice(0, 10)}</td><td><div className="table-actions">{item.state === 'active' && <button className="text-button" onClick={() => revokeInvite.mutate(item.id)}>撤销</button>}{item.state !== 'used' && <button className="text-button" onClick={() => reissueInvite.mutate(item.id)}>重新签发</button>}</div></td></tr>)}</tbody></table></div> : <EmptyState title="暂无邀请" detail="创建链接后只展示一次明文令牌。" />}</article>
                <article className="panel"><div className="panel-heading"><div><p className="eyebrow">USERS</p><h2>用户</h2></div><ShieldCheck size={19} /></div><div className="table-wrap"><table><thead><tr><th>用户</th><th>角色</th><th>状态</th><th>操作</th></tr></thead><tbody>{users.data?.results.map((user) => <tr key={user.id}><td>{user.display_name}<span>{user.email}</span></td><td>{user.is_staff ? '管理员' : '用户'}</td><td>{user.is_active ? '正常' : '停用'}</td><td><div className="table-actions"><button className="text-button" disabled={user.id === currentUser?.id} onClick={() => updateUser.mutate({ id: user.id, is_active: !user.is_active })}>{user.is_active ? '停用' : '恢复'}</button><button className="text-button" onClick={() => revokeSessions.mutate(user.id)}>撤销会话</button></div></td></tr>)}</tbody></table></div></article>
            </section>
            <section className="section-grid two-columns">
                <article className="panel"><div className="panel-heading"><div><p className="eyebrow">STRATEGIES</p><h2>策略状态</h2></div></div><div className="table-wrap"><table><thead><tr><th>策略</th><th>版本</th><th>状态</th><th>操作</th></tr></thead><tbody>{strategies.data?.results.map((strategy) => <tr key={strategy.id}><td>{strategy.name}</td><td>{strategy.version}</td><td>{strategy.active ? '启用' : '停用'}</td><td><div className="table-actions"><button className="text-button" onClick={() => updateStrategy.mutate({ id: strategy.id, active: !strategy.active })}>{strategy.active ? '停用' : '启用'}</button>{strategy.active && <button className="text-button" onClick={() => generateSignal.mutate(strategy.slug)}>生成最新信号</button>}</div></td></tr>)}</tbody></table></div></article>
                <article className="panel"><div className="panel-heading"><div><p className="eyebrow">DATA JOBS</p><h2>最近批次</h2></div><button className="icon-button" onClick={() => batches.refetch()} aria-label="刷新批次"><RefreshCw size={16} /></button></div>{batches.data?.results.length ? <div className="table-wrap"><table><thead><tr><th>开始</th><th>交易日</th><th>状态</th><th>问题</th></tr></thead><tbody>{batches.data.results.map((batch) => <tr key={batch.id}><td>{new Date(batch.started_at).toLocaleString('zh-CN')}</td><td>{batch.expected_session || '—'}</td><td>{batch.status}</td><td>{batch.errors.length ? `${batch.errors.length} 个错误` : batch.warnings.length ? `${batch.warnings.length} 个警告` : '—'}{batch.errors[0] && <span>{String(batch.errors[0].message || batch.errors[0].source || '')}</span>}</td></tr>)}</tbody></table></div> : <EmptyState title="暂无数据批次" detail="首次任务完成后显示状态。" />}</article>
            </section>
            <article className="panel"><div className="panel-heading"><div><p className="eyebrow">PAPER CYCLES</p><h2>模拟周期</h2></div><div className="table-actions"><button className="secondary-button" onClick={() => reconcilePaper.mutate()} disabled={reconcilePaper.isPending}>{reconcilePaper.isPending ? '已提交' : '补偿处理'}</button><button className="icon-button" onClick={() => cycles.refetch()} aria-label="刷新模拟周期"><RefreshCw size={16} /></button></div></div>{cycles.data?.results.length ? <div className="table-wrap"><table><thead><tr><th>交易日</th><th>状态</th><th>尝试</th><th>完成时间</th><th>问题</th></tr></thead><tbody>{cycles.data.results.map((cycle) => <tr key={cycle.id}><td>{cycle.session_date}</td><td>{cycle.status}</td><td>{cycle.attempt_count}</td><td>{cycle.finished_at ? new Date(cycle.finished_at).toLocaleString('zh-CN') : '—'}</td><td>{cycle.error || '—'}</td></tr>)}</tbody></table></div> : <EmptyState title="暂无模拟周期" detail="行情就绪后自动按交易日处理。" />}</article>
            <article className="panel"><div className="panel-heading"><div><p className="eyebrow">AUDIT</p><h2>审计日志</h2></div></div><div className="audit-list">{audit.data?.results.map((item) => <div key={item.id}><code>{item.event_type}</code><span>{item.actor_email || 'system'}</span><time>{new Date(item.created_at).toLocaleString('zh-CN')}</time></div>)}</div></article>
        </div>
    )
}
