import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("paper", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="PaperCycleRun",
            fields=[
                (
                    "id",
                    models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False),
                ),
                ("session_date", models.DateField(unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "待处理"),
                            ("running", "处理中"),
                            ("succeeded", "完成"),
                            ("failed", "失败"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=12,
                    ),
                ),
                ("attempt_count", models.PositiveIntegerField(default=0)),
                ("lease_expires_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-session_date"]},
        )
    ]
