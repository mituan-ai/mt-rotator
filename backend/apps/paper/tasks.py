from celery import shared_task

from apps.market.models import MarketDataBatch
from apps.market.services import create_snapshot
from apps.strategies.services import generate_all_month_end_signals

from .models import PaperAccount, PaperRebalance
from .services import apply_actions_for_date, enqueue_signal_for_accounts, process_rebalance, snapshot_account


@shared_task(name="apps.paper.tasks.run_daily_paper_cycle")
def run_daily_paper_cycle(batch_id: str) -> dict:
    batch = MarketDataBatch.objects.get(pk=batch_id)
    if batch.status != MarketDataBatch.Status.HEALTHY or not batch.expected_session:
        return {"status": "blocked", "reason": "market_data_not_healthy"}
    snapshot = create_snapshot(batch.expected_session)
    signals = generate_all_month_end_signals(snapshot)
    queued = sum(enqueue_signal_for_accounts(signal) for signal in signals)
    accounts = list(PaperAccount.objects.filter(status=PaperAccount.Status.ACTIVE))
    for account in accounts:
        apply_actions_for_date(account, batch.expected_session)
    processed = 0
    for item in PaperRebalance.objects.filter(
        status=PaperRebalance.Status.PENDING,
        eligible_on__lte=batch.expected_session,
    ):
        process_rebalance(item, item.eligible_on)
        processed += 1
    for account in accounts:
        snapshot_account(account, batch.expected_session)
    return {"status": "ok", "signals": len(signals), "queued": queued, "processed": processed}
