import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import App from '../src/App'
import { AuthProvider } from '../src/auth/AuthProvider'

function json(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/problem+json' }
    })
}

function renderApp(path: string) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
        <QueryClientProvider client={queryClient}>
            <MemoryRouter initialEntries={[path]}>
                <AuthProvider>
                    <App />
                </AuthProvider>
            </MemoryRouter>
        </QueryClientProvider>
    )
}

describe('authentication pages', () => {
    it('redirects anonymous users to the login page', async () => {
        vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
            const url = String(input)
            return url.endsWith('/auth/csrf') ? json({ detail: 'ok' }) : json({ detail: '未登录' }, 401)
        })

        renderApp('/')

        expect(await screen.findByRole('heading', { name: '登录' })).toBeInTheDocument()
    })

    it('validates the hash invitation without exposing it in the path', async () => {
        window.location.hash = '#token=one-time-token'
        const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
            const url = String(input)
            if (url.endsWith('/auth/invitations/inspect')) return json({ email: 'invitee@example.com' })
            if (url.endsWith('/auth/me')) return json({ detail: '未登录' }, 401)
            return json({ detail: 'ok' })
        })

        renderApp('/register')

        expect(await screen.findByDisplayValue('invitee@example.com')).toBeInTheDocument()
        expect(fetchMock.mock.calls.some(([url]) => String(url).includes('one-time-token'))).toBe(false)
    })

    it('shows a Problem Details login error', async () => {
        vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
            const url = String(input)
            if (url.endsWith('/auth/me')) return json({ detail: '未登录' }, 401)
            if (url.endsWith('/auth/login')) return json({ detail: '邮箱或密码错误', code: 'invalid_credentials' }, 400)
            return json({ detail: 'ok' })
        })

        renderApp('/login')
        fireEvent.change(await screen.findByLabelText('邮箱'), { target: { value: 'user@example.com' } })
        fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'incorrect-password' } })
        fireEvent.click(screen.getByRole('button', { name: '登录' }))

        await waitFor(() => expect(screen.getByText('邮箱或密码错误')).toBeInTheDocument())
    })
})
