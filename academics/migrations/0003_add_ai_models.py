# academics/migrations/0003_add_ai_models.py
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('academics', '0002_initial'),
        ('enrollment', '0001_initial'),
    ]

    operations = [
        # Create GradingSchema table
        migrations.CreateModel(
            name='GradingSchema',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('scale_type', models.CharField(choices=[('PERCENTAGE', '0-100 Percentage'), ('NUMERIC_1_5', '1.0 - 5.0 (1.0 highest)'), ('NUMERIC_5_1', '5.0 - 1.0 (5.0 highest)'), ('GPA_4', '0.0 - 4.0 GPA'), ('LETTER', 'A - F Letter Grades')], default='PERCENTAGE', max_length=20)),
                ('passing_threshold', models.FloatField(default=75.0)),
                ('highest_is_best', models.BooleanField(default=True)),
                ('rounding_rule', models.CharField(choices=[('NEAREST_INT', 'Round to nearest integer (0.5 up)'), ('NEAREST_INT_DOWN', 'Round down always'), ('ONE_DECIMAL', 'Keep 1 decimal place'), ('TWO_DECIMAL', 'Keep 2 decimal places'), ('NONE', 'No rounding')], default='NEAREST_INT', max_length=20)),
                ('letter_grade_mapping', models.JSONField(blank=True, default=dict)),
                ('min_value', models.FloatField(default=0)),
                ('max_value', models.FloatField(default=100)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('school', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='grading_schema', to='academics.school')),
            ],
            options={
                'db_table': 'academics_gradingschema',
            },
        ),
        
        # Create SectionQuarterlySummary table
        migrations.CreateModel(
            name='SectionQuarterlySummary',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('average_grade', models.FloatField(default=0)),
                ('median_grade', models.FloatField(default=0)),
                ('highest_grade', models.FloatField(default=0)),
                ('lowest_grade', models.FloatField(default=0)),
                ('passing_rate', models.FloatField(default=0)),
                ('excellent_rate', models.FloatField(default=0)),
                ('at_risk_count', models.IntegerField(default=0)),
                ('total_students', models.IntegerField(default=0)),
                ('trend_direction', models.CharField(blank=True, max_length=20)),
                ('trend_slope', models.FloatField(default=0)),
                ('category', models.CharField(blank=True, choices=[('EXCELLENCE', 'Excellence Track'), ('STANDARD', 'Standard Track'), ('INTERVENTION', 'Intervention Track')], max_length=20)),
                ('category_score', models.FloatField(default=0)),
                ('needs_intervention', models.BooleanField(default=False)),
                ('calculated_at', models.DateTimeField(auto_now_add=True)),
                ('quarter', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='section_summaries', to='academics.quarter')),
                ('section', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='quarterly_summaries', to='academics.section')),
                ('school_year', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='section_summaries', to='academics.schoolyear')),
                ('subject', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='section_summaries', to='academics.subject')),
            ],
            options={
                'db_table': 'academics_sectionquarterlysummary',
                'unique_together': {('section', 'subject', 'quarter', 'school_year')},
            },
        ),
        
        # Create AISectionRecommendation table
        migrations.CreateModel(
            name='AISectionRecommendation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('category', models.CharField(max_length=50)),
                ('one_sentence_summary', models.TextField()),
                ('key_insights', models.TextField()),
                ('recommendations', models.TextField()),
                ('confidence_score', models.FloatField(default=0)),
                ('was_implemented', models.BooleanField(default=False)),
                ('implemented_at', models.DateTimeField(blank=True, null=True)),
                ('implementation_notes', models.TextField(blank=True)),
                ('principal_feedback', models.TextField(blank=True)),
                ('generated_at', models.DateTimeField(auto_now_add=True)),
                ('section_summary', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='ai_recommendation', to='academics.sectionquarterlysummary')),
            ],
            options={
                'db_table': 'academics_aisectionrecommendation',
            },
        ),
        
        # Create GradePrediction table
        migrations.CreateModel(
            name='GradePrediction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('predicted_grade', models.FloatField()),
                ('actual_grade', models.FloatField(blank=True, null=True)),
                ('confidence_score', models.FloatField()),
                ('risk_score', models.FloatField(default=0)),
                ('risk_factors', models.JSONField(blank=True, default=list)),
                ('is_at_risk', models.BooleanField(default=False)),
                ('predicted_at', models.DateTimeField(auto_now_add=True)),
                ('model_version', models.CharField(blank=True, max_length=50)),
                ('enrollment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='grade_predictions', to='enrollment.enrollment')),
                ('quarter', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='grade_predictions', to='academics.quarter')),
                ('subject', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='grade_predictions', to='academics.subject')),
            ],
            options={
                'db_table': 'academics_gradeprediction',
                'ordering': ['-predicted_at'],
            },
        ),
    ]