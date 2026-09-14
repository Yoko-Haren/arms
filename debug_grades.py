# debug_grades.py
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
django.setup()

from django.db.models import Count, Q
from enrollment.models import Enrollment
from grades.models import GradeComponent, FinalGrade, QuarterlyGrade
from academics.models import Quarter, SchoolYear

print("=" * 60)
print("GRADE DATA DEBUG")
print("=" * 60)

# 1. Check GradeComponent
print(f"\n1. GradeComponent table:")
print(f"   Total records: {GradeComponent.objects.count()}")
print(f"   With initial_grade: {GradeComponent.objects.filter(initial_grade__isnull=False).count()}")
print(f"   Distinct enrollments: {GradeComponent.objects.values('enrollment_id').distinct().count()}")

# 2. Check FinalGrade
print(f"\n2. FinalGrade table:")
print(f"   Total records: {FinalGrade.objects.count()}")
print(f"   With final_grade: {FinalGrade.objects.filter(final_grade__isnull=False).count()}")

# 3. Check QuarterlyGrade
print(f"\n3. QuarterlyGrade table:")
print(f"   Total records: {QuarterlyGrade.objects.count()}")

# 4. Find enrollments with complete grade data
print(f"\n4. Enrollments with GradeComponent data:")
enrollments_with_grades = Enrollment.objects.annotate(
    grade_count=Count('grade_components')
).filter(grade_count__gt=0)

print(f"   Count: {enrollments_with_grades.count()}")

# Show sample
for e in enrollments_with_grades[:3]:
    print(f"\n   Enrollment ID: {e.id}")
    print(f"   Student: {e.student.first_name} {e.student.last_name}")
    print(f"   Section: {e.section}")
    print(f"   Grade Level: {e.section.grade_level.grade_name if e.section and e.section.grade_level else 'N/A'}")
    
    grades = GradeComponent.objects.filter(enrollment=e).select_related('subject', 'quarter')
    for g in grades:
        print(f"     - {g.subject.subject_name}: Q{g.quarter.quarter_number} = {g.initial_grade}")

# 5. Check quarters in current school year
current_sy = SchoolYear.objects.filter(is_current=True).first()
if current_sy:
    print(f"\n5. Quarters in {current_sy.year_label}:")
    for q in Quarter.objects.filter(school_year=current_sy).order_by('quarter_number'):
        print(f"   {q.quarter_label}: {q.date_start} to {q.date_end}")

print("\n" + "=" * 60)
print("DEBUG COMPLETE")
print("=" * 60)