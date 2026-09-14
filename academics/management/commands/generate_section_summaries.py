# academics/management/commands/generate_section_summaries.py

from django.core.management.base import BaseCommand
from django.db.models import Avg, Count, Q
from academics.models import Section, Subject, Quarter, SchoolYear, SectionQuarterlySummary
from grades.models import QuarterlyGrade
from academics.services.trend_detection import detect_trend
from academics.services.categorization_service import categorize_section


class Command(BaseCommand):
    help = 'Generate section quarterly summaries for AI analysis'
    
    def add_arguments(self, parser):
        parser.add_argument('--school_year', type=int, help='School year ID')
        parser.add_argument('--quarter', type=int, help='Quarter ID')
    
    def handle(self, *args, **options):
        school_year_id = options.get('school_year')
        quarter_id = options.get('quarter')
        
        # Get all sections with enrollments
        sections = Section.objects.filter(
            is_active=True,
            school_year_id=school_year_id
        )
        
        subjects = Subject.objects.filter(is_active=True)
        quarters = Quarter.objects.filter(school_year_id=school_year_id)
        
        if quarter_id:
            quarters = quarters.filter(id=quarter_id)
        
        total_processed = 0
        
        for section in sections:
            for subject in subjects:
                for quarter in quarters:
                    # Get all grades for this section-subject-quarter
                    grades = QuarterlyGrade.objects.filter(
                        enrollment__section_id=section.id,
                        subject_id=subject.id,
                        quarter_id=quarter.id
                    ).select_related('enrollment__student')
                    
                    if not grades.exists():
                        continue
                    
                    grade_values = [g.initial_grade for g in grades if g.initial_grade]
                    
                    if not grade_values:
                        continue
                    
                    # Calculate metrics
                    avg_grade = sum(grade_values) / len(grade_values)
                    passing_count = sum(1 for g in grade_values if g >= 75)
                    excellent_count = sum(1 for g in grade_values if g >= 90)
                    at_risk_count = sum(1 for g in grade_values if g < 75)
                    
                    passing_rate = (passing_count / len(grade_values)) * 100
                    excellent_rate = (excellent_count / len(grade_values)) * 100
                    
                    # Get historical grades for trend detection
                    previous_quarters = Quarter.objects.filter(
                        school_year_id=school_year_id,
                        quarter_number__lt=quarter.quarter_number
                    ).order_by('quarter_number')
                    
                    historical_grades = []
                    for prev_q in previous_quarters:
                        prev_grades = QuarterlyGrade.objects.filter(
                            enrollment__section_id=section.id,
                            subject_id=subject.id,
                            quarter_id=prev_q.id
                        )
                        if prev_grades.exists():
                            prev_avg = sum([g.initial_grade for g in prev_grades if g.initial_grade]) / len(prev_grades)
                            historical_grades.append(prev_avg)
                    
                    historical_grades.append(avg_grade)
                    
                    # Detect trend
                    trend = detect_trend(historical_grades)
                    
                    # Categorize
                    category_data = categorize_section({
                        'average_grade': avg_grade,
                        'passing_rate': passing_rate,
                        'excellent_rate': excellent_rate,
                        'at_risk_count': at_risk_count,
                        'total_students': len(grade_values)
                    })
                    
                    # Update or create summary
                    summary, created = SectionQuarterlySummary.objects.update_or_create(
                        section=section,
                        subject=subject,
                        quarter=quarter,
                        school_year_id=school_year_id,
                        defaults={
                            'average_grade': round(avg_grade, 2),
                            'median_grade': round(sorted(grade_values)[len(grade_values)//2], 2),
                            'highest_grade': round(max(grade_values), 2),
                            'lowest_grade': round(min(grade_values), 2),
                            'passing_rate': round(passing_rate, 2),
                            'excellent_rate': round(excellent_rate, 2),
                            'at_risk_count': at_risk_count,
                            'total_students': len(grade_values),
                            'trend_direction': trend['direction'],
                            'trend_slope': trend['slope'],
                            'category': category_data['category'],
                            'category_score': category_data['score'],
                            'needs_intervention': category_data['needs_intervention'],
                        }
                    )
                    
                    total_processed += 1
        
        self.stdout.write(
            self.style.SUCCESS(f'Generated {total_processed} section summaries')
        )