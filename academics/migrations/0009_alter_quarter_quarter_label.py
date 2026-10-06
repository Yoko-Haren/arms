from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('academics', '0008_assessment_assessmentquestion_assessmentresponse_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='quarter',
            name='quarter_label',
            field=models.CharField(choices=[('Q1', 'Q1'), ('Q2', 'Q2'), ('Q3', 'Q3'), ('Q4', 'Q4'), ('T1', 'T1'), ('T2', 'T2'), ('T3', 'T3'), ('S1', 'S1'), ('S2', 'S2')], max_length=10),
        ),
    ]
