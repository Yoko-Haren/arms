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
from academics.models import Subject, SubjectKPUPSummary, KPUPMastery
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




def _generate_proficiency_recommendation(section_name, subject_name, avg_grade, section_prof_level,
                                          advanced, proficient, approaching, developing, beginning,
                                          total_students, passing_rate, trend_direction):
    """Generate AI recommendation based on DO 31 proficiency levels."""
    
    if section_prof_level == 'ADVANCED':
        summary = f"{section_name} is at ADVANCED level in {subject_name} with {avg_grade}% average. {advanced} of {total_students} students scored 90%+."
    elif section_prof_level == 'PROFICIENT':
        summary = f"{section_name} is at PROFICIENT level in {subject_name} with {avg_grade}% average. {proficient} students meeting expectations."
    elif section_prof_level == 'APPROACHING PROFICIENCY':
        summary = f"{section_name} is APPROACHING PROFICIENCY in {subject_name} with {avg_grade}% average. {approaching} students near the proficient threshold."
    elif section_prof_level == 'DEVELOPING':
        summary = f"{section_name} is at DEVELOPING level in {subject_name} with {avg_grade}% average. {beginning} student(s) at Beginning level need intervention."
    else:
        summary = f"{section_name} is at BEGINNING level in {subject_name} with {avg_grade}% average. {beginning} student(s) require immediate intervention."
    
    insights = f"• Passing rate: {passing_rate}%\n"
    insights += f"• Advanced: {advanced} | Proficient: {proficient} | Approaching: {approaching} | Developing: {developing} | Beginning: {beginning}\n"
    if trend_direction == 'improving':
        insights += "• Positive trend detected — current interventions may be working\n"
    elif trend_direction == 'declining':
        insights += "• Declining trend — investigate causes before next quarter\n"
    elif trend_direction == 'stable':
        insights += "• Stable performance across quarters\n"
    
    if section_prof_level in ['BEGINNING', 'DEVELOPING']:
        recommendations = (
            "• Schedule principal classroom observation within 2 weeks\n"
            "• Implement targeted remediation for Beginning-level students\n"
            "• Assign peer tutoring or after-school intervention\n"
            "• Parent-teacher conference for at-risk students"
        )
    elif section_prof_level == 'APPROACHING PROFICIENCY':
        recommendations = (
            "• Focus on moving Approaching students to Proficient level\n"
            "• Review assessment item difficulty and alignment\n"
            "• Provide enrichment activities to bridge the gap"
        )
    elif section_prof_level == 'PROFICIENT':
        recommendations = (
            "• Maintain current instructional strategies\n"
            "• Challenge Proficient students with enrichment tasks\n"
            "• Set goal to increase Advanced count next quarter"
        )
    else:
        recommendations = (
            "• Document teaching practices for replication across other sections\n"
            "• Consider this section for peer demonstration teaching\n"
            "• Nominate top students for academic competitions"
        )
    
    return {
        'summary': summary,
        'insights': insights,
        'recommendations': recommendations,
        'confidence': 85,
    }





