import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import { api } from '../api/client'
import type { User } from '../api/types'
import { useAuth } from '../auth/AuthProvider'

export function LoginPage() {
    const { user, refresh } = useAuth()
    const navigate = useNavigate()
    const [email, setEmail] = useState('')
    const [password, setPassword] = useState('')
    const [error, setError] = useState('')
    const [submitting, setSubmitting] = useState(false)
    if (user) return <Navigate to="/" replace />

    async function submit(event: FormEvent) {
        event.preventDefault()
        setError('')
        setSubmitting(true)
        try {
            await api.post<User>('/auth/login', { email, password })
            await refresh()
            navigate('/')
        } catch (reason) {
            setError(reason instanceof Error ? reason.message : '登录失败')
        } finally {
            setSubmitting(false)
        }
    }

    return (
        <div className="auth-page">
            <div className="auth-brand"><span>MT</span><strong>MT轮动</strong></div>
            <form className="auth-card" onSubmit={submit}>
                <div><p className="eyebrow">WELCOME BACK</p><h1>登录</h1></div>
                <label>邮箱<input type="email" required autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label>
                <label>密码<input type="password" required autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
                {error && <p className="form-error">{error}</p>}
                <button className="primary-button" disabled={submitting}>{submitting ? '正在登录' : '登录'}</button>
                <p className="form-hint">持有邀请链接？<Link to="/register">完成注册</Link></p>
            </form>
        </div>
    )
}
