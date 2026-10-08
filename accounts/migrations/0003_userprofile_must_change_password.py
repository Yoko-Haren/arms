from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_remove_userprofile_school_id_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='must_change_password',
            field=models.BooleanField(default=False, help_text='Set when an administrator issues a temporary password; cleared once the user sets their own.'),
        ),
    ]
