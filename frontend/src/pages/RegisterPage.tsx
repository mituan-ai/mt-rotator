import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

function tokenFromHash(): string {
    return new URLSearchParams(window.location.hash.replace(/^#/, '')).get('token') || ''
}

export function RegisterPage() {
    const token = useMemo(tokenFromHash, [])
    const navigate = useNavigate()
    const { refresh } = useAuth()
    const [email, setEmail] = useState('')
    const [displayName, setDisplayName] = useState('')
    const [password, setPassword] = useState('')
    const [error, setError] = useState('')
    const [valid, setValid] = useState(false)

    useEffect(() => {
        if (!token) return
        api.post<{ email: string }>('/auth/invitations/inspect', { token })
            .then((result) => { setEmail(result.email); setValid(true) })
            .catch((reason) => setError(reason instanceof Error ? reason.message : '邀请无效'))
    }, [token])

    async function submit(event: FormEvent) {
        event.preventDefault()
        setError('')
        try {
            await api.post('/auth/register', { token, email, display_name: displayName, password })
            window.history.replaceState(null, '', '/register')
            await refresh()
            navigate('/')
        } catch (reason) {
            setError(reason instanceof Error ? reason.message : '注册失败')
        }
    }

    return (
        <div className="auth-page">
            <div className="auth-brand"><span>MT</span><strong>MT轮动</strong></div>
            <form className="auth-card" onSubmit={submit}>
                <div><p className="eyebrow">INVITATION ONLY</p><h1>创建账户</h1></div>
                {!token && <p className="form-error">请使用管理员提供的完整邀请链接。</p>}
                <label>邮箱<input type="email" value={email} readOnly /></label>
                <label>显示名称<input required minLength={2} maxLength={24} value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></label>
                <label>密码<input type="password" required minLength={12} autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
                {error && <p className="form-error">{error}</p>}
                <button className="primary-button" disabled={!valid}>注册</button>
                <p className="form-hint">已有账户？<Link to="/login">返回登录</Link></p>
            </form>
        </div>
    )
}
