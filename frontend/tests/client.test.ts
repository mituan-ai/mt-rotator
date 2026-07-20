import { describe, expect, it, vi } from 'vitest'

import { api, ApiError } from '../src/api/client'

function response(body: unknown, status = 200): Response {
    return new Response(body === undefined ? null : JSON.stringify(body), {
        status,
        headers: body === undefined ? undefined : { 'Content-Type': 'application/json' }
    })
}

describe('API client', () => {
    it('sends session credentials and the CSRF token for mutations', async () => {
        document.cookie = 'csrftoken=test-csrf-token; Path=/'
        const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response({ ok: true }))

        await api.post('/auth/login', { email: 'user@example.com', password: 'password' })

        const [url, init] = fetchMock.mock.calls[0]
        expect(url).toBe('/api/v1/auth/login')
        expect(init?.credentials).toBe('include')
        expect(init?.method).toBe('POST')
        expect(new Headers(init?.headers).get('X-CSRFToken')).toBe('test-csrf-token')
    })

    it('maps Problem Details responses to a stable ApiError', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(
            response({ title: '请求受限', detail: '请稍后重试', code: 'login_throttled' }, 429)
        )

        await expect(api.post('/auth/login', {})).rejects.toMatchObject({
            status: 429,
            code: 'login_throttled',
            message: '请稍后重试'
        } satisfies Partial<ApiError>)
    })
})
