import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
    await page.route('**/api/v1/auth/csrf', (route) => route.fulfill({ json: { detail: 'ok' } }))
    await page.route('**/api/v1/auth/me', (route) =>
        route.fulfill({ status: 401, contentType: 'application/problem+json', body: JSON.stringify({ detail: '未登录' }) })
    )
})

test('anonymous business routes require login', async ({ page }) => {
    await page.goto('/strategies')
    await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
    await expect(page).toHaveURL(/\/login$/)
})

test('invitation token stays in the URL fragment', async ({ page }) => {
    await page.route('**/api/v1/auth/invitations/inspect', async (route) => {
        const request = route.request()
        expect(request.url()).not.toContain('one-time-token')
        expect((await request.postDataJSON()).token).toBe('one-time-token')
        await route.fulfill({ json: { email: 'invitee@example.com' } })
    })

    await page.goto('/register#token=one-time-token')
    await expect(page.getByLabel('邮箱')).toHaveValue('invitee@example.com')
    await expect(page.getByRole('button', { name: '注册' })).toBeEnabled()
    expect(new URL(page.url()).search).toBe('')
})
