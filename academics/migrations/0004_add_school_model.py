# academics/migrations/0004_add_school_model.py
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('academics', '0003_add_ai_models'),
    ]

    operations = [
        # Create School model
        migrations.CreateModel(
            name='School',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('school_id', models.CharField(help_text='Unique school identifier', max_length=20, unique=True)),
                ('school_name', models.CharField(help_text='Official school name', max_length=200)),
                ('short_name', models.CharField(help_text='Abbreviated school name', max_length=50)),
                ('address', models.TextField(blank=True)),
                ('contact_number', models.CharField(blank=True, max_length=20)),
                ('email_domain', models.CharField(blank=True, help_text='e.g., @deped.gov.ph', max_length=100)),
                ('grading_scale', models.CharField(choices=[('PERCENTAGE', '0-100 Percentage'), ('NUMERIC_1_5', '1.0 - 5.0 (1.0 highest)'), ('NUMERIC_5_1', '5.0 - 1.0 (5.0 highest)'), ('GPA_4', '0.0 - 4.0 GPA'), ('GPA_5', '0.0 - 5.0 GPA'), ('LETTER', 'A - F Letter Grades')], default='PERCENTAGE', max_length=20)),
                ('passing_grade', models.FloatField(default=75.0, help_text='Minimum passing grade')),
                ('period_type', models.CharField(choices=[('QUARTERLY', 'Quarterly - 4 periods'), ('SEMESTRAL', 'Semestral - 2 semesters'), ('TRIMESTRAL', 'Trimestral - 3 periods')], default='QUARTERLY', max_length=20)),
                ('quarters_count', models.IntegerField(default=4, help_text='4 for quarterly, 3 for trimestral, 2 for semestral')),
                ('logo', models.ImageField(blank=True, null=True, upload_to='school_logos/')),
                ('theme_color', models.CharField(default='#2c3e50', help_text='Primary theme color (hex)', max_length=7)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'academics_school',
                'ordering': ['school_name'],
                'verbose_name': 'School',
                'verbose_name_plural': 'Schools',
            },
        ),
        
        # Add school ForeignKey to SchoolYear
        migrations.AddField(
            model_name='schoolyear',
            name='school',
            field=models.ForeignKey(default=1, help_text='School this school year belongs to', on_delete=django.db.models.deletion.CASCADE, related_name='school_years', to='academics.school'),
            preserve_default=False,
        ),
        
        # Add school ForeignKey to GradeLevel
        migrations.AddField(
            model_name='gradelevel',
            name='school',
            field=models.ForeignKey(blank=True, help_text='School this grade level belongs to (optional for global grade levels)', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='grade_levels', to='academics.school'),
        ),
        
        # Add school ForeignKey to Track
        migrations.AddField(
            model_name='track',
            name='school',
            field=models.ForeignKey(blank=True, help_text='School this track belongs to (optional for global tracks)', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='tracks', to='academics.school'),
        ),
        
        # Add school ForeignKey to Subject
        migrations.AddField(
            model_name='subject',
            name='school',
            field=models.ForeignKey(default=1, help_text='School this subject belongs to', on_delete=django.db.models.deletion.CASCADE, related_name='subjects', to='academics.school'),
            preserve_default=False,
        ),
        
        # Add school ForeignKey to Room
        migrations.AddField(
            model_name='room',
            name='school',
            field=models.ForeignKey(default=1, help_text='School this room belongs to', on_delete=django.db.models.deletion.CASCADE, related_name='rooms', to='academics.school'),
            preserve_default=False,
        ),
        
        # Add school ForeignKey to Section
        migrations.AddField(
            model_name='section',
            name='school',
            field=models.ForeignKey(default=1, help_text='School this section belongs to', on_delete=django.db.models.deletion.CASCADE, related_name='sections', to='academics.school'),
            preserve_default=False,
        ),
        
        # Add school ForeignKey to SubjectGroup
        migrations.AddField(
            model_name='subjectgroup',
            name='school',
            field=models.ForeignKey(default=1, help_text='School this subject group belongs to', on_delete=django.db.models.deletion.CASCADE, related_name='subject_groups', to='academics.school'),
            preserve_default=False,
        ),
        
        # Update GradingSchema school field to point to the new School model
        migrations.AlterField(
            model_name='gradingschema',
            name='school',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='grading_schema', to='academics.school'),
        ),
    ]