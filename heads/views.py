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
from attendance.models import AttendanceRecord, AttendanceSummary
from communication.models import Announcement, Notification
from transfers.models import Transfer
from promotion.models import PromotionRecommendation
from audit.models import ActivityLog
from scheduling.models import ClassAssignment  # Add this import
from core.caching import cache_page_for_user, remember_filters
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
        
        if not grade or not grade.initial_grade:
            return JsonResponse({'remark': 'No grade data', 'level': 'N/A'})
        
        from ml_engine.services.ai_remark_generator import ai_remark_generator
        
        result = ai_remark_generator.generate_remark({
            'first_name': enrollment.student.first_name,
            'last_name': enrollment.student.last_name,
            'subject_name': subject.subject_name,
            'grade': float(grade.initial_grade),
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
# SCHOOL PERFORMANCE DASHBOARD - FULLY FIXED
# =============================================================================
@login_required
@remember_filters('heads-performance', ['school_year', 'quarter', 'grade_level'])
@cache_page_for_user()
def school_performance(request):
    """
    School Head — School Performance Dashboard.
    Shows academic indicators, enrollment trends, and student achievement.
    """
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        messages.error(request, 'Access denied. School Heads only.')
        return redirect('signin')

    school_head = request.user
    principal_school = request.user.profile.school
    today = date.today()

    # ── GET params for filters ──
    sy_id = request.GET.get('school_year')
    quarter_label = request.GET.get('quarter')
    grade_level_id = request.GET.get('grade_level', 'all')

    # ── Current School Year ──
    current_sy = None
    current_sy_id = None
    if sy_id:
        try:
            current_sy = SchoolYear.objects.get(id=sy_id, school=principal_school)
            current_sy_id = current_sy.id
        except (SchoolYear.DoesNotExist, ValueError):
            pass
    if not current_sy:
        current_sy = SchoolYear.objects.filter(school=principal_school, is_current=True).first()
        if current_sy:
            current_sy_id = current_sy.id

    has_data = current_sy is not None
    current_sy_label = str(current_sy) if current_sy else 'N/A'
    available_sy = list(SchoolYear.objects.filter(school=principal_school).order_by('-year_start'))

    # ── Quarter: the one asked for, otherwise the same default as the Academic Dashboard ──
    from .views_academic import _default_period
    quarter_obj = None
    if current_sy:
        periods = list(Quarter.objects.filter(school_year=current_sy).order_by('quarter_number'))
        quarter_obj = next((q for q in periods if q.quarter_label == quarter_label), None) or _default_period(periods, principal_school)
    if quarter_obj:
        quarter_label = quarter_obj.quarter_label
    quarter_label = quarter_label or 'Q1'
    quarter_name = f'Quarter {quarter_obj.quarter_number}' if quarter_obj else quarter_label

    # ── Grade Levels for filter ──
    grade_levels = GradeLevel.objects.filter(school=principal_school).order_by('sort_order')

    # ═══════════════════════════════════════════════════════════════
    # STATS CALCULATIONS
    # ═══════════════════════════════════════════════════════════════
    
    # Base enrollment queryset
    enrolled_qs = Enrollment.objects.none()
    if current_sy:
        enrolled_qs = Enrollment.objects.filter(
            school_year=current_sy,
            status__in=['Enrolled', 'Transferred_In']
        )
        if grade_level_id != 'all':
            try:
                enrolled_qs = enrolled_qs.filter(section__grade_level_id=int(grade_level_id))
            except (ValueError, TypeError):
                pass

    total_enrolled = enrolled_qs.count()

    # ── Average Grade ──
    avg_grade = 0
    avg_grade_change = 0
    if current_sy and total_enrolled > 0:
        grades_qs = GradeComponent.objects.filter(
            enrollment__school_year=current_sy,
            enrollment__status__in=['Enrolled', 'Transferred_In']
        )
        if grade_level_id != 'all':
            try:
                grades_qs = grades_qs.filter(enrollment__section__grade_level_id=int(grade_level_id))
            except (ValueError, TypeError):
                pass
        if quarter_obj:
            grades_qs = grades_qs.filter(quarter=quarter_obj)
        
        # Try transmuted_grade first, fallback to initial_grade
        avg_result = grades_qs.aggregate(
            avg_transmuted=Avg('transmuted_grade'),
            avg_initial=Avg('initial_grade')
        )
        
        if avg_result['avg_transmuted'] is not None:
            avg_grade = round(float(avg_result['avg_transmuted']), 1)
        elif avg_result['avg_initial'] is not None:
            avg_grade = round(float(avg_result['avg_initial']), 1)
        
        # Previous quarter comparison
        if quarter_obj and quarter_obj.quarter_number > 1:
            prev_quarter = Quarter.objects.filter(
                school_year=current_sy, 
                quarter_number=quarter_obj.quarter_number - 1
            ).first()
            
            if prev_quarter:
                prev_grades = GradeComponent.objects.filter(
                    enrollment__school_year=current_sy,
                    enrollment__status__in=['Enrolled', 'Transferred_In'],
                    quarter=prev_quarter
                )
                if grade_level_id != 'all':
                    try:
                        prev_grades = prev_grades.filter(enrollment__section__grade_level_id=int(grade_level_id))
                    except (ValueError, TypeError):
                        pass
                
                prev_result = prev_grades.aggregate(
                    avg_transmuted=Avg('transmuted_grade'),
                    avg_initial=Avg('initial_grade')
                )
                
                prev_avg = 0
                if prev_result['avg_transmuted'] is not None:
                    prev_avg = round(float(prev_result['avg_transmuted']), 1)
                elif prev_result['avg_initial'] is not None:
                    prev_avg = round(float(prev_result['avg_initial']), 1)
                
                if prev_avg > 0:
                    avg_grade_change = round(avg_grade - prev_avg, 1)

    # ── Honor Students Count ──
    honor_count = 0
    honor_breakdown = []
    if current_sy and total_enrolled > 0:
        for gl in grade_levels:
            gl_enrolled = enrolled_qs.filter(section__grade_level=gl)
            total_students = gl_enrolled.count()
            
            if total_students == 0:
                honor_breakdown.append({
                    'grade': f'Grade {gl.grade_number}',
                    'total': 0,
                    'highest': 0,
                    'high': 0,
                    'with': 0,
                    'rate': 0,
                })
                continue
            
            # Get grades for this grade level
            gl_grades = GradeComponent.objects.filter(
                enrollment__section__grade_level=gl,
                enrollment__school_year=current_sy,
                enrollment__status__in=['Enrolled', 'Transferred_In']
            )
            if quarter_obj:
                gl_grades = gl_grades.filter(quarter=quarter_obj)
            
            # Per-student average
            student_grades = gl_grades.values('enrollment_id').annotate(
                avg_transmuted=Avg('transmuted_grade'),
                avg_initial=Avg('initial_grade')
            )
            
            highest = 0
            high = 0
            with_honors = 0
            
            for sg in student_grades:
                student_avg = sg['avg_transmuted'] if sg['avg_transmuted'] is not None else (sg['avg_initial'] or 0)
                
                if student_avg >= 95:
                    highest += 1
                elif student_avg >= 90:
                    high += 1
                elif student_avg >= 85:
                    with_honors += 1
            
            honor_count += highest + high + with_honors
            
            honor_breakdown.append({
                'grade': f'Grade {gl.grade_number}',
                'total': total_students,
                'highest': highest,
                'high': high,
                'with': with_honors,
                'rate': round(((highest + high + with_honors) / total_students * 100), 1) if total_students > 0 else 0,
            })

    # ── Passing Rate ──
    passing_rate = 0
    passing_rate_change = 0
    if current_sy and total_enrolled > 0:
        grades_qs = GradeComponent.objects.filter(
            enrollment__school_year=current_sy,
            enrollment__status__in=['Enrolled', 'Transferred_In']
        )
        if grade_level_id != 'all':
            try:
                grades_qs = grades_qs.filter(enrollment__section__grade_level_id=int(grade_level_id))
            except (ValueError, TypeError):
                pass
        if quarter_obj:
            grades_qs = grades_qs.filter(quarter=quarter_obj)
        
        student_avgs = grades_qs.values('enrollment_id').annotate(
            avg_transmuted=Avg('transmuted_grade'),
            avg_initial=Avg('initial_grade')
        )
        
        total_with_grades = student_avgs.count()
        passed = 0
        
        for sa in student_avgs:
            student_avg = sa['avg_transmuted'] if sa['avg_transmuted'] is not None else (sa['avg_initial'] or 0)
            if float(student_avg) >= 75:
                passed += 1
        
        if total_with_grades > 0:
            passing_rate = round((passed / total_with_grades) * 100, 1)
        
        # Previous quarter comparison
        if quarter_obj and quarter_obj.quarter_number > 1:
            prev_quarter = Quarter.objects.filter(
                school_year=current_sy, 
                quarter_number=quarter_obj.quarter_number - 1
            ).first()
            
            if prev_quarter:
                prev_grades = GradeComponent.objects.filter(
                    enrollment__school_year=current_sy,
                    enrollment__status__in=['Enrolled', 'Transferred_In'],
                    quarter=prev_quarter
                )
                if grade_level_id != 'all':
                    try:
                        prev_grades = prev_grades.filter(enrollment__section__grade_level_id=int(grade_level_id))
                    except (ValueError, TypeError):
                        pass
                
                prev_avgs = prev_grades.values('enrollment_id').annotate(
                    avg_transmuted=Avg('transmuted_grade'),
                    avg_initial=Avg('initial_grade')
                )
                
                prev_total = prev_avgs.count()
                prev_passed = 0
                for pa in prev_avgs:
                    p_avg = pa['avg_transmuted'] if pa['avg_transmuted'] is not None else (pa['avg_initial'] or 0)
                    if float(p_avg) >= 75:
                        prev_passed += 1
                
                if prev_total > 0:
                    prev_rate = round((prev_passed / prev_total) * 100, 1)
                    passing_rate_change = round(passing_rate - prev_rate, 1)

    # ── Attendance Rate ──
    attendance_rate = 0
    if current_sy:
        attendance_qs = AttendanceSummary.objects.filter(school_year=current_sy)
        if quarter_obj:
            quarter_months = {
                'Q1': [6, 7, 8],
                'Q2': [9, 10, 11],
                'Q3': [12, 1, 2],
                'Q4': [3, 4, 5],
            }
            months = quarter_months.get(quarter_label, [])
            attendance_qs = attendance_qs.filter(month__in=months)
        
        if grade_level_id != 'all':
            try:
                attendance_qs = attendance_qs.filter(section__grade_level_id=int(grade_level_id))
            except (ValueError, TypeError):
                pass
        
        if attendance_qs.exists():
            total_rate = 0
            count = 0
            for summary in attendance_qs:
                if summary.absence_rate_percent is not None:
                    rate = 100 - summary.absence_rate_percent
                    total_rate += rate
                    count += 1
                elif summary.days_present and summary.total_school_days and summary.total_school_days > 0:
                    rate = (summary.days_present / summary.total_school_days) * 100
                    total_rate += rate
                    count += 1
            
            if count > 0:
                attendance_rate = round(float(total_rate) / count, 1)      # Decimal -> float for the charts

    # ═══════════════════════════════════════════════════════════════
    # ENROLLMENT TREND (5-Year)
    # ═══════════════════════════════════════════════════════════════
    enrollment_trend_labels = []
    enrollment_trend_data = []
    
    all_sy = list(SchoolYear.objects.filter(school=principal_school).order_by('year_start'))
    if current_sy and all_sy:
        current_idx = next((i for i, sy in enumerate(all_sy) if sy.id == current_sy.id), len(all_sy) - 1)
        start_idx = max(0, current_idx - 4)
        recent_sy = all_sy[start_idx:current_idx + 1]
    else:
        recent_sy = all_sy[-5:] if len(all_sy) > 5 else all_sy
    
    for sy in recent_sy:
        enrollment_trend_labels.append(str(sy))
        count = Enrollment.objects.filter(
            school_year=sy,
            status__in=['Enrolled', 'Transferred_In']
        ).count()
        enrollment_trend_data.append(count)

    # ═══════════════════════════════════════════════════════════════
    # PROMOTION RATE BY GRADE LEVEL
    # ═══════════════════════════════════════════════════════════════
    promotion_labels = []
    promotion_data = []
    
    if current_sy:
        for gl in grade_levels:
            promotion_labels.append(f'G{gl.grade_number}')
            
            gl_enrolled = Enrollment.objects.filter(
                school_year=current_sy,
                section__grade_level=gl,
                status__in=['Enrolled', 'Transferred_In']
            ).count()
            
            if gl_enrolled > 0:
                promoted = PromotionRecommendation.objects.filter(
                    enrollment__school_year=current_sy,
                    enrollment__section__grade_level=gl,
                    recommendation='Promoted'
                ).count()
                rate = round((promoted / gl_enrolled) * 100, 1)
                promotion_data.append(rate)
            else:
                promotion_data.append(0)

    # ═══════════════════════════════════════════════════════════════
    # SUBJECT PERFORMANCE - FIXED: using subject_name instead of name
    # ═══════════════════════════════════════════════════════════════
    subject_averages = []
    if current_sy:
        subject_grades = GradeComponent.objects.filter(
            enrollment__school_year=current_sy,
            enrollment__status__in=['Enrolled', 'Transferred_In']
        ).select_related('subject')
        
        if grade_level_id != 'all':
            try:
                subject_grades = subject_grades.filter(enrollment__section__grade_level_id=int(grade_level_id))
            except (ValueError, TypeError):
                pass
        if quarter_obj:
            subject_grades = subject_grades.filter(quarter=quarter_obj)
        
        # FIXED: Using subject_name and subject_code (actual field names)
        subject_data = subject_grades.values(
            'subject_id',
        ).annotate(
            avg_transmuted=Avg('transmuted_grade'),
            avg_initial=Avg('initial_grade'),
        ).order_by('subject_id')
        
        # Get subject names separately
        subject_ids = [item['subject_id'] for item in subject_data if item['subject_id']]
        
        # Fetch subjects in one query
        from academics.models import Subject  # or wherever your Subject model is
        subjects_map = {}
        if subject_ids:
            for subj in Subject.objects.filter(id__in=subject_ids):
                subjects_map[subj.id] = subj.subject_name or subj.subject_code or f'Subject {subj.id}'
        
        for item in subject_data:
            avg_val = item['avg_transmuted'] if item['avg_transmuted'] is not None else (item['avg_initial'] or 0)
            subject_name = subjects_map.get(item['subject_id'], f'Subject {item["subject_id"]}')
            
            if avg_val and float(avg_val) > 0:
                subject_averages.append({
                    'subject': subject_name,
                    'avg': round(float(avg_val), 1),
                })
    
    # Fallback if no subject data
    if not subject_averages:
        subject_averages = [
            {'subject': 'No grade data available', 'avg': 0},
        ]

    # ═══════════════════════════════════════════════════════════════
    # YEAR-OVER-YEAR COMPARISON
    # ═══════════════════════════════════════════════════════════════
    yoy_labels = ['Avg Grade', 'Passing Rate', 'Attendance', 'Honor Rate']
    prev_year_data = [0, 0, 0, 0]
    curr_year_data = [
        avg_grade,
        passing_rate,
        attendance_rate,
        round((honor_count / total_enrolled * 100), 1) if total_enrolled > 0 else 0,
    ]
    
    if current_sy:
        prev_sy = SchoolYear.objects.filter(
            school=principal_school,
            year_start__lt=current_sy.year_start
        ).order_by('-year_start').first()
        
        if prev_sy:
            prev_enrolled = Enrollment.objects.filter(
                school_year=prev_sy,
                status__in=['Enrolled', 'Transferred_In']
            )
            prev_count = prev_enrolled.count()
            
            if prev_count > 0:
                prev_grades = GradeComponent.objects.filter(
                    enrollment__school_year=prev_sy,
                    enrollment__status__in=['Enrolled', 'Transferred_In']
                )
                
                prev_grade_result = prev_grades.aggregate(
                    avg_transmuted=Avg('transmuted_grade'),
                    avg_initial=Avg('initial_grade')
                )
                prev_avg = prev_grade_result['avg_transmuted'] or prev_grade_result['avg_initial'] or 0
                prev_year_data[0] = round(float(prev_avg), 1)
                
                prev_student_avgs = prev_grades.values('enrollment_id').annotate(
                    avg_transmuted=Avg('transmuted_grade'),
                    avg_initial=Avg('initial_grade')
                )
                
                prev_passed = 0
                prev_honor = 0
                for psa in prev_student_avgs:
                    p_avg = float(psa['avg_transmuted'] or psa['avg_initial'] or 0)
                    if p_avg >= 75:
                        prev_passed += 1
                    if p_avg >= 85:
                        prev_honor += 1
                
                prev_year_data[1] = round((prev_passed / prev_count * 100), 1)
                prev_year_data[3] = round((prev_honor / prev_count * 100), 1)
            
            prev_attendance = AttendanceSummary.objects.filter(school_year=prev_sy)
            if prev_attendance.exists():
                prev_att_total = 0
                prev_att_count = 0
                for pa in prev_attendance:
                    if pa.absence_rate_percent is not None:
                        prev_att_total += (100 - pa.absence_rate_percent)
                        prev_att_count += 1
                if prev_att_count > 0:
                    prev_year_data[2] = round(float(prev_att_total) / prev_att_count, 1)

    # ═══════════════════════════════════════════════════════════════
    # NOTIFICATIONS
    # ═══════════════════════════════════════════════════════════════
    notifications = []
    try:
        notif_qs = Notification.objects.filter(
            recipient=school_head, is_read=False
        ).order_by('-created_at')[:10]
        
        for n in notif_qs:
            icon_map = {
                'FORM_SUBMITTED': ('fi-rr-document', 'form'),
                'FORM_APPROVED': ('fi-rr-check-circle', 'form'),
                'FORM_RETURNED': ('fi-rr-undo', 'form'),
                'GRADE_SUBMITTED': ('fi-rr-chart-histogram', 'grade'),
                'GRADE_APPROVED': ('fi-rr-check-circle', 'grade'),
                'TRANSFER_REQUESTED': ('fi-rr-exchange', 'transfer'),
                'PROMOTION_REVIEW_NEEDED': ('fi-rr-trophy', 'alert'),
                'CORRECTION_REQUESTED': ('fi-rr-edit', 'alert'),
            }
            icon, icon_class = icon_map.get(n.notification_type, ('fi-rr-bell', 'form'))
            notifications.append({
                'id': n.id,
                'title': n.title,
                'message': n.message,
                'icon': icon,
                'icon_class': icon_class,
                'time_ago': _time_ago(n.created_at),
                'is_read': n.is_read,
                'type': n.notification_type.lower() if n.notification_type else 'general',
            })
    except Exception:
        pass
    
    notification_count = len(notifications)

    # ═══════════════════════════════════════════════════════════════
    # PORO MESSAGE
    # ═══════════════════════════════════════════════════════════════
    poro_message = f"Average grade at {avg_grade}%. {honor_count} honor students. {passing_rate}% passing rate this quarter."
    
    if passing_rate_change > 0:
        poro_message += f" Up {passing_rate_change}% from last quarter!"
    elif passing_rate_change < 0:
        poro_message += f" Down {abs(passing_rate_change)}% from last quarter."

    # ═══════════════════════════════════════════════════════════════
    # JSON-safe data for Chart.js
    # ═══════════════════════════════════════════════════════════════
    import json as json_module
    
    context = {
        'has_data': has_data,
        'current_sy_label': current_sy_label,
        'current_sy_id': current_sy_id,
        'available_sy': available_sy,
        'quarter_label': quarter_label,
        'quarter_name': quarter_name,
        'grade_levels': grade_levels,
        'selected_grade': grade_level_id,
        
        # Stats cards
        'avg_grade': avg_grade,
        'avg_grade_change': avg_grade_change,
        'honor_count': honor_count,
        'honor_breakdown': honor_breakdown,
        'passing_rate': passing_rate,
        'passing_rate_change': passing_rate_change,
        'attendance_rate': attendance_rate,
        
        # Charts (JSON safe)
        'enrollment_trend_labels': json_module.dumps(enrollment_trend_labels),
        'enrollment_trend_data': json_module.dumps(enrollment_trend_data),
        'promotion_labels': json_module.dumps(promotion_labels),
        'promotion_data': json_module.dumps(promotion_data),
        'subject_averages': subject_averages,
        'yoy_labels': json_module.dumps(yoy_labels),
        'prev_year_data': json_module.dumps(prev_year_data),
        'curr_year_data': json_module.dumps(curr_year_data),
        
        # Notifications
        'notifications': notifications,
        'notification_count': notification_count,
        'poro_message': poro_message,
        'today': today,
    }
    from .views_academic import school_fingerprint
    context['live_fingerprint'] = school_fingerprint(principal_school) if principal_school else ''

    return render(request, 'heads/performance/school_performance.html', context)


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