def _generate_kpup_recommendation(section_name, subject_name, avg_grade, section_prof_level,
                                   advanced, proficient, approaching, developing, beginning, total_students,
                                   avg_k, avg_pr, avg_u, avg_pd, trend_direction):
    """Generate AI recommendation based on KPUP proficiency levels."""
    
    # One-sentence summary
    if section_prof_level == 'ADVANCED':
        summary = f"{section_name} is at Advanced level in {subject_name} with {avg_grade}% average. {advanced} of {total_students} students scored 90%+."
    elif section_prof_level == 'PROFICIENT':
        summary = f"{section_name} is at Proficient level in {subject_name} with {avg_grade}% average. {proficient} students are meeting expectations."
    elif section_prof_level == 'APPROACHING PROFICIENCY':
        summary = f"{section_name} is Approaching Proficiency in {subject_name} with {avg_grade}% average. {approaching} students are near the proficient threshold."
    elif section_prof_level == 'DEVELOPING':
        summary = f"{section_name} is at Developing level in {subject_name} with {avg_grade}% average. {beginning} students are at Beginning level."
    else:
        summary = f"{section_name} is at Beginning level in {subject_name} with {avg_grade}% average. Immediate intervention needed for {beginning} students."
    
    # Key insights
    insights = []
    
    # KPUP dimension analysis
    dims = {'Knowledge': avg_k, 'Process': avg_pr, 'Understanding': avg_u, 'Product': avg_pd}
    weakest = min(dims, key=dims.get)
    strongest = max(dims, key=dims.get)
    
    insights.append(f"• Strongest cognitive dimension: {strongest} ({dims[strongest]}%)")
    insights.append(f"• Weakest cognitive dimension: {weakest} ({dims[weakest]}%) — needs focus")
    
    if advanced > 0:
        insights.append(f"• {advanced} student(s) at Advanced level — consider enrichment activities")
    if beginning > 0:
        insights.append(f"• {beginning} student(s) at Beginning level — needs remediation")
    if trend_direction == 'improving':
        insights.append("• Positive trend detected — current interventions may be working")
    elif trend_direction == 'declining':
        insights.append("• Declining trend — investigate cause before next quarter")
    
    # Recommendations
    recommendations = []
    
    if section_prof_level in ['BEGINNING', 'DEVELOPING']:
        recommendations.append(f"• Schedule principal classroom observation for {subject_name}")
        recommendations.append(f"• Implement targeted remediation focusing on {weakest} skills")
        recommendations.append("• Assign peer tutoring for Beginning-level students")
        recommendations.append("• Parent-teacher conference for at-risk students")
    elif section_prof_level == 'APPROACHING PROFICIENCY':
        recommendations.append(f"• Focus on moving Approaching students to Proficient via {weakest} improvement")
        recommendations.append("• Review assessment item difficulty in Understanding and Product dimensions")
    elif section_prof_level == 'PROFICIENT':
        recommendations.append("• Maintain current instructional strategies")
        recommendations.append(f"• Challenge Proficient students with more {strongest}-focused enrichment")
    else:
        recommendations.append("• Document teaching practices for replication across other sections")
        recommendations.append("• Consider this section for peer demonstration teaching")
    
    return {
        'summary': summary,
        'insights': '\n'.join(insights),
        'recommendations': '\n'.join(recommendations),
        'confidence': 85,
    }
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
    
# =============================================================================
# KPUP COGNITIVE DISCIPLINE DASHBOARD
# =============================================================================

@login_required
def kpup_dashboard(request):
    """
    Principal's KPUP Dashboard — Shows all subjects with cognitive discipline 
    breakdown (Knowledge, Process, Understanding, Product).
    """
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        messages.error(request, 'Access denied. School Heads only.')
        return redirect('signin')
    
    school_head = request.user
    today = date.today()
    
    # GET params
    sy_id = request.GET.get('school_year')
    quarter_label = request.GET.get('quarter', 'Q3')
    
    # Current School Year
    current_sy = None
    if sy_id:
        try:
            current_sy = SchoolYear.objects.get(id=sy_id)
        except SchoolYear.DoesNotExist:
            pass
    if not current_sy:
        current_sy = SchoolYear.objects.filter(is_current=True).first()
    
    has_data = current_sy is not None
    current_sy_label = str(current_sy) if current_sy else 'N/A'
    available_sy = list(SchoolYear.objects.all().order_by('-year_start'))
    
    # Quarter
    quarter_obj = None
    if current_sy:
        quarter_obj = Quarter.objects.filter(
            school_year=current_sy, quarter_label=quarter_label
        ).first()
    quarter_name = f'Quarter {quarter_obj.quarter_number}' if quarter_obj else quarter_label
    
    # Get KPUP dashboard data
    from academics.services.kpup_service import get_subject_kpup_dashboard
    
    kpup_subjects = []
    if current_sy and quarter_obj:
        kpup_subjects = get_subject_kpup_dashboard(current_sy, quarter_obj)
    
    # Summary stats
    total_subjects = len(kpup_subjects)
    strong_count = sum(1 for s in kpup_subjects if s['status'] == 'strong')
    adequate_count = sum(1 for s in kpup_subjects if s['status'] == 'adequate')
    attention_count = sum(1 for s in kpup_subjects if s['status'] == 'needs_attention')
    
    # Overall KPUP averages
    if total_subjects > 0:
        overall_k = round(sum(s['avg_knowledge'] for s in kpup_subjects) / total_subjects, 1)
        overall_p = round(sum(s['avg_process'] for s in kpup_subjects) / total_subjects, 1)
        overall_u = round(sum(s['avg_understanding'] for s in kpup_subjects) / total_subjects, 1)
        overall_product = round(sum(s['avg_product'] for s in kpup_subjects) / total_subjects, 1)
    else:
        overall_k = overall_p = overall_u = overall_product = 0
    
    # Notifications
    notifications = []
    notification_count = 0
    try:
        notif_qs = Notification.objects.filter(
            recipient=school_head, is_read=False
        ).order_by('-created_at')[:10]
        for n in notif_qs:
            icon_map = {
                'FORM_SUBMITTED': ('fi-rr-document', 'form'),
                'FORM_APPROVED': ('fi-rr-check-circle', 'form'),
                'GRADE_SUBMITTED': ('fi-rr-chart-histogram', 'grade'),
            }
            icon, icon_class = icon_map.get(n.notification_type, ('fi-rr-bell', 'form'))
            notifications.append({
                'id': n.id, 'title': n.title, 'message': n.message,
                'icon': icon, 'icon_class': icon_class,
                'time_ago': _time_ago(n.created_at), 'is_read': n.is_read,
            })
        notification_count = len(notifications)
    except Exception:
        pass
    
    import json as json_module
    
    # Prepare JSON for charts
    kpup_labels = ['Knowledge', 'Process', 'Understanding', 'Product']
    
    context = {
        'has_data': has_data,
        'current_sy_label': current_sy_label,
        'current_sy_id': current_sy.id if current_sy else None,
        'available_sy': available_sy,
        'quarter_label': quarter_label,
        'quarter_name': quarter_name,
        
        'kpup_subjects': kpup_subjects,
        'total_subjects': total_subjects,
        'strong_count': strong_count,
        'adequate_count': adequate_count,
        'attention_count': attention_count,
        
        'overall_k': overall_k,
        'overall_p': overall_p,
        'overall_u': overall_u,
        'overall_product': overall_product,
        'kpup_labels': json_module.dumps(kpup_labels),
        
        'notifications': notifications,
        'notification_count': notification_count,
        'today': today,
    }
    
    return render(request, 'heads/kpup_dashboard/index.html', context)


