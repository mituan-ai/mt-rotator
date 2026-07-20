import { lazy, Suspense } from 'react'
import { Navigate, Outlet, Route, Routes } from 'react-router-dom'

import { useAuth } from './auth/AuthProvider'
import { Loading } from './components/Loading'
import { AppLayout } from './layout/AppLayout'
import { LoginPage } from './pages/LoginPage'
import { RegisterPage } from './pages/RegisterPage'

const AdminPage = lazy(() => import('./pages/AdminPage').then((module) => ({ default: module.AdminPage })))
const BacktestsPage = lazy(() => import('./pages/BacktestsPage').then((module) => ({ default: module.BacktestsPage })))
const DashboardPage = lazy(() => import('./pages/DashboardPage').then((module) => ({ default: module.DashboardPage })))
const SimulationPage = lazy(() => import('./pages/SimulationPage').then((module) => ({ default: module.SimulationPage })))
const StrategiesPage = lazy(() => import('./pages/StrategiesPage').then((module) => ({ default: module.StrategiesPage })))

function ProtectedRoute() {
    const { user, loading } = useAuth()
    if (loading) return <Loading />
    return user ? <Outlet /> : <Navigate to="/login" replace />
}

function AdminRoute() {
    const { user } = useAuth()
    return user?.is_staff ? <AdminPage /> : <Navigate to="/" replace />
}

export default function App() {
    return (
        <Suspense fallback={<Loading />}>
            <Routes>
                <Route path="/login" element={<LoginPage />} />
                <Route path="/register" element={<RegisterPage />} />
                <Route element={<ProtectedRoute />}>
                    <Route element={<AppLayout />}>
                        <Route index element={<DashboardPage />} />
                        <Route path="strategies" element={<StrategiesPage />} />
                        <Route path="backtests" element={<BacktestsPage />} />
                        <Route path="simulation" element={<SimulationPage />} />
                        <Route path="admin" element={<AdminRoute />} />
                    </Route>
                </Route>
                <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
        </Suspense>
    )
}
