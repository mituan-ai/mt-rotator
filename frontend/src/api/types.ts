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
    coverage: string
    counts: {
        catalog: number
        trade_eligible: number
        advice_eligible: number
        ready: number
        stale: number
        missing: number
        blocked: number
    }
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
        state: 'ready' | 'stale' | 'missing' | 'blocked'
        error: string
    }>
}

export interface Instrument {
    symbol: string
    name: string
    exchange: 'XSHG' | 'XSHE'
    asset_class: 'equity' | 'bond' | 'money' | 'gold' | 'cross_border' | 'commodity' | 'unknown'
    settlement_cycle: 't0' | 't1'
    lot_size: number
    listed_on: string | null
    enabled: boolean
    catalog_active: boolean
    data_status: 'ready' | 'stale' | 'missing' | 'blocked'
    data_error: string
    last_bar_date: string | null
    average_amount_20d: string
    trade_eligible: boolean
    advice_eligible: boolean
    latest_close: string | null
}

export interface MarketBar {
    date: string
    open: string
    high: string
    low: string
    close: string
    volume: string
    amount: string
}

export interface InstrumentBarsResponse {
    instrument: Instrument
    adjustment: 'raw'
    source: string
    bars: MarketBar[]
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

export interface Position {
    symbol: string
    name: string
    settlement_cycle: 't0' | 't1'
    shares: number
    sellable_shares: number
    average_cost: string
}

export interface PaperAccount {
    id: string
    account_number: string
    mode: 'manual' | 'legacy_auto'
    risk_level: 'conservative' | 'balanced' | 'aggressive'
    strategy_id: string | null
    strategy_name: string | null
    strategy_slug: string | null
    generation: number
    status: 'active' | 'archived'
    initial_capital: string
    cash: string
    latest_nav: null | { date: string; value: string; cash: string }
    positions?: Position[]
    pending_orders?: Order[]
    created_at: string
    archived_at: string | null
}

export interface Order {
    id: string
    symbol: string
    name: string
    side: 'buy' | 'sell'
    shares: number
    origin: 'user' | 'legacy'
    eligible_on: string
    expires_on: string
    reserved_cash: string
    status: 'pending' | 'filled' | 'rejected' | 'cancelled' | 'expired'
    rejection_reason: string
    cancellable: boolean
    fill?: { price: string; fee: string; filled_on: string; estimated: boolean }
    created_at: string
}

export interface Fill {
    id: string
    order_id: string
    symbol: string
    side: 'buy' | 'sell'
    shares: number
    price: string
    fee: string
    filled_on: string
    estimated: boolean
    created_at: string
}

export interface LedgerEntry {
    id: string
    kind: 'deposit' | 'buy' | 'sell' | 'fee' | 'dividend' | 'split'
    symbol: string | null
    amount: string
    quantity: string
    occurred_on: string
    detail: Record<string, unknown>
    created_at: string
}

export interface NavPoint {
    date: string
    value: string
    cash: string
}

export interface Advice {
    id: string
    strategy_name: string
    strategy_slug: string
    session_date: string
    expires_on: string
    status: 'ready' | 'stale'
    stale?: boolean
    risk_level: string
    target_weights: Record<string, string>
    recommendations: Array<{
        symbol: string
        name: string
        action: 'watch' | 'buy' | 'hold' | 'reduce' | 'sell' | 'waiting' | 'cooldown'
        quantity: number
        actionable: boolean
        current_shares: number
        effective_shares: number
        current_weight: string
        target_weight: string
        estimated_price: string | null
        reason: string
        valid_on: string
    }>
    input_summary: {
        cash: string
        nav: string
        market_state: string
    }
}

export interface LeaderboardRow {
    rank: number | null
    rank_change: number | null
    display_name: string
    account_number: string
    return: string
    max_drawdown: string
    current_nav: string
    account_age_sessions: number
    eligible: boolean
    eligibility_reason: string
    started_at: string
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

export interface LeaderboardPage extends Page<LeaderboardRow> {
    period: string
    as_of_date: string | null
}
