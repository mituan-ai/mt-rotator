from django.db import migrations
from django.utils import timezone


def create_manual_accounts(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    PaperAccount = apps.get_model("paper", "PaperAccount")
    LedgerEntry = apps.get_model("paper", "LedgerEntry")
    StrategyVersion = apps.get_model("strategies", "StrategyVersion")
    strategy = StrategyVersion.objects.filter(active=True).order_by("name", "-published_at").first()
    now = timezone.now()

    PaperAccount.objects.filter(status="active", mode="legacy_auto").update(
        status="archived", archived_at=now
    )
    for user in User.objects.all().iterator():
        account = PaperAccount.objects.create(
            user_id=user.id,
            strategy_version_id=strategy.id if strategy else None,
            mode="manual",
            risk_level="balanced",
            generation=1,
            status="active",
            initial_capital=100000,
            cash=100000,
        )
        LedgerEntry.objects.create(
            account_id=account.id,
            kind="deposit",
            amount=100000,
            occurred_on=timezone.localdate(account.created_at),
            event_key=f"manual-initial:{account.id}",
            detail={"source": "manual_account_migration"},
        )


class Migration(migrations.Migration):
    dependencies = [("paper", "0003_advicesnapshot_positionlot_and_more")]

    operations = [migrations.RunPython(create_manual_accounts, migrations.RunPython.noop)]
