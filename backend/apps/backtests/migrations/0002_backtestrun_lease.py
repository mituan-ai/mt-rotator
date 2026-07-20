from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("backtests", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="backtestrun",
            name="attempt_count",
            field=models.PositiveIntegerField(default=0, null=True),
        ),
        migrations.AddField(
            model_name="backtestrun",
            name="lease_expires_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="backtestrun",
            name="lease_token",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
    ]
