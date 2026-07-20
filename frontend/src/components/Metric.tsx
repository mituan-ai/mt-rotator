export function Metric({ label, value, tone }: { label: string; value: string; tone?: 'up' | 'down' }) {
    return (
        <div className="metric">
            <span>{label}</span>
            <strong className={tone === 'up' ? 'number-up' : tone === 'down' ? 'number-down' : ''}>{value}</strong>
        </div>
    )
}
