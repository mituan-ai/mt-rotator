import { expect, test } from '@playwright/test'

test.skip(!process.env.E2E_BASE_URL, 'requires the real Compose application')

test('real invitation registration and permission isolation', async ({ page }) => {
    const memberEmail = `member-${Date.now()}@example.com`
    const password = 'Correct-Horse-Battery-Staple-2026'

    await page.goto('/login')
    await page.getByLabel('邮箱').fill('admin@example.com')
    await page.getByLabel('密码').fill(password)
    await page.getByRole('button', { name: '登录' }).click()
    await page.getByRole('link', { name: '管理' }).click()
    await page.getByLabel('邮箱').fill(memberEmail)
    await page.getByLabel('备注').fill('全栈测试')
    await page.getByRole('button', { name: '生成一次性链接' }).click()
    const invitationLink = await page.locator('.invite-link code').innerText()

    await page.getByRole('button', { name: '退出登录' }).click()
    await page.goto(invitationLink)
    await expect(page.getByLabel('邮箱')).toHaveValue(memberEmail)
    await page.getByLabel('显示名称').fill('测试用户')
    await page.getByLabel('密码').fill(password)
    await page.getByRole('button', { name: '注册' }).click()
    await expect(page.getByRole('heading', { name: '总览' })).toBeVisible()

    await page.goto('/admin')
    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByRole('heading', { name: '总览' })).toBeVisible()
})
