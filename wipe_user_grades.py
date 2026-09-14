#!/usr/bin/env python
"""
Wipe all grade components for all 4 seed teachers.
"""
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.contrib.auth.models import User
from grades.models import GradeComponent
from scheduling.models import ClassAssignment
from enrollment.models import Enrollment


def wipe_grades_for_user(email):
    """Delete all grade components for a specific teacher."""
    
    print(f"\n{'='*60}")
    print(f"🔍 Processing: {email}")
    print(f"{'='*60}")
    
    # Get the user
    try:
        teacher = User.objects.get(username=email)
        print(f"✅ Found: {teacher.get_full_name()}")
    except User.DoesNotExist:
        print(f"❌ User '{email}' not found!")
        return 0
    
    # Get sections this teacher has class assignments for
    class_assignments = ClassAssignment.objects.filter(teacher=teacher)
    
    if not class_assignments.exists():
        print(f"⚠️ No class assignments found")
        return 0
    
    section_ids = class_assignments.values_list('section_id', flat=True).distinct()
    subject_ids = class_assignments.values_list('subject_id', flat=True).distinct()
    
    # Also get sections where this teacher is the adviser
    from academics.models import Section
    advised_sections = Section.objects.filter(adviser=teacher).values_list('id', flat=True)
    all_section_ids = set(list(section_ids) + list(advised_sections))
    
    # Count grades before deletion
    grade_count = GradeComponent.objects.filter(
        enrollment__section_id__in=all_section_ids,
        encoded_by=teacher
    ).count()
    
    print(f"📊 Grades encoded by this teacher: {grade_count}")
    
    if grade_count == 0:
        print("✅ No grades to wipe!")
        return 0
    
    # Delete the grades
    deleted = GradeComponent.objects.filter(
        enrollment__section_id__in=all_section_ids,
        encoded_by=teacher
    ).delete()[0]
    
    print(f"🗑️  Deleted: {deleted} grade components")
    
    return deleted


if __name__ == "__main__":
    # All 4 teacher emails
    teacher_emails = [
        "User.one@deped.gov.ph",
        "jen.takashie@deped.gov.ph",
        "jeren.takashie@deped.gov.ph",
        "juan.delacruz.teach@deped.gov.ph",
    ]
    
    print("=" * 60)
    print("⚠️  GRADE WIPE SCRIPT - ALL 4 TEACHERS")
    print("=" * 60)
    print("\nTarget teachers:")
    for email in teacher_emails:
        print(f"  • {email}")
    
    print("\n⚠️  This will delete ALL grades for ALL 4 teachers!")
    print("    This action CANNOT be undone!")
    print("=" * 60)
    
    confirm = input("\nAre you sure? Type 'DELETE ALL GRADES' to confirm: ")
    
    if confirm == "DELETE ALL GRADES":
        print("\n🚀 Starting grade wipe for all teachers...")
        
        total_deleted = 0
        for email in teacher_emails:
            deleted = wipe_grades_for_user(email)
            total_deleted += deleted
        
        print(f"\n{'='*60}")
        print(f"✅ COMPLETE! Total grades deleted: {total_deleted}")
        print(f"{'='*60}")
    else:
        print("\n❌ Operation cancelled. No changes were made.")