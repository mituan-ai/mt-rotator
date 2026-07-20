import { BarChart3, Database, FlaskConical, LayoutDashboard, LogOut, Moon, Shield, Sun, WalletCards } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthProvider'
import { PasswordDialog } from '../components/PasswordDialog'

const navigation = [
    { to: '/', label: '总览', icon: LayoutDashboard },
    { to: '/strategies', label: '策略', icon: BarChart3 },
    { to: '/backtests', label: '回测', icon: FlaskConical },
    { to: '/simulation', label: '模拟', icon: WalletCards }
]

export function AppLayout() {
    const { user, logout } = useAuth()
    const navigate = useNavigate()
    const [dark, setDark] = useState(() => localStorage.getItem('mt-theme') === 'dark')

    useEffect(() => {
        document.documentElement.dataset.theme = dark ? 'dark' : 'light'
        localStorage.setItem('mt-theme', dark ? 'dark' : 'light')
    }, [dark])

    return (
        <div className="app-shell">
            <aside className="sidebar">
                <div className="brand-mark">
                    <span>MT</span>
                    <strong>MT轮动</strong>
                </div>
                <nav>
                    {navigation.map((item) => (
                        <NavLink key={item.to} to={item.to} end={item.to === '/'}>
                            <item.icon size={18} />
                            {item.label}
                        </NavLink>
                    ))}
                    {user?.is_staff && (
                        <NavLink to="/admin">
                            <Shield size={18} />
                            管理
                        </NavLink>
                    )}
                </nav>
                <div className="sidebar-footer">
                    <button className="icon-button" onClick={() => setDark((value) => !value)} aria-label="切换主题">
                        {dark ? <Sun size={17} /> : <Moon size={17} />}
                    </button>
                    {user && <div className="user-block"><strong>{user.display_name}</strong><span>{user.email}</span></div>}
                    {user && <PasswordDialog />}
                    <button
                        className="icon-button"
                        aria-label="退出登录"
                        onClick={async () => {
                            await logout()
                            navigate('/login')
                        }}
                    >
                        <LogOut size={17} />
                    </button>
                </div>
            </aside>
            <main className="app-main">
                <Outlet />
                <footer>
                    <Database size={14} /> 仅用于真实历史数据上的模拟研究，不构成投资建议
                </footer>
            </main>
        </div>
    )
}