@login_required
def kpup_subject_detail(request, subject_id):
    """
    Drill-down: Single subject KPUP with section-by-section breakdown.
    """
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        messages.error(request, 'Access denied. School Heads only.')
        return redirect('signin')
    
    subject = get_object_or_404(Subject, id=subject_id)
    
    sy_id = request.GET.get('school_year')
    quarter_label = request.GET.get('quarter', 'Q3')
    
    current_sy = None
    if sy_id:
        try:
            current_sy = SchoolYear.objects.get(id=sy_id)
        except SchoolYear.DoesNotExist:
            pass
    if not current_sy:
        current_sy = SchoolYear.objects.filter(is_current=True).first()
    
    quarter_obj = None
    if current_sy:
        quarter_obj = Quarter.objects.filter(
            school_year=current_sy, quarter_label=quarter_label
        ).first()
    
    # Get section breakdown
    section_data = []
    all_sections_k = []
    all_sections_p = []
    all_sections_u = []
    all_sections_product = []
    section_labels = []
    
    if current_sy and quarter_obj:
        sections = Section.objects.filter(
            school_year=current_sy, is_active=True
        ).order_by('grade_level__grade_number', 'section_name')
        
        for section in sections:
            masteries = KPUPMastery.objects.filter(
                subject=subject,
                quarter=quarter_obj,
                school_year=current_sy,
                student__enrollments__section=section,
                student__enrollments__school_year=current_sy,
                student__enrollments__status__in=['Enrolled', 'Transferred_In']
            ).distinct()
            
            if not masteries.exists():
                continue
            
            total = masteries.count()
            avg_k = round(masteries.aggregate(Avg('knowledge_score'))['knowledge_score__avg'] or 0, 1)
            avg_p = round(masteries.aggregate(Avg('process_score'))['process_score__avg'] or 0, 1)
            avg_u = round(masteries.aggregate(Avg('understanding_score'))['understanding_score__avg'] or 0, 1)
            avg_prod = round(masteries.aggregate(Avg('product_score'))['product_score__avg'] or 0, 1)
            
            section_data.append({
                'section_id': section.id,
                'section_name': section.section_name,
                'grade_level': section.grade_level.grade_name,
                'total_students': total,
                'avg_k': avg_k,
                'avg_p': avg_p,
                'avg_u': avg_u,
                'avg_product': avg_prod,
                'overall_avg': round((avg_k + avg_p + avg_u + avg_prod) / 4, 1),
                'advanced': masteries.filter(overall_mastery='ADVANCED').count(),
                'proficient': masteries.filter(overall_mastery='PROFICIENT').count(),
                'developing': masteries.filter(overall_mastery='DEVELOPING').count(),
                'beginning': masteries.filter(overall_mastery='BEGINNING').count(),
            })
            
            all_sections_k.append(avg_k)
            all_sections_p.append(avg_p)
            all_sections_u.append(avg_u)
            all_sections_product.append(avg_prod)
            section_labels.append(str(section))
    
    # Subject summary
    subject_summary = SubjectKPUPSummary.objects.filter(
        subject=subject, quarter=quarter_obj, school_year=current_sy
    ).first()
    
    import json as json_module
    
    context = {
        'subject': subject,
        'current_sy_label': str(current_sy) if current_sy else 'N/A',
        'quarter_name': f'Quarter {quarter_obj.quarter_number}' if quarter_obj else 'N/A',
        'section_data': section_data,
        'subject_summary': subject_summary,
        'section_labels': json_module.dumps(section_labels),
        'sections_k': json_module.dumps(all_sections_k),
        'sections_p': json_module.dumps(all_sections_p),
        'sections_u': json_module.dumps(all_sections_u),
        'sections_product': json_module.dumps(all_sections_product),
        'today': date.today(),
    }
    
    return render(request, 'heads/kpup_dashboard/subject_detail.html', context)

    
