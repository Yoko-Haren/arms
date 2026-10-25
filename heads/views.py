# heads/views.py
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import User
from django.db.models import Count, Q, Avg, Sum, F, FloatField, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from datetime import date, timedelta
import json
import csv

from academics.models import SchoolYear, GradeLevel, Section, Quarter, Subject, GradingSchema, SectionQuarterlySummary, AISectionRecommendation, GradePrediction
from enrollment.models import Enrollment
from accounts.models import UserProfile, SchoolForm
from evaluation.models import TeacherEvaluation
from documentation.models import FormSubmission, FormCompliance
from grades.models import GradeComponent
from core.periods import grade_value
from communication.models import Announcement, Notification
from transfers.models import Transfer
from audit.models import ActivityLog
from scheduling.models import ClassAssignment  # Add this import
from django.db import models
from academics.models import SubjectFamily  # Add this line
import json as json_module



# =============================================================================
# NEW: AI ACADEMIC INTELLIGENCE SERVICES
# =============================================================================

def _time_ago(dt):
    """Return a human-readable time difference."""
    if not dt:
        return 'Unknown'
    now = timezone.now()
    diff = now - dt
    if diff.days > 365:
        years = diff.days // 365
        return f'{years} year{"s" if years > 1 else ""} ago'
    elif diff.days > 30:
        months = diff.days // 30
        return f'{months} month{"s" if months > 1 else ""} ago'
    elif diff.days > 0:
        return f'{diff.days} day{"s" if diff.days > 1 else ""} ago'
    elif diff.seconds > 3600:
        hours = diff.seconds // 3600
        return f'{hours} hour{"s" if hours > 1 else ""} ago'
    elif diff.seconds > 60:
        minutes = diff.seconds // 60
        return f'{minutes} minute{"s" if minutes > 1 else ""} ago'
    else:
        return 'Just now'


def _log(request, action_type, resource_type, resource_id, description):
    """Create an ActivityLog entry."""
    try:
        user_name = request.user.get_full_name() if request.user.is_authenticated else 'System'
        user_role = request.user.profile.role if hasattr(request.user, 'profile') else 'Unknown'
        ActivityLog.objects.create(
            user=request.user if request.user.is_authenticated else None,
            user_name=user_name,
            user_role=user_role,
            action_type=action_type,
            resource_type=resource_type,
            resource_id=str(resource_id),
            details_json={'description': description},
            ip_address=request.META.get('REMOTE_ADDR', '127.0.0.1'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
        )
    except Exception:
        pass


@login_required
def get_ai_remark(request, enrollment_id, subject_id, quarter_id):
    """AJAX endpoint: Generate AI remark for a single student"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    try:
        enrollment = Enrollment.objects.get(id=enrollment_id)
        subject = Subject.objects.get(id=subject_id)
        quarter = Quarter.objects.get(id=quarter_id)
        
        grade = GradeComponent.objects.filter(
            enrollment=enrollment, subject=subject, quarter=quarter
        ).first()
        
        value = grade_value(grade.transmuted_grade, grade.initial_grade) if grade else None
        if value is None:
            return JsonResponse({'remark': 'No grade data', 'level': 'N/A'})
        
        from ml_engine.services.ai_remark_generator import ai_remark_generator
        
        result = ai_remark_generator.generate_remark({
            'first_name': enrollment.student.first_name,
            'last_name': enrollment.student.last_name,
            'subject_name': subject.subject_name,
            'grade': value,
            'trend': 'stable',
            'attendance_rate': 85,
            'quarter': quarter.quarter_label,
            'grade_level': enrollment.section.grade_level.grade_number if enrollment.section and enrollment.section.grade_level else 10,
        })
        
        return JsonResponse({
            'remark': result['personalized_remark'],
            'level': result['proficiency_abbreviation'],
            'model': result['ai_model'],
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)




@login_required
@csrf_exempt
def ai_mark_recommendation_implemented(request, recommendation_id):
    """
    Mark an AI recommendation as implemented (for feedback and improvement)
    """
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    try:
        recommendation = get_object_or_404(AISectionRecommendation, id=recommendation_id)
        
        data = json.loads(request.body)
        recommendation.was_implemented = True
        recommendation.implemented_at = timezone.now()
        recommendation.implementation_notes = data.get('notes', '')
        recommendation.principal_feedback = data.get('feedback', '')
        recommendation.save()
        
        _log(request, 'IMPLEMENT_RECOMMENDATION', 'AISectionRecommendation', recommendation.id,
             f'Implemented AI recommendation for {recommendation.section_summary.section}')
        
        return JsonResponse({'success': True, 'message': 'Recommendation marked as implemented'})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# =============================================================================
# MARK NOTIFICATIONS AS READ (AJAX)
# =============================================================================
@login_required
def mark_notifications_read(request):
    """Mark all notifications as read for the school head."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    try:
        Notification.objects.filter(
            recipient=request.user, is_read=False
        ).update(is_read=True)
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
