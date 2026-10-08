import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('accounts', '0003_userprofile_must_change_password'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='google_sub',
            field=models.CharField(blank=True, help_text="Google account ID ('sub') bound to this user. NULL until the user links Google.", max_length=64, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='google_email',
            field=models.EmailField(blank=True, help_text='Address of the bound Google account.', max_length=254),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='google_linked_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name='EmailCode',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('purpose', models.CharField(choices=[('bind_google', 'Link Google account'), ('password_reset', 'Password reset'), ('change_email', 'Change email address')], db_index=True, max_length=20)),
                ('code_hash', models.CharField(help_text='Keyed hash of the 6-digit code; the code itself is never stored.', max_length=128)),
                ('sent_to', models.EmailField(max_length=254)),
                ('payload', models.JSONField(blank=True, default=dict, help_text='What the code confirms, e.g. the Google account being linked.')),
                ('attempts', models.PositiveSmallIntegerField(default=0)),
                ('created_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('expires_at', models.DateTimeField()),
                ('used_at', models.DateTimeField(blank=True, null=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='email_codes', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Email Code',
                'verbose_name_plural': 'Email Codes',
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['user', 'purpose', 'created_at'], name='accounts_emailcode_lookup')],
            },
        ),
    ]
