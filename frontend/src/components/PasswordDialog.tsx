import * as Dialog from '@radix-ui/react-dialog'
import { KeyRound, X } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { api } from '../api/client'

export function PasswordDialog() {
    const [open, setOpen] = useState(false)
    const [currentPassword, setCurrentPassword] = useState('')
    const [newPassword, setNewPassword] = useState('')
    const [error, setError] = useState('')
    const [submitting, setSubmitting] = useState(false)

    async function submit(event: FormEvent) {
        event.preventDefault()
        setSubmitting(true)
        setError('')
        try {
            await api.post('/auth/password/change', {
                current_password: currentPassword,
                new_password: newPassword
            })
            setCurrentPassword('')
            setNewPassword('')
            setOpen(false)
        } catch (reason) {
            setError(reason instanceof Error ? reason.message : '密码修改失败')
        } finally {
            setSubmitting(false)
        }
    }

    return (
        <Dialog.Root open={open} onOpenChange={setOpen}>
            <Dialog.Trigger asChild>
                <button className="icon-button" aria-label="修改密码" title="修改密码">
                    <KeyRound size={17} />
                </button>
            </Dialog.Trigger>
            <Dialog.Portal>
                <Dialog.Overlay className="dialog-overlay" />
                <Dialog.Content className="dialog-content" aria-describedby={undefined}>
                    <div className="panel-heading"><div><p className="eyebrow">SECURITY</p><Dialog.Title>修改密码</Dialog.Title></div><Dialog.Close className="icon-button" aria-label="关闭"><X size={16} /></Dialog.Close></div>
                    <form onSubmit={submit}>
                        <label>当前密码<input type="password" required autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} /></label>
                        <label>新密码<input type="password" required minLength={12} autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} /></label>
                        {error && <p className="form-error">{error}</p>}
                        <button className="primary-button" disabled={submitting}>{submitting ? '正在保存' : '保存'}</button>
                    </form>
                </Dialog.Content>
            </Dialog.Portal>
        </Dialog.Root>
    )
}