@login_required
def kpup_subject_detail(request, subject_id):
    """
    Drill-down: Subject-level KPUP with section breakdown.
    Shows how each section performs across K-P-U-P dimensions.
    """
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        messages.error(request, 'Access denied. School Heads only.')
        return redirect('signin')
    
    subject = get_object_or_404(Subject, id=subject_id)
    
    sy_id = request.GET.get('school_year')
    quarter_label = request.GET.get('quarter', 'Q3')
    
    current_sy = None
    if sy_id:
        try:
            current_sy = SchoolYear.objects.get(id=sy_id)
        except SchoolYear.DoesNotExist:
            pass
    if not current_sy:
        current_sy = SchoolYear.objects.filter(is_current=True).first()
    
    quarter_obj = None
    if current_sy:
        quarter_obj = Quarter.objects.filter(
            school_year=current_sy, quarter_label=quarter_label
        ).first()
    
    # Get section breakdown
    section_data = []
    if current_sy and quarter_obj:
        sections = Section.objects.filter(
            school_year=current_sy,
            is_active=True
        ).order_by('grade_level__grade_number', 'section_name')
        
        for section in sections:
            masteries = KPUPMastery.objects.filter(
                subject=subject,
                quarter=quarter_obj,
                school_year=current_sy,
                student__enrollments__section=section,
                student__enrollments__school_year=current_sy,
                student__enrollments__status__in=['Enrolled', 'Transferred_In']
            ).distinct()
            
            if not masteries.exists():
                continue
            
            total = masteries.count()
            
            section_data.append({
                'section_id': section.id,
                'section_name': section.section_name,
                'grade_level': section.grade_level.grade_name,
                'total_students': total,
                'avg_k': round(masteries.aggregate(Avg('knowledge_score'))['knowledge_score__avg'] or 0, 1),
                'avg_p': round(masteries.aggregate(Avg('process_score'))['process_score__avg'] or 0, 1),
                'avg_u': round(masteries.aggregate(Avg('understanding_score'))['understanding_score__avg'] or 0, 1),
                'avg_product': round(masteries.aggregate(Avg('product_score'))['product_score__avg'] or 0, 1),
                'advanced': masteries.filter(overall_mastery='ADVANCED').count(),
                'proficient': masteries.filter(overall_mastery='PROFICIENT').count(),
                'developing': masteries.filter(overall_mastery='DEVELOPING').count(),
                'beginning': masteries.filter(overall_mastery='BEGINNING').count(),
            })
    
    # Subject KPUP Summary
    subject_summary = SubjectKPUPSummary.objects.filter(
        subject=subject,
        quarter=quarter_obj,
        school_year=current_sy
    ).first()
    
    import json as json_module
    
    context = {
        'subject': subject,
        'current_sy_label': str(current_sy) if current_sy else 'N/A',
        'quarter_name': f'Quarter {quarter_obj.quarter_number}' if quarter_obj else 'N/A',
        'section_data': section_data,
        'subject_summary': subject_summary,
        'today': date.today(),
    }
    
    return render(request, 'heads/kpup_dashboard/subject_detail.html', context)