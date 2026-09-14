#!/usr/bin/env python
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.contrib.auth.models import User
from students.models import Student, Guardian, StudentAddress, StudentContact
from enrollment.models import Enrollment, EnrollmentDocument
from attendance.models import AttendanceRecord, AttendanceSummary
from grades.models import GradeComponent
from scheduling.models import ClassAssignment, ClassSchedule
from academics.models import Section

def wipe_seed_data():
    print("🧹 Starting wipe of seed data...")
    
    # Delete in correct order (child tables first)
    
    # 1. Grades
    grade_count = GradeComponent.objects.all().count()
    GradeComponent.objects.all().delete()
    print(f"✅ Deleted {grade_count} grade components")
    
    # 2. Attendance
    attendance_count = AttendanceRecord.objects.all().count()
    AttendanceRecord.objects.all().delete()
    print(f"✅ Deleted {attendance_count} attendance records")
    
    summary_count = AttendanceSummary.objects.all().count()
    AttendanceSummary.objects.all().delete()
    print(f"✅ Deleted {summary_count} attendance summaries")
    
    # 3. Scheduling
    schedule_count = ClassSchedule.objects.all().count()
    ClassSchedule.objects.all().delete()
    print(f"✅ Deleted {schedule_count} class schedules")
    
    assignment_count = ClassAssignment.objects.all().count()
    ClassAssignment.objects.all().delete()
    print(f"✅ Deleted {assignment_count} class assignments")
    
    # 4. Enrollment
    enrollment_count = Enrollment.objects.all().count()
    Enrollment.objects.all().delete()
    print(f"✅ Deleted {enrollment_count} enrollments")
    
    # 5. Students (cascade deletes guardians, addresses, contacts)
    student_count = Student.objects.all().count()
    Student.objects.all().delete()
    print(f"✅ Deleted {student_count} students (and their guardians, addresses, contacts)")
    
    # 6. Section (optional - if you want to reset section enrollment count)
    section = Section.objects.filter(section_name="ABM C", strand__strand_code="ABM").first()
    if section:
        section.current_enrollment_count = 0
        section.save()
        print(f"✅ Reset section {section.section_name} enrollment count to 0")
    
    # 7. User (optional - uncomment if you want to delete the teacher user too)
    # user = User.objects.filter(username="User.one@deped.gov.ph").first()
    # if user:
    #     user.delete()
    #     print(f"✅ Deleted user User.one@deped.gov.ph")
    
    print("\n" + "="*50)
    print("✅ WIPE COMPLETE! Database is clean.")
    print("="*50)
    print("You can now run your seeder again.")

if __name__ == "__main__":
    confirm = input("⚠️ This will delete ALL students, enrollments, grades, and attendance. Continue? (yes/no): ")
    if confirm.lower() == "yes":
        wipe_seed_data()
    else:
        print("❌ Wipe cancelled.")