export function StatusBadge({ ok, children }: { ok: boolean; children: React.ReactNode }) {
    return <span className={`status-badge ${ok ? 'status-good' : 'status-warn'}`}>{children}</span>
}
