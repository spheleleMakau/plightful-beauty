from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0003_remove_walkin_finish_time_alter_walkin_start_time')]

    operations = [
        migrations.AddField(model_name='appointment', name='completed_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='walkin', name='completed_at', field=models.DateTimeField(blank=True, null=True)),
    ]