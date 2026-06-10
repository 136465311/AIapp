from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_user_pending_review"),
    ]

    operations = [
        migrations.AddField(
            model_name="recharge",
            name="out_trade_no",
            field=models.CharField(blank=True, max_length=64, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="recharge",
            name="provider_trade_no",
            field=models.CharField(blank=True, max_length=80),
        ),
    ]
