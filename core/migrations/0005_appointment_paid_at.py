from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0004_completion_times')]

    operations = [
        migrations.AddField(model_name='appointment', name='paid_at', field=models.DateTimeField(blank=True, null=True)),
    ]