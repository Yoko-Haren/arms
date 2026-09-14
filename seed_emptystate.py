#!/usr/bin/env python
"""
Create a fresh empty-state teacher account.
No students, no grades, no attendance - just the teacher account.
"""

import os
from datetime import date

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.contrib.auth.models import User
from accounts.models import UserProfile
from academics.models import SchoolYear, Section, GradeLevel, Subject


def create_empty_teacher():
    """Create a fresh teacher account with no data."""
    
    print("=" * 60)
    print("📝 CREATING FRESH EMPTY TEACHER ACCOUNT")
    print("=" * 60)
    
    # Get the current school year
    school_year = SchoolYear.objects.get(is_current=True)
    print(f"📅 School Year: {school_year.year_label}")
    
    # ─────────────────────────────────────────────────────
    # Create fresh teacher account
    # ─────────────────────────────────────────────────────
    email = "fresh.teacher@deped.gov.ph"
    password = "fresh123"
    
    # Delete existing if present
    User.objects.filter(username=email).delete()
    print(f"\n🗑️  Cleaned up any existing account for {email}")
    
    # Create user
    teacher = User.objects.create_user(
        username=email,
        email=email,
        password=password,
        first_name="Fresh",
        last_name="Teacher",
        is_active=True,
    )
    
    # Create profile
    profile, _ = UserProfile.objects.update_or_create(
        user=teacher,
        defaults={
            "role": "teacher",
            "deped_email": email,
            "is_homeroom_adviser": False,  # Not an adviser yet
            "position_title": "Teacher I",
            "designation": "Newly Assigned Teacher",
            "teaching_area": "",
            "employment_status": "Probationary",
            "date_hired": date.today(),
            "employee_number": f"DEPED-NEW-{date.today().strftime('%Y%m%d')}",
            "is_active": True,
            "notes": "Fresh account - no data assigned yet.",
        }
    )
    
    print(f"\n✅ TEACHER ACCOUNT CREATED!")
    print(f"{'='*60}")
    print(f"""
  ┌─────────────────────────────────────────────────────────┐
  │                 FRESH TEACHER ACCOUNT                    │
  ├─────────────────────────────────────────────────────────┤
  │ Email:      {email:<45} │
  │ Password:   {password:<45} │
  │ Name:       {teacher.get_full_name():<45} │
  │ Role:       {profile.get_role_display():<45} │
  │ Status:     {'Active' if teacher.is_active else 'Inactive':<45} │
  ├─────────────────────────────────────────────────────────┤
  │ Students:   0                                            │
  │ Grades:     0                                            │
  │ Attendance: 0                                            │
  │ Sections:   None assigned                                │
  └─────────────────────────────────────────────────────────┘
  
  Login at: http://127.0.0.1:8000/teachers/dashboard/
  """)
    
    return teacher


if __name__ == "__main__":
    create_empty_teacher()