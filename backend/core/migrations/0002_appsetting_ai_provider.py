from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="appsetting",
            name="ai_relay_base_url",
            field=models.URLField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="appsetting",
            name="ai_root_api_key",
            field=models.CharField(blank=True, default="", max_length=256),
        ),
        migrations.AddField(
            model_name="appsetting",
            name="chat_model",
            field=models.CharField(default="gpt-4o-mini", max_length=80),
        ),
        migrations.AddField(
            model_name="appsetting",
            name="image_model",
            field=models.CharField(default="gpt-image-1", max_length=80),
        ),
    ]
