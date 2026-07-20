export interface User {
    id: string
    email: string
    display_name: string
    is_staff: boolean
    is_active: boolean
}

export interface MarketStatus {
    ready: boolean
    expected_session: string
    source: string
    validation_source: string
    adjustments: string[]
    last_batch: null | {
        id: string
        status: 'healthy' | 'degraded' | 'failed'
        finished_at: string
        errors: Array<Record<string, string>>
        warnings: Array<Record<string, string>>
    }
    instruments: Array<{
        symbol: string
        name: string
        latest_date: string | null
        raw_latest_date: string | null
        hfq_latest_date: string | null
        state: 'ready' | 'stale' | 'missing'
    }>
}

export interface Signal {
    id: string
    strategy_slug: string
    strategy_name: string
    signal_date: string
    tradable_on: string
    target_weights: Record<string, number>
    rationale: Record<string, unknown>
    data_source: {
        provider: string
        cutoff_date: string
        adjustment: string
    }
}

export interface Strategy {
    id: string
    slug: string
    name: string
    description: string
    version: string
    parameters: Record<string, unknown>
    risk_symbols: string[]
    defensive_weights: Record<string, number>
    active: boolean
    latest_signal?: Signal | null
}

export interface PaperAccount {
    id: string
    strategy_id: string
    strategy_name: string
    strategy_slug: string
    generation: number
    status: 'active' | 'archived'
    initial_capital: string
    cash: string
    latest_nav: null | { date: string; value: string; cash: string }
    positions?: Array<{
        symbol: string
        name: string
        shares: number
        average_cost: string
    }>
    pending_rebalances?: Array<{
        id: string
        eligible_on: string
        target_weights: Record<string, number>
        source: string
        status: string
    }>
}

export interface BacktestRun {
    id: string
    strategy_name: string
    strategy_slug: string
    start_date: string
    end_date: string
    initial_capital: string
    status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
    result?: {
        assumptions: Record<string, unknown>
        metrics: Record<string, number | string>
        nav: Array<{ date: string; value: number }>
        trades: Array<Record<string, string | number | boolean | null>>
    }
    error: string
    data_snapshot: {
        cutoff_date: string
        provider: string
        digest: string
    }
    created_at: string
}

export interface Page<T> {
    count: number
    next: string | null
    previous: string | null
    results: T[]
}
