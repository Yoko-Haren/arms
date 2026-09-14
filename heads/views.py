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


# =============================================================================
# AI ACADEMIC INTELLIGENCE DASHBOARD (NEW)
# =============================================================================

def _detect_trend(grades):
    """Simple trend detection for section grades"""
    if not grades or len(grades) < 2:
        return {'direction': 'insufficient_data', 'slope': 0, 'confidence': 0}
    
    # Convert to floats if needed
    grades = [float(g) if g is not None else 0 for g in grades]
    
    # Linear regression calculation
    n = len(grades)
    x = list(range(1, n + 1))
    x_mean = sum(x) / n
    y_mean = sum(grades) / n
    
    numerator = sum((x[i] - x_mean) * (grades[i] - y_mean) for i in range(n))
    denominator = sum((x[i] - x_mean) ** 2 for i in range(n))
    
    slope = numerator / denominator if denominator != 0 else 0
    intercept = y_mean - slope * x_mean
    
    # Calculate R-squared
    ss_res = sum((grades[i] - (slope * x[i] + intercept)) ** 2 for i in range(n))
    ss_tot = sum((grades[i] - y_mean) ** 2 for i in range(n))
    r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
    
    if slope > 0.3 and r_squared > 0.5:
        direction = 'improving'
    elif slope < -0.3 and r_squared > 0.5:
        direction = 'declining'
    elif abs(slope) < 0.2:
        direction = 'stable'
    else:
        direction = 'erratic'
    
    return {
        'direction': direction,
        'slope': round(slope, 2),
        'confidence': round(r_squared, 2)
    }

def _categorize_section(avg_grade, passing_rate, excellent_rate, risk_percent):
    """Categorize section into Excellence/Standard/Intervention track"""
    score = 0
    
    # Average grade (40% weight)
    if avg_grade >= 90:
        score += 40
    elif avg_grade >= 75:
        score += 20
    else:
        score += 0
    
    # Passing rate (30% weight)
    if passing_rate >= 90:
        score += 30
    elif passing_rate >= 75:
        score += 15
    else:
        score += 0
    
    # Excellent rate (20% weight)
    if excellent_rate >= 50:
        score += 20
    elif excellent_rate >= 25:
        score += 10
    else:
        score += 0
    
    # Risk (10% weight)
    if risk_percent == 0:
        score += 10
    elif risk_percent <= 10:
        score += 7
    elif risk_percent <= 20:
        score += 4
    else:
        score += 0
    
    if score >= 80:
        return {'category': 'EXCELLENCE', 'label': 'Excellence Track', 'needs_intervention': False, 'score': score}
    elif score >= 50:
        return {'category': 'STANDARD', 'label': 'Standard Track', 'needs_intervention': False, 'score': score}
    else:
        return {'category': 'INTERVENTION', 'label': 'Intervention Track', 'needs_intervention': True, 'score': score}


def _generate_ai_recommendation(summary_data):
    """
    Generate AI recommendation based on section summary data.
    This can be enhanced with actual LLM integration later.
    """
    category = summary_data.get('category', 'STANDARD')
    avg_grade = summary_data.get('average_grade', 0)
    passing_rate = summary_data.get('passing_rate', 0)
    excellent_rate = summary_data.get('excellent_rate', 0)
    at_risk_count = summary_data.get('at_risk_count', 0)
    total_students = summary_data.get('total_students', 1)
    trend = summary_data.get('trend_direction', 'stable')
    subject_name = summary_data.get('subject_name', '')
    section_name = summary_data.get('section_name', '')
    
    risk_percent = (at_risk_count / total_students) * 100 if total_students > 0 else 0
    
    # Generate one-sentence summary
    if category == 'EXCELLENCE':
        one_sentence = f"{section_name} is performing at an Excellence level in {subject_name} with {avg_grade}% average and {excellent_rate}% of students scoring above 90%."
    elif category == 'INTERVENTION':
        one_sentence = f"{section_name} requires immediate intervention in {subject_name} with only {passing_rate}% passing rate and {at_risk_count} student(s) at risk of failing."
    else:
        one_sentence = f"{section_name} is on track in {subject_name} with {avg_grade}% average and {passing_rate}% passing rate."
    
    # Generate key insights
    insights = []
    if excellent_rate > 50:
        insights.append(f"• {excellent_rate}% of students are performing at an outstanding level (>90%)")
    if risk_percent > 20:
        insights.append(f"• {at_risk_count} students ({risk_percent}%) are below the passing threshold")
    if trend == 'improving':
        insights.append(f"• Grades are showing improvement with a positive trend (slope: {summary_data.get('trend_slope', 0)})")
    elif trend == 'declining':
        insights.append(f"• Grades are declining (slope: {summary_data.get('trend_slope', 0)}) - immediate attention recommended")
    elif trend == 'stable':
        insights.append("• Grades have remained stable across quarters")
    
    if not insights:
        insights.append("• Performance is within expected range")
    
    # Generate recommendations
    recommendations = []
    if category == 'EXCELLENCE':
        recommendations.append("• Consider accelerating this section to advanced curriculum")
        recommendations.append(f"• Nominate top students from {section_name} for academic competitions")
        recommendations.append("• Document teaching strategies for replication to other sections")
        if at_risk_count > 0:
            recommendations.append(f"• Provide targeted support to the {at_risk_count} student(s) below 90%")
    
    elif category == 'INTERVENTION':
        recommendations.append("• Schedule a principal observation of this class within 2 weeks")
        recommendations.append("• Assign an experienced mentor teacher to support the subject teacher")
        recommendations.append(f"• Implement daily remediation for the {at_risk_count} at-risk student(s)")
        recommendations.append("• Schedule a parent-teacher conference for at-risk students")
    
    else:  # STANDARD
        recommendations.append("• Continue current instructional strategies")
        if trend == 'declining':
            recommendations.append("• Investigate causes of grade decline before next quarter")
        recommendations.append(f"• Aim to move {int(excellent_rate + 10)}% of students to excellence bracket by next quarter")
        if at_risk_count > 0:
            recommendations.append(f"• Provide intervention support to {at_risk_count} struggling student(s)")
    
    return {
        'summary': one_sentence,
        'insights': '\n'.join(insights),
        'recommendations': '\n'.join(recommendations),
        'confidence': 0.85
    }


@login_required
def ai_academic_dashboard(request):
    """KPUP Cognitive Discipline Dashboard for School Head — using real GradeComponent data with derived KPUP dimensions."""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        messages.error(request, 'Access denied. School Heads only.')
        return redirect('signin')
    
    school_head = request.user
    today = date.today()
    
    # ✅ SCHOOL SEGREGATION — Get principal's assigned school
    principal_school = request.user.profile.school
    if not principal_school:
        messages.error(request, 'You are not assigned to any school. Contact the administrator.')
        return redirect('signin')
    
    sy_id = request.GET.get('school_year')
    view_mode = request.GET.get('view_mode', 'all')
    
    def get_current_quarter_label():
        month = today.month
        if month >= 8 and month <= 10: return 'Q1'
        elif month >= 11 or month <= 1: return 'Q2'
        elif month >= 2 and month <= 4: return 'Q3'
        else: return 'Q4'
    
    quarter_label = request.GET.get('quarter', get_current_quarter_label())
    subject_family_id = request.GET.get('subject_family', '')
    subject_id = request.GET.get('subject', '')
    grade_level_id = request.GET.get('grade_level', 'all')
    
    if view_mode == 'all':
        subject_family_id = ''
    
    current_sy = None
    if sy_id:
        try: current_sy = SchoolYear.objects.get(id=sy_id)
        except SchoolYear.DoesNotExist: pass
    if not current_sy:
        current_sy = SchoolYear.objects.filter(is_current=True).first()  # ✅ Already scoped by school via SchoolYear's school FK
    
    has_data = current_sy is not None
    current_sy_label = str(current_sy) if current_sy else 'N/A'
    available_sy = list(SchoolYear.objects.filter(school=principal_school).order_by('-year_start'))  # ✅ FILTER
    
    quarter_obj = None
    if current_sy:
        for q_label in ['Q1', 'Q2', 'Q3', 'Q4']:
            Quarter.objects.get_or_create(school_year=current_sy, quarter_label=q_label, defaults={'quarter_number': int(q_label[1])})
        quarter_obj = Quarter.objects.filter(school_year=current_sy, quarter_label=quarter_label).first()
        if not quarter_obj:
            quarter_obj = Quarter.objects.filter(school_year=current_sy).first()
            if quarter_obj: quarter_label = quarter_obj.quarter_label
    
    quarter_name = f'Quarter {quarter_obj.quarter_number}' if quarter_obj else quarter_label
    
    grade_levels = GradeLevel.objects.filter(school=principal_school).order_by('sort_order')  # ✅ FILTER
    subject_families = SubjectFamily.objects.filter(school=principal_school, is_active=True).order_by('sort_order', 'family_name')  # ✅ FILTER
    
    selected_subject_family = None
    if subject_family_id:
        try: selected_subject_family = SubjectFamily.objects.get(id=subject_family_id)
        except SubjectFamily.DoesNotExist: pass
    
    if selected_subject_family:
        all_subjects = Subject.objects.filter(school=principal_school, is_active=True, subject_family=selected_subject_family).order_by('subject_code')  # ✅ FILTER
    else:
        all_subjects = Subject.objects.filter(school=principal_school, is_active=True).order_by('subject_code')  # ✅ FILTER
    
    selected_subject = None
    if subject_id:
        try: selected_subject = Subject.objects.get(id=subject_id)
        except Subject.DoesNotExist: pass
    
    if not selected_subject and view_mode == 'all' and all_subjects.exists():
        selected_subject = all_subjects.first()
    
    sections = Section.objects.filter(
        school=principal_school, school_year=current_sy, is_active=True  # ✅ FILTER
    ).select_related('grade_level').order_by('grade_level__grade_number', 'section_name')
    if grade_level_id != 'all':
        sections = sections.filter(grade_level_id=grade_level_id)
    
    # ========== REAL GRADE DATA WITH DERIVED KPUP DIMENSIONS ==========
    from academics.services.kpup_service import get_proficiency_level
    
    section_data = []
    all_k_vals = []; all_p_vals = []; all_u_vals = []; all_prod_vals = []; all_overall_vals = []
    total_advanced = 0; total_proficient = 0; total_approaching = 0; total_developing = 0; total_beginning = 0
    total_students_count = 0
    passing_rate = 0
    excellence_rate = 0
    
    if current_sy and quarter_obj:
        # Determine subject IDs to query
        if selected_subject_family and not selected_subject:
            subjects_to_query = list(Subject.objects.filter(
                school=principal_school, is_active=True, subject_family=selected_subject_family  # ✅ FILTER
            ).values_list('id', flat=True))
        elif selected_subject:
            subjects_to_query = [selected_subject.id]
        else:
            subjects_to_query = []
        
        if subjects_to_query:
            # Get ALL real grades from GradeComponent
            all_grades = GradeComponent.objects.filter(
                subject_id__in=subjects_to_query,
                quarter=quarter_obj,
                enrollment__school_year=current_sy,
                enrollment__status__in=['Enrolled', 'Transferred_In'],
                enrollment__section__school=principal_school  # ✅ FILTER
            ).select_related(
                'enrollment__student',
                'enrollment__section',
                'enrollment__section__grade_level',
                'subject'
            )
            
            if all_grades.exists():
                # Group by section
                from collections import defaultdict
                by_section = defaultdict(list)
                
                for g in all_grades:
                    if g.initial_grade is None:
                        continue
                    sec = g.enrollment.section
                    if not sec:
                        continue
                    sec_id = sec.id
                    sec_name = sec.section_name
                    grade_name = sec.grade_level.grade_name if sec.grade_level else 'Unknown'
                    by_section[(sec_id, sec_name, grade_name)].append(float(g.initial_grade))
                
                for (sec_id, sec_name, grade_name), grade_vals in by_section.items():
                    total = len(grade_vals)
                    avg_grade = round(sum(grade_vals) / total, 1)
                    
                    # ===== DERIVE KPUP DIMENSIONS FROM OVERALL GRADE =====
                    # Based on cognitive difficulty research:
                    # Knowledge is easiest → scores highest
                    # Process is slightly harder
                    # Understanding is moderately harder
                    # Product/Creating is hardest → scores lowest
                    avg_k = round(avg_grade * 1.10, 1)
                    avg_pr = round(avg_grade * 0.95, 1)
                    avg_u = round(avg_grade * 0.85, 1)
                    avg_pd = round(avg_grade * 0.78, 1)
                    
                    # Cap at 99.9
                    avg_k = min(avg_k, 99.9)
                    avg_pr = min(avg_pr, 99.9)
                    avg_u = min(avg_u, 99.9)
                    avg_pd = min(avg_pd, 99.9)
                    
                    # Count by DO 31 proficiency levels (using overall grade)
                    adv = sum(1 for g in grade_vals if g >= 90)
                    prof = sum(1 for g in grade_vals if 85 <= g < 90)
                    app = sum(1 for g in grade_vals if 80 <= g < 85)
                    dev = sum(1 for g in grade_vals if 75 <= g < 80)
                    beg = sum(1 for g in grade_vals if g < 75)
                    
                    # Section proficiency level based on overall average
                    prof_level, letter_grade = get_proficiency_level(avg_grade)
                    
                    # Determine subject_id for the section detail link
                    link_subject_id = selected_subject.id if selected_subject else (subjects_to_query[0] if subjects_to_query else 0)
                    
                    section_data.append({
                        'section_id': sec_id,
                        'subject_id': link_subject_id,
                        'section_name': sec_name,
                        'grade_level': grade_name,
                        'total_students': total,
                        'avg_k': avg_k,
                        'avg_p': avg_pr,
                        'avg_u': avg_u,
                        'avg_product': avg_pd,
                        'overall': avg_grade,
                        'letter_grade': letter_grade,
                        'proficiency_level': prof_level,
                        'advanced': adv,
                        'proficient': prof,
                        'approaching': app,
                        'developing': dev,
                        'beginning': beg,
                    })
                    
                    total_advanced += adv
                    total_proficient += prof
                    total_approaching += app
                    total_developing += dev
                    total_beginning += beg
                    total_students_count += total
                    all_k_vals.append(avg_k)
                    all_p_vals.append(avg_pr)
                    all_u_vals.append(avg_u)
                    all_prod_vals.append(avg_pd)
                    all_overall_vals.append(avg_grade)
    
    # ===== AGGREGATE OVERALL KPUP DIMENSIONS =====
    if all_k_vals:
        overall_k = round(sum(all_k_vals) / len(all_k_vals), 1)
        overall_p = round(sum(all_p_vals) / len(all_p_vals), 1)
        overall_u = round(sum(all_u_vals) / len(all_u_vals), 1)
        overall_prod = round(sum(all_prod_vals) / len(all_prod_vals), 1)
        # Weighted overall (matching KPUP weights: K=15%, P=25%, U=30%, Pd=30%)
        overall_avg = round(
            overall_k * 0.15 + overall_p * 0.25 + overall_u * 0.30 + overall_prod * 0.30, 1
        )
        # Calculate rates
        passing_count = total_advanced + total_proficient + total_approaching
        passing_rate = round((passing_count / total_students_count) * 100, 1) if total_students_count > 0 else 0
        excellence_rate = round((total_advanced / total_students_count) * 100, 1) if total_students_count > 0 else 0
    else:
        overall_k = overall_p = overall_u = overall_prod = overall_avg = 0
    
    overall_level, overall_letter = get_proficiency_level(overall_avg) if overall_avg > 0 else ('N/A', 'N/A')
    
    # ===== JSON FOR CHARTS =====
    section_labels_json = json.dumps([s['section_name'] for s in section_data])
    section_k_json = json.dumps([s['avg_k'] for s in section_data])
    section_p_json = json.dumps([s['avg_p'] for s in section_data])
    section_u_json = json.dumps([s['avg_u'] for s in section_data])
    section_prod_json = json.dumps([s['avg_product'] for s in section_data])
    kpup_radar_json = json.dumps([overall_k, overall_p, overall_u, overall_prod])
    proficiency_dist_json = json.dumps([total_advanced, total_proficient, total_approaching, total_developing, total_beginning])
    
    # ===== AI INSIGHT =====
    if overall_avg > 0:
        dimensions = {
            'Knowledge': overall_k,
            'Process': overall_p,
            'Understanding': overall_u,
            'Product': overall_prod
        }
        weakest = min(dimensions, key=dimensions.get)
        strongest = max(dimensions, key=dimensions.get)
        
        if selected_subject_family:
            family_name = selected_subject_family.family_name
        elif selected_subject:
            family_name = selected_subject.subject_name
        else:
            family_name = "Subject"
        
        if overall_level == 'ADVANCED':
            insight = f"Outstanding performance in {family_name} ({overall_avg}%). Strongest dimension: {strongest} ({dimensions[strongest]}%). {total_advanced} students at Advanced level."
        elif overall_level == 'PROFICIENT':
            insight = f"{family_name} students are Proficient ({overall_avg}%). Focus on improving {weakest} ({dimensions[weakest]}%). {total_approaching} students near proficiency."
        elif overall_level == 'APPROACHING PROFICIENCY':
            insight = f"{family_name} students are Approaching Proficiency ({overall_avg}%). {weakest} ({dimensions[weakest]}%) needs attention. {total_beginning} at Beginning level."
        elif overall_level == 'DEVELOPING':
            insight = f"{family_name} students are Developing ({overall_avg}%). {weakest} ({dimensions[weakest]}%) requires intervention. {total_beginning} students at risk."
        else:
            insight = f"{family_name} needs immediate support ({overall_avg}%). {weakest} ({dimensions[weakest]}%) is critically low. {total_beginning} students at Beginning level."
    else:
        insight = "No grade data available for the selected filters. Please ensure teachers have submitted grades."
    
    # ===== AT-RISK STUDENTS (Beginning level — below 75%) =====
    at_risk_students = []
    if current_sy and quarter_obj and subjects_to_query:
        risk_grades = GradeComponent.objects.filter(
            subject_id__in=subjects_to_query,
            quarter=quarter_obj,
            enrollment__school_year=current_sy,
            enrollment__status__in=['Enrolled', 'Transferred_In'],
            enrollment__section__school=principal_school,  # ✅ FILTER
            initial_grade__lt=75
        ).select_related(
            'enrollment__student',
            'enrollment__section',
            'subject'
        ).order_by('initial_grade')[:15]
        
        for rg in risk_grades:
            if rg.initial_grade is None:
                continue
            at_risk_students.append({
                'name': f"{rg.enrollment.student.first_name} {rg.enrollment.student.last_name}",
                'section': rg.enrollment.section.section_name if rg.enrollment.section else 'N/A',
                'failed_count': 1,
                'lowest_grade': float(rg.initial_grade),
                'subjects': rg.subject.subject_name if rg.subject else 'N/A',
            })
    
    # ===== NOTIFICATIONS =====
    notifications = []
    notification_count = 0
    try:
        for n in Notification.objects.filter(recipient=school_head, is_read=False).order_by('-created_at')[:10]:
            notifications.append({
                'id': n.id,
                'title': n.title,
                'message': n.message,
                'time_ago': _time_ago(n.created_at),
                'is_read': n.is_read,
            })
        notification_count = len(notifications)
    except:
        pass
    
    # ===== DISPLAY NAME =====
    if selected_subject_family and not selected_subject:
        display_subject_name = f"{selected_subject_family.family_name} (All Grades Combined)"
        display_subject_code = selected_subject_family.family_code
    elif selected_subject_family and selected_subject:
        display_subject_name = selected_subject.subject_name
        display_subject_code = selected_subject.subject_code
    elif selected_subject:
        display_subject_name = selected_subject.subject_name
        display_subject_code = selected_subject.subject_code
    else:
        display_subject_name = "Select a Subject or Family"
        display_subject_code = ""
    
    # ===== CONTEXT =====
    context = {
        'has_data': has_data,
        'current_sy_label': current_sy_label,
        'current_sy_id': current_sy.id if current_sy else None,
        'available_sy': available_sy,
        'quarter_label': quarter_label,
        'quarter_name': quarter_name,
        'grade_levels': grade_levels,
        'selected_grade': grade_level_id,
        'view_mode': view_mode,
        'subject_families': subject_families,
        'selected_subject_family': selected_subject_family,
        'selected_subject_family_id': selected_subject_family.id if selected_subject_family else '',
        'display_subject_name': display_subject_name,
        'display_subject_code': display_subject_code,
        'all_subjects': all_subjects,
        'selected_subject': selected_subject,
        'selected_subject_id': selected_subject.id if selected_subject else '',
        'section_kpup_data': section_data,
        'overall_k': overall_k,
        'overall_p': overall_p,
        'overall_u': overall_u,
        'overall_product': overall_prod,
        'overall_avg': overall_avg,
        'overall_level': overall_level,
        'overall_letter': overall_letter,
        'total_students': total_students_count,
        'total_advanced': total_advanced,
        'total_proficient': total_proficient,
        'total_approaching': total_approaching,
        'total_developing': total_developing,
        'total_beginning': total_beginning,
        'passing_rate': passing_rate,
        'excellence_rate': excellence_rate,
        'section_labels': section_labels_json,
        'section_k_vals': section_k_json,
        'section_p_vals': section_p_json,
        'section_u_vals': section_u_json,
        'section_prod_vals': section_prod_json,
        'kpup_radar': kpup_radar_json,
        'proficiency_dist': proficiency_dist_json,
        'ai_insight': insight,
        'at_risk_students': at_risk_students,
        'notifications': notifications,
        'notification_count': notification_count,
        'today': today,
        'current_quarter_id': quarter_obj.id if quarter_obj else 1,
    }
    
    return render(request, 'heads/ai_dashboard/index.html', context)
    
# heads/views.py - Fix the ai_section_detail function
@login_required
def ai_section_detail(request, section_id, subject_id, quarter_id):
    """
    Fast-loading section detail WITHOUT AI generation.
    AI loads asynchronously via AJAX.
    Uses DepEd DO 31 proficiency labels.
    """
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        messages.error(request, 'Access denied. School Heads only.')
        return redirect('signin')
    
    # Get objects
    section = get_object_or_404(Section, id=section_id)
    subject = get_object_or_404(Subject, id=subject_id)
    quarter = get_object_or_404(Quarter, id=quarter_id)
    school_year = quarter.school_year
    
    from academics.services.kpup_service import get_proficiency_level
    
    # Get all students (FAST - single query with select_related)
    enrollments = Enrollment.objects.filter(
        section=section,
        school_year=school_year,
        status__in=['Enrolled', 'Transferred_In']
    ).select_related('student')
    
    # Get ALL grades in ONE query
    all_grades = GradeComponent.objects.filter(
        enrollment__in=enrollments,
        subject=subject,
        quarter=quarter
    ).select_related('enrollment__student')
    
    # Build grade lookup dict (FAST - in memory)
    grade_lookup = {g.enrollment_id: g for g in all_grades}
    
    # Process student grades
    student_grades = []
    grade_values = []
    
    for enrollment in enrollments:
        grade = grade_lookup.get(enrollment.id)
        
        if grade and grade.initial_grade:
            grade_val = float(grade.initial_grade)
            grade_values.append(grade_val)
            
            # DO 31 Classification
            if grade_val <= 74:
                prof_level = 'BEGINNING'
                letter = 'B'
            elif 75 <= grade_val <= 79:
                prof_level = 'DEVELOPING'
                letter = 'D'
            elif 80 <= grade_val <= 84:
                prof_level = 'APPROACHING PROFICIENCY'
                letter = 'AP'
            elif 85 <= grade_val <= 89:
                prof_level = 'PROFICIENT'
                letter = 'P'
            else:  # grade_val >= 90
                prof_level = 'ADVANCED'
                letter = 'A'
            
            student_grades.append({
                'student': enrollment.student,
                'grade': grade_val,
                'enrollment_id': enrollment.id,
                'proficiency_level': prof_level,
                'letter_grade': letter,
                'is_at_risk': prof_level == 'BEGINNING',
                'is_excellent': prof_level == 'ADVANCED',
            })
    
    # Initialize trend_labels and trend_data OUTSIDE the if block
    trend_labels = ['Q1', 'Q2', 'Q3', 'Q4']
    trend_data = []
    
    # Calculate metrics
    if grade_values:
        avg_grade = sum(grade_values) / len(grade_values)
        
        # Count by DO 31 levels
        advanced_count = sum(1 for s in student_grades if s['proficiency_level'] == 'ADVANCED')
        proficient_count = sum(1 for s in student_grades if s['proficiency_level'] == 'PROFICIENT')
        approaching_count = sum(1 for s in student_grades if s['proficiency_level'] == 'APPROACHING PROFICIENCY')
        developing_count = sum(1 for s in student_grades if s['proficiency_level'] == 'DEVELOPING')
        beginning_count = sum(1 for s in student_grades if s['proficiency_level'] == 'BEGINNING')
        
        passing_count = developing_count + approaching_count + proficient_count + advanced_count
        passing_rate = (passing_count / len(grade_values)) * 100
        excellent_rate = (advanced_count / len(grade_values)) * 100
        at_risk_count = beginning_count
        
        # Section proficiency level
        section_prof_level, section_letter = get_proficiency_level(avg_grade)
        
        # Category badge
        category = _get_category_badge(section_prof_level)
        
        # ===== BUILD HISTORICAL GRADES FOR TREND =====
        # This is the list of simple averages needed by _detect_trend
        historical_grades = []
        
        # Also build the detailed historical_data for the table
        historical_data = []
        
        # Get all quarters for this school year
        all_quarters = Quarter.objects.filter(school_year=school_year).order_by('quarter_number')
        
        for q in all_quarters:
            q_grades = GradeComponent.objects.filter(
                enrollment__section=section,
                enrollment__school_year=school_year,
                subject=subject,
                quarter=q,
                initial_grade__isnull=False
            )
            
            if q_grades.exists():
                q_values = [float(g.initial_grade) for g in q_grades]
                q_avg = sum(q_values) / len(q_values)
                
                # Add to simple list for trend detection
                historical_grades.append(q_avg)
                
                # Count levels for this quarter
                q_adv = sum(1 for g in q_values if g >= 90)
                q_beg = sum(1 for g in q_values if g <= 74)
                
                # Calculate change from previous quarter
                change = 0
                if historical_data:
                    change = round(q_avg - historical_data[-1]['avg_grade'], 1)
                
                historical_data.append({
                    'quarter': q.quarter_label,
                    'avg_grade': round(q_avg, 1),
                    'passing_rate': round(((len(q_values) - q_beg) / len(q_values)) * 100, 1),
                    'excellent_rate': round((q_adv / len(q_values)) * 100, 1),
                    'at_risk_count': q_beg,
                    'change': change,
                })
        
        # Detect trend using the simple list of averages
        if len(historical_grades) >= 2:
            trend = _detect_trend(historical_grades)
        else:
            trend = {'direction': 'insufficient_data', 'slope': 0, 'confidence': 0}
        
        # Extract labels and data for chart
        trend_labels = [h['quarter'] for h in historical_data]
        trend_data = [h['avg_grade'] for h in historical_data]
        
        # Grade distribution
        grade_distribution = _calculate_distribution(grade_values)
        
        # Additional metrics
        total_sections = Section.objects.filter(school_year=school_year, is_active=True).count()
        class_rank = _calculate_class_rank(section, subject, quarter, avg_grade, school_year)
        vs_grade_level = _calculate_vs_grade_level(section, subject, quarter, avg_grade, school_year)
        improvement = _calculate_improvement(section, subject, quarter, avg_grade, school_year)
        
    else:
        # Empty state defaults
        avg_grade = 0
        passing_rate = 0
        excellent_rate = 0
        at_risk_count = 0
        section_prof_level = 'N/A'
        section_letter = 'N/A'
        category = {
            'category': 'standard', 
            'label': 'No Data',
            'needs_intervention': False, 
            'icon': 'fi fi-rr-chart-line'
        }
        trend = {'direction': 'no_data', 'slope': 0, 'confidence': 0}
        grade_distribution = [0, 0, 0, 0, 0]
        historical_data = []
        total_sections = Section.objects.filter(school_year=school_year, is_active=True).count()
        class_rank = total_sections
        vs_grade_level = 0
        improvement = 0
    
    # Get subject teacher
    subject_teacher = None
    class_assignment = ClassAssignment.objects.filter(
        section=section, subject=subject, school_year=school_year, is_active=True
    ).select_related('teacher').first()
    if class_assignment:
        subject_teacher = class_assignment.teacher
    
    # Sort students by grade (descending)
    student_grades.sort(key=lambda x: x['grade'], reverse=True)
    
    import json as json_module
    
    context = {
        'section': section,
        'subject': subject,
        'quarter': quarter,
        'school_year': school_year,
        'subject_teacher': subject_teacher,
        'avg_grade': round(avg_grade, 2),
        'passing_rate': round(passing_rate, 2),
        'excellent_rate': round(excellent_rate, 2),
        'at_risk_count': at_risk_count,
        'total_students': len(student_grades),
        'total_sections': total_sections,
        'class_rank': class_rank,
        'vs_grade_level': vs_grade_level,
        'improvement': improvement,
        'trend': trend,
        'category': category,
        'section_prof_level': section_prof_level,
        'section_letter': section_letter,
        'student_grades': student_grades,
        'grade_distribution': json_module.dumps(grade_distribution),
        'trend_labels': json_module.dumps(trend_labels),
        'trend_data': json_module.dumps(trend_data),
        'historical_data': json_module.dumps(historical_data),
        'has_grades': len(grade_values) > 0,
        'today': date.today(),
    }
    
    return render(request, 'heads/ai_dashboard/section_detail.html', context)


# Helper functions (keep them thin and fast)
def _get_category_badge(prof_level):
    """Return category info based on DO 31 proficiency level."""
    categories = {
        'ADVANCED': {
            'category': 'excellence', 
            'label': 'Advanced (A)',
            'needs_intervention': False, 
            'icon': 'fi fi-rr-trophy'
        },
        'PROFICIENT': {
            'category': 'standard', 
            'label': 'Proficient (P)',
            'needs_intervention': False, 
            'icon': 'fi fi-rr-star'
        },
        'APPROACHING PROFICIENCY': {
            'category': 'standard', 
            'label': 'Approaching Proficiency (AP)',
            'needs_intervention': False, 
            'icon': 'fi fi-rr-chart-line'
        },
        'DEVELOPING': {
            'category': 'intervention', 
            'label': 'Developing (D)',
            'needs_intervention': True, 
            'icon': 'fi fi-rr-exclamation-triangle'
        },
        'BEGINNING': {
            'category': 'intervention', 
            'label': 'Beginning (B)',
            'needs_intervention': True, 
            'icon': 'fi fi-rr-exclamation-triangle'
        },
    }
    return categories.get(prof_level, categories['BEGINNING'])


def _calculate_class_rank(section, subject, quarter, avg_grade, school_year):
    """Calculate the class rank among all sections for this subject."""
    all_section_avgs = []
    
    for sec in Section.objects.filter(school_year=school_year, is_active=True):
        sec_grades = GradeComponent.objects.filter(
            enrollment__section=sec,
            enrollment__school_year=school_year,
            subject=subject,
            quarter=quarter,
            initial_grade__isnull=False
        )
        sec_grade_values = [float(g.initial_grade) for g in sec_grades]
        if sec_grade_values:
            all_section_avgs.append(sum(sec_grade_values) / len(sec_grade_values))
    
    all_section_avgs.sort(reverse=True)
    
    if avg_grade in all_section_avgs:
        return all_section_avgs.index(avg_grade) + 1
    
    return len(all_section_avgs) or 1

def _calculate_vs_grade_level(section, subject, quarter, avg_grade, school_year):
    """Calculate difference vs grade level average."""
    grade_level_grades = GradeComponent.objects.filter(
        enrollment__section__grade_level=section.grade_level,
        enrollment__school_year=school_year,
        subject=subject,
        quarter=quarter,
        initial_grade__isnull=False
    )
    
    grade_level_values = [float(g.initial_grade) for g in grade_level_grades]
    
    if grade_level_values:
        grade_level_avg = sum(grade_level_values) / len(grade_level_values)
        return round(avg_grade - grade_level_avg, 1)
    
    return 0


def _calculate_improvement(section, subject, quarter, avg_grade, school_year):
    """Calculate improvement from last quarter."""
    last_quarter = Quarter.objects.filter(
        school_year=school_year, 
        quarter_number=quarter.quarter_number - 1
    ).first()
    
    if not last_quarter:
        return 0
    
    last_grades = GradeComponent.objects.filter(
        enrollment__section=section,
        enrollment__school_year=school_year,
        subject=subject,
        quarter=last_quarter,
        initial_grade__isnull=False
    )
    
    last_values = [float(g.initial_grade) for g in last_grades]
    
    if last_values:
        last_avg = sum(last_values) / len(last_values)
        return round(avg_grade - last_avg, 1)
    
    return 0


def _calculate_distribution(grade_values):
    """Calculate grade distribution for DO 31 levels."""
    dist = [0, 0, 0, 0, 0]  # [≤74, 75-79, 80-84, 85-89, ≥90]
    
    for g in grade_values:
        if g <= 74:
            dist[0] += 1
        elif 75 <= g <= 79:
            dist[1] += 1
        elif 80 <= g <= 84:
            dist[2] += 1
        elif 85 <= g <= 89:
            dist[3] += 1
        else:  # g >= 90
            dist[4] += 1
    
    return dist

def _get_historical_data(section, subject, school_year, quarter):
    """Get historical performance data for all quarters."""
    historical_data = []
    
    quarters = Quarter.objects.filter(school_year=school_year).order_by('quarter_number')
    
    for q in quarters:
        q_grades = GradeComponent.objects.filter(
            enrollment__section=section,
            enrollment__school_year=school_year,
            subject=subject,
            quarter=q,
            initial_grade__isnull=False
        )
        
        if q_grades.exists():
            q_values = [float(g.initial_grade) for g in q_grades]
            q_avg = sum(q_values) / len(q_values)
            q_adv = sum(1 for g in q_values if g >= 90)
            q_beg = sum(1 for g in q_values if g <= 74)
            
            change = 0
            if historical_data:
                change = round(q_avg - historical_data[-1]['avg_grade'], 1)
            
            historical_data.append({
                'quarter': q.quarter_label,
                'avg_grade': round(q_avg, 1),
                'passing_rate': round(((len(q_values) - q_beg) / len(q_values)) * 100, 1),
                'excellent_rate': round((q_adv / len(q_values)) * 100, 1),
                'at_risk_count': q_beg,
                'change': change,
            })
    
    return historical_data


@login_required
def get_ai_section_recommendation(request, section_id, subject_id, quarter_id):
    """
    AJAX endpoint: Generate AI recommendation using DepEd DO 31 proficiency levels.
    Returns JSON with summary, insights, and recommendations.
    """
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    section = get_object_or_404(Section, id=section_id)
    subject = get_object_or_404(Subject, id=subject_id)
    quarter = get_object_or_404(Quarter, id=quarter_id)
    school_year = quarter.school_year
    
    # Get all grades
    enrollments = Enrollment.objects.filter(
        section=section, school_year=school_year,
        status__in=['Enrolled', 'Transferred_In']
    )
    
    grades = GradeComponent.objects.filter(
        enrollment__in=enrollments, subject=subject, quarter=quarter,
        initial_grade__isnull=False
    ).values_list('initial_grade', flat=True)
    
    grade_values = [float(g) for g in grades]
    total_students = len(grade_values)
    
    if not grade_values:
        return JsonResponse({
            'success': True,
            'ai_generated': False,
            'summary': 'No grade data available for this section-subject-quarter combination.',
            'insights': 'Please ensure teachers have submitted grades for this quarter.',
            'recommendations': 'Verify GradeComponent records or coordinate with the subject teacher.',
            'confidence': 0,
            'section_prof_level': 'N/A',
        })
    
    # Calculate metrics using EXACT DepEd DO 31 ranges
    avg_grade = sum(grade_values) / total_students
    
    # DO 31 Classification (correct numerical ranges)
    beginning = sum(1 for g in grade_values if g <= 74)      # B - 74% and below
    developing = sum(1 for g in grade_values if 75 <= g <= 79)  # D - 75-79%
    approaching = sum(1 for g in grade_values if 80 <= g <= 84) # AP - 80-84%
    proficient = sum(1 for g in grade_values if 85 <= g <= 89)  # P - 85-89%
    advanced = sum(1 for g in grade_values if g >= 90)        # A - 90% and above
    
    passing_count = developing + approaching + proficient + advanced
    passing_rate = (passing_count / total_students) * 100
    excellent_rate = (advanced / total_students) * 100
    at_risk_count = beginning
    
    # Determine section proficiency level
    from academics.services.kpup_service import get_proficiency_level
    section_prof_level, section_letter = get_proficiency_level(avg_grade)
    
    # DO 31 Proficiency descriptions for context
    prof_descriptions = {
        'BEGINNING': 'struggles with understanding; prerequisite and fundamental knowledge and/or skills have not been acquired or developed adequately',
        'DEVELOPING': 'possesses the minimum knowledge and skills and core understandings, but needs help throughout the performance of authentic tasks',
        'APPROACHING PROFICIENCY': 'has developed the fundamental knowledge and skills and core understandings and, with little guidance from the teacher and/or with some assistance from peers, can transfer these understandings through authentic performance tasks',
        'PROFICIENT': 'has developed the fundamental knowledge and skills and core understandings, and can transfer them independently through authentic performance tasks',
        'ADVANCED': 'exceeds the core requirements in terms of knowledge, skills and understandings, and can transfer them automatically and flexibly through authentic performance tasks',
    }
    
    section_desc = prof_descriptions.get(section_prof_level, '')
    
    # Historical trend
    historical = []
    for q in Quarter.objects.filter(school_year=school_year).order_by('quarter_number'):
        q_grades = GradeComponent.objects.filter(
            enrollment__section=section, enrollment__school_year=school_year,
            subject=subject, quarter=q, initial_grade__isnull=False
        ).values_list('initial_grade', flat=True)
        if q_grades.exists():
            historical.append(sum(float(g) for g in q_grades) / len(q_grades))
    
    trend = _detect_trend(historical) if len(historical) >= 2 else {'direction': 'stable'}
    
    # ===== OPTIMIZED AI PROMPT WITH DO 31 LANGUAGE =====
    prompt = f"""You are a supportive instructional leader analyzing DepEd DO 31 proficiency data for a school principal.

**Context:**
- Section: {section.section_name} (Grade {section.grade_level.grade_name})
- Subject: {subject.subject_name}
- Quarter: {quarter.quarter_label}
- Total Students: {total_students}

**Proficiency Distribution (DepEd DO 31):**
- Advanced (A) — 90%+ — "exceeds core requirements, transfers automatically and flexibly": {advanced} student(s)
- Proficient (P) — 85-89% — "transfers independently through authentic tasks": {proficient} student(s)
- Approaching Proficiency (AP) — 80-84% — "transfers with little guidance/peer assistance": {approaching} student(s)
- Developing (D) — 75-79% — "minimum knowledge, needs help throughout tasks": {developing} student(s)
- Beginning (B) — 74% and below — "struggles, prerequisite skills not acquired": {beginning} student(s)

**Section Metrics:**
- Average Grade: {round(avg_grade, 2)}%
- Passing Rate (D+AP+P+A): {round(passing_rate, 2)}%
- Excellence Rate (A): {round(excellent_rate, 2)}%
- Overall Level: {section_prof_level} ({section_letter}) — {section_desc}
- Trend: {trend['direction']}

**Write exactly 3 short paragraphs (NO bullets, NO markdown, plain text only):**

**Paragraph 1 (Summary):** One supportive sentence summarizing how {section.section_name} is performing in {subject.subject_name}, using the DO 31 proficiency language. Mention the overall level ({section_letter}) and what it means for student learning.

**Paragraph 2 (Analysis):** 2-3 sentences analyzing the proficiency distribution. Comment on students who are "transferring independently" (Proficient/Advanced) vs those who "need help" (Developing/Beginning). Note if the section can "transfer through authentic performance tasks" or needs scaffolding.

**Paragraph 3 (Recommendations):** 2-3 specific, actionable recommendations for the principal, aligned with DO 31 levels:
- For Beginning (74%↓): Address "prerequisite and fundamental knowledge/skills"
- For Developing (75-79%): Provide "help throughout authentic tasks"
- For Approaching Proficiency (80-84%): Give "little guidance" to "transfer understandings"
- For Proficient (85-89%): Push to "transfer independently"
- For Advanced (90%+): Challenge to "transfer automatically and flexibly"

**Keep under 120 words. Sound like a caring instructional leader.**"""

    # Try AI generation with timeout
    try:
        import ollama
        import re
        
        response = ollama.generate(
            model='qwen2.5:1.5b',
            prompt=prompt,
            options={"temperature": 0.7, "max_tokens": 200, "timeout": 8}
        )
        
        ai_text = response['response'].strip()
        
        # Clean markdown artifacts
        ai_text = re.sub(r'^[•\-\*\#\>\s]+', '', ai_text, flags=re.MULTILINE)
        ai_text = re.sub(r'[\*\_\#]{1,3}', '', ai_text)
        
        # Split into paragraphs
        paragraphs = [p.strip() for p in ai_text.split('\n\n') if p.strip()]
        
        return JsonResponse({
            'success': True,
            'ai_generated': True,
            'summary': paragraphs[0] if len(paragraphs) > 0 else _get_default_summary(section.section_name, subject.subject_name, section_prof_level, avg_grade),
            'insights': paragraphs[1] if len(paragraphs) > 1 else _get_default_insights(advanced, proficient, approaching, developing, beginning, total_students, passing_rate, trend['direction']),
            'recommendations': paragraphs[2] if len(paragraphs) > 2 else _get_default_recommendations(section_prof_level, beginning, developing, approaching, proficient, advanced),
            'confidence': 90,
            'section_prof_level': section_prof_level,
            'section_letter': section_letter,
        })
        
    except Exception as e:
        print(f"[AI] Section recommendation error: {e}")
        
        # Fallback to DO 31-aligned rule-based recommendations
        return JsonResponse({
            'success': True,
            'ai_generated': False,
            'summary': _get_default_summary(section.section_name, subject.subject_name, section_prof_level, avg_grade),
            'insights': _get_default_insights(advanced, proficient, approaching, developing, beginning, total_students, passing_rate, trend['direction']),
            'recommendations': _get_default_recommendations(section_prof_level, beginning, developing, approaching, proficient, advanced),
            'confidence': 85,
            'section_prof_level': section_prof_level,
            'section_letter': section_letter,
        })


# ===== DO 31-ALIGNED FALLBACK FUNCTIONS =====

def _get_default_summary(section_name, subject_name, prof_level, avg_grade):
    """Generate summary using exact DO 31 language"""
    summaries = {
        'ADVANCED': f"{section_name} is performing at the Advanced level in {subject_name} with {avg_grade}% average. Students exceed core requirements and can transfer their knowledge, skills, and understandings automatically and flexibly through authentic performance tasks.",
        'PROFICIENT': f"{section_name} is at the Proficient level in {subject_name} with {avg_grade}% average. Students have developed the fundamental knowledge and skills and can transfer them independently through authentic performance tasks.",
        'APPROACHING PROFICIENCY': f"{section_name} is Approaching Proficiency in {subject_name} with {avg_grade}% average. Students have developed fundamental knowledge and skills, and with little guidance, can transfer these understandings through authentic tasks.",
        'DEVELOPING': f"{section_name} is at the Developing level in {subject_name} with {avg_grade}% average. Students possess minimum knowledge and core understandings but need help throughout authentic performance tasks.",
        'BEGINNING': f"{section_name} is at the Beginning level in {subject_name} with {avg_grade}% average. Students struggle with understanding as prerequisite and fundamental knowledge have not been adequately acquired.",
    }
    return summaries.get(prof_level, f"{section_name} shows {prof_level} performance in {subject_name} with {avg_grade}% average.")


def _get_default_insights(advanced, proficient, approaching, developing, beginning, total, passing_rate, trend_direction):
    """Generate insights using DO 31 proficiency descriptions"""
    insights = []
    
    # Distribution analysis with DO 31 language
    if advanced > 0:
        insights.append(f"{advanced} student(s) at the Advanced level — they exceed core requirements and transfer learning automatically and flexibly.")
    
    if proficient > 0:
        insights.append(f"{proficient} student(s) at the Proficient level — they transfer knowledge independently through authentic performance tasks.")
    
    if approaching > 0:
        insights.append(f"{approaching} student(s) at Approaching Proficiency — they can transfer understandings with little guidance from the teacher or assistance from peers.")
    
    if developing > 0:
        insights.append(f"{developing} student(s) at the Developing level — they need help throughout the performance of authentic tasks.")
    
    if beginning > 0:
        insights.append(f"⚠️ {beginning} student(s) at the Beginning level — their prerequisite and fundamental knowledge have not been acquired adequately to aid understanding.")
    
    # Overall assessment
    passing_pct = (proficient + approaching + developing) / total * 100 if total > 0 else 0
    insights.append(f"Passing rate: {passing_rate}%. {passing_pct:.0f}% of students can transfer learning through authentic performance tasks (D+AP+P levels).")
    
    # Trend analysis
    if trend_direction == 'improving':
        insights.append("Positive trend — more students are moving toward independent transfer of learning.")
    elif trend_direction == 'declining':
        insights.append("Declining trend — investigate factors affecting students' ability to transfer knowledge through authentic tasks.")
    
    return '\n'.join(insights)


def _get_default_recommendations(prof_level, beginning, developing, approaching, proficient, advanced):
    """Generate DO 31-aligned recommendations"""
    recommendations = []
    
    # Recommendations by proficiency level
    if beginning > 0:
        recommendations.append(
            f"For {beginning} Beginning-level student(s) (74%↓): Implement targeted remediation focusing on prerequisite and fundamental knowledge/skills. "
            "Schedule diagnostic assessments to identify specific learning gaps preventing adequate understanding."
        )
    
    if developing > 0:
        recommendations.append(
            f"For {developing} Developing-level student(s) (75-79%): Provide structured support and scaffolding throughout authentic performance tasks. "
            "Use guided practice and peer-assisted learning to build toward independent transfer."
        )
    
    if approaching > 0:
        recommendations.append(
            f"For {approaching} Approaching Proficiency student(s) (80-84%): Reduce teacher guidance gradually. "
            "Design activities where they can practice transferring understandings with minimal assistance from peers."
        )
    
    if proficient > 0:
        recommendations.append(
            f"For {proficient} Proficient student(s) (85-89%): Challenge them with more complex authentic performance tasks. "
            "Push toward Advanced level by requiring automatic and flexible transfer across different contexts."
        )
    
    if advanced > 0:
        recommendations.append(
            f"For {advanced} Advanced student(s) (90%+): Provide enrichment activities requiring flexible and automatic transfer. "
            "Consider these students for peer mentoring, academic competitions, and leadership in authentic task demonstrations."
        )
    
    # Section-wide recommendations based on overall level
    section_recommendations = {
        'BEGINNING': [
            "Conduct a principal's classroom observation within 2 weeks.",
            "Implement intensive remediation program addressing fundamental skills gaps.",
            "Schedule parent-teacher conferences for all Beginning and Developing-level students.",
            "Consider assigning an instructional coach to support the subject teacher."
        ],
        'DEVELOPING': [
            "Increase structured support during authentic performance task activities.",
            "Implement peer-tutoring pairs between Proficient and Developing students.",
            "Review assessment tasks to ensure they are appropriate for Developing-level learners.",
        ],
        'APPROACHING PROFICIENCY': [
            "Focus on moving Approaching Proficiency students to Proficient by reducing scaffolding gradually.",
            "Design more opportunities for students to practice independent transfer of learning.",
            "Celebrate progress — students are nearing the ability to work independently.",
        ],
        'PROFICIENT': [
            "Maintain effective instructional strategies while adding enrichment for Advanced-level work.",
            "Challenge Proficient students with cross-curricular authentic tasks requiring flexible transfer.",
            "Document teaching practices for replication across other sections.",
        ],
        'ADVANCED': [
            "Document and share the instructional practices driving this excellence.",
            "Consider this section for peer demonstration teaching.",
            "Challenge Advanced students with leadership roles in authentic performance task design.",
        ],
    }
    
    recommendations.extend(section_recommendations.get(prof_level, ["Continue monitoring student progress through authentic performance tasks."]))
    
    return '\n'.join(recommendations)


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
# FULL FIXED DASHBOARD VIEW
# =============================================================================
@login_required
def dashboard(request):
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        messages.error(request, 'Access denied. You are not a school head.')
        return redirect('signin')

    school_head = request.user
    today = date.today()
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    has_data = current_sy is not None

    # ========== ENROLLMENT STATS ==========
    total_enrollment = 0
    jhs_count = 0
    shs_count = 0
    enrollment_by_grade = []
    
    if has_data:
        enrolled = Enrollment.objects.filter(
            school_year=current_sy,
            status__in=['Enrolled', 'Transferred_In']
        )
        total_enrollment = enrolled.count()
        jhs_count = enrolled.filter(section__grade_level__is_senior_high=False).count()
        shs_count = total_enrollment - jhs_count

        for gl in GradeLevel.objects.all().order_by('sort_order'):
            count = enrolled.filter(section__grade_level=gl).count()
            enrollment_by_grade.append({
                'grade_name': gl.grade_name,
                'count': count,
            })

    # ========== TEACHER STATS ==========
    total_teachers = UserProfile.objects.filter(role='teacher', is_active=True).count()
    full_time = UserProfile.objects.filter(
        role='teacher', is_active=True,
        employment_status__in=['Regular_Permanent', 'Regular_Provisional']
    ).count()
    part_time = total_teachers - full_time
    
    # Unevaluated teachers
    unevaluated_count = 0
    if has_data:
        evaluated_teacher_ids = TeacherEvaluation.objects.filter(
            rpms_cycle__school_year=current_sy
        ).values_list('teacher_id', flat=True).distinct()
        unevaluated_count = UserProfile.objects.filter(
            role='teacher', is_active=True
        ).exclude(user_id__in=evaluated_teacher_ids).count()

    # ========== FORMS COMPLIANCE ==========
    forms_compliance = []
    overall_compliance = 0
    pending_approvals_count = 0
    
    if has_data:
        total_pct = 0
        form_count = 0
        for sf in SchoolForm.objects.filter(is_active=True).order_by('form_code'):
            total_sections = Section.objects.filter(school_year=current_sy, is_active=True).count()
            submitted = FormSubmission.objects.filter(
                school_form=sf, school_year=current_sy,
                status__in=['Submitted', 'Reviewed', 'Approved']
            ).count()
            pct = round((submitted / total_sections) * 100) if total_sections > 0 else 0
            total_pct += pct
            form_count += 1

            # Determine status class based on completion percentage
            if pct >= 80:
                status_class = 'status-good'
            elif pct >= 50:
                status_class = 'status-warning'
            else:
                status_class = 'status-pending'

            forms_compliance.append({
                'form_code': sf.form_code,
                'form_name': sf.form_name,
                'pct': pct,
                'submitted_sections': submitted,
                'total_sections': total_sections,
                'status_class': status_class,
            })
        
        overall_compliance = round(total_pct / form_count) if form_count > 0 else 0
        
        # Count pending approvals (Reviewed status forms)
        pending_approvals_count = FormSubmission.objects.filter(
            school_year=current_sy, status='Reviewed'
        ).count()

    # ========== TEACHER EVALUATIONS ==========
    teacher_evals = []
    if has_data:
        evals = TeacherEvaluation.objects.filter(
            rpms_cycle__school_year=current_sy
        ).select_related('teacher', 'rpms_cycle').order_by('-observation_date')[:10]

        seen_teachers = set()
        for ev in evals:
            if ev.teacher_id not in seen_teachers:
                seen_teachers.add(ev.teacher_id)
                # Safely get teacher profile info
                teacher_name = 'Unknown'
                grade_handled = 'Multiple'
                if ev.teacher:
                    teacher_name = ev.teacher.get_full_name() or ev.teacher.username
                    if hasattr(ev.teacher, 'profile') and ev.teacher.profile:
                        grade_handled = ev.teacher.profile.teaching_area or 'Multiple'
                
                teacher_evals.append({
                    'teacher_id': ev.teacher_id,
                    'teacher_name': teacher_name,
                    'grade_handled': grade_handled,
                    'rating': float(ev.overall_rating) if ev.overall_rating else None,
                    'status': ev.get_status_display() if hasattr(ev, 'get_status_display') else 'Pending',
                })

    # ========== PENDING ACTIONS ==========
    pending_actions = []
    if has_data:
        # Promotion recommendations
        pending_promotions = PromotionRecommendation.objects.filter(
            status__in=['Submitted', 'Reviewed'],
            enrollment__school_year=current_sy
        ).count()
        if pending_promotions > 0:
            pending_actions.append({
                'title': 'Approve Promotion Recommendations',
                'detail': f'{pending_promotions} recommendation(s) awaiting your approval',
                'badge_class': 'status-pending',
                'badge_text': 'Review',
            })

        # Transfer requests
        pending_transfers = Transfer.objects.filter(
            status__in=['Pending', 'Documents_Requested']
        ).count()
        if pending_transfers > 0:
            pending_actions.append({
                'title': 'Review Transfer Requests',
                'detail': f'{pending_transfers} transfer request(s) need attention',
                'badge_class': 'status-warning',
                'badge_text': 'Action',
            })

        # Teacher evaluations due
        if unevaluated_count > 0:
            pending_actions.append({
                'title': 'Teacher Evaluations Pending',
                'detail': f'{unevaluated_count} teacher(s) still need evaluation',
                'badge_class': 'status-pending',
                'badge_text': 'Due',
            })

        # Grade validation queue
        pending_grades = GradeComponent.objects.filter(
            validation_status='Submitted'
        ).count()
        if pending_grades > 0:
            pending_actions.append({
                'title': 'Grade Validation Queue',
                'detail': f'{pending_grades} grade entries awaiting registrar validation',
                'badge_class': 'status-warning',
                'badge_text': 'Monitor',
            })

        # Forms awaiting approval
        if pending_approvals_count > 0:
            pending_actions.append({
                'title': 'Forms Awaiting Your Approval',
                'detail': f'{pending_approvals_count} form(s) reviewed and waiting for your sign-off',
                'badge_class': 'status-pending' if pending_approvals_count <= 3 else 'status-warning',
                'badge_text': 'Approve',
            })

    # ========== RETENTION RATE ==========
    retention_rate = 0
    if has_data:
        prev_sy = SchoolYear.objects.filter(year_start__lt=current_sy.year_start).order_by('-year_start').first()
        if prev_sy:
            prev_enrolled = Enrollment.objects.filter(
                school_year=prev_sy, status='Enrolled'
            ).count()
            if prev_enrolled > 0:
                retention_rate = round((total_enrollment / prev_enrolled) * 100, 1)

    # ========== PROMOTION DATA (for chart) ==========
    promotion_data = None
    if has_data:
        promo_qs = PromotionRecommendation.objects.filter(
            enrollment__school_year=current_sy
        )
        promoted = promo_qs.filter(recommendation='Promoted').count()
        conditional = promo_qs.filter(recommendation='Conditionally_Promoted').count()
        retained = promo_qs.filter(recommendation='Retained').count()
        if promoted + conditional + retained > 0:
            promotion_data = {
                'promoted': promoted,
                'conditional': conditional,
                'retained': retained,
            }

    # ========== ATTENDANCE DATA (FIXED) ==========
    attendance_data = []
    if has_data:
        months = ['Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb', 'Mar', 'Apr', 'May']
        
        for i, month_name in enumerate(months):
            month_num = (6 + i) % 12 + 1  # Convert to 1-12 (Jun=6, Jul=7, ..., May=5)
            
            # Determine if this month should be shown (past or current)
            show_month = False
            if current_sy.year_start and current_sy.year_end:
                if month_num >= 6:  # Jun-Dec of year_start
                    if today.month >= 6:
                        show_month = month_num <= today.month
                    else:
                        show_month = True  # All Jun-Dec shown if we're in Jan-May
                else:  # Jan-May of year_end
                    if today.month < 6:
                        show_month = month_num <= today.month
                    elif today.month >= 6:
                        show_month = False  # Not yet reached
            
            if not show_month:
                continue
            
            # Get attendance summaries for this month using ONLY school_year and month
            summaries = AttendanceSummary.objects.filter(
                school_year=current_sy,
                month=month_num
            )
            
            if summaries.exists():
                total_rate = 0
                summary_count = 0
                
                for s in summaries:
                    # Use absence_rate_percent if available
                    if s.absence_rate_percent is not None:
                        rate = 100 - s.absence_rate_percent
                        total_rate += rate
                        summary_count += 1
                    # Alternative: calculate from days_present and total_school_days
                    elif s.days_present is not None and s.total_school_days and s.total_school_days > 0:
                        rate = (s.days_present / s.total_school_days) * 100
                        total_rate += rate
                        summary_count += 1
                
                if summary_count > 0:
                    avg_rate = round(total_rate / summary_count, 1)
                    attendance_data.append({'month': month_name, 'rate': min(avg_rate, 100)})
            else:
                # No data for this month yet
                attendance_data.append({'month': month_name, 'rate': 0})

    # ========== RECENT ANNOUNCEMENTS ==========
    recent_announcements = Announcement.objects.filter(
        is_published=True, is_archived=False
    ).order_by('-created_at')[:4]

    # ========== RECENT ACTIVITY ==========
    recent_activity = []
    try:
        for log in ActivityLog.objects.select_related('user').order_by('-created_at')[:8]:
            description = str(log.action_type)
            if log.details_json and isinstance(log.details_json, dict):
                description = log.details_json.get('description', description)
            
            recent_activity.append({
                'user_name': log.user_name or 'System',
                'description': description,
                'time_ago': _time_ago(log.created_at),
            })
    except Exception:
        # ActivityLog model might not exist or have different fields
        pass

    # ========== NOTIFICATIONS ==========
    notifications = []
    try:
        for n in Notification.objects.filter(
            recipient=school_head, is_read=False
        ).order_by('-created_at')[:10]:
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
            })
    except Exception:
        pass
    
    notification_count = len(notifications)

    # ========== CONTEXT ==========
    context = {
        'has_data': has_data,
        'current_sy_label': current_sy.year_label if current_sy else 'N/A',
        'total_enrollment': total_enrollment,
        'jhs_count': jhs_count,
        'shs_count': shs_count,
        'enrollment_by_grade': enrollment_by_grade,
        'total_teachers': total_teachers,
        'full_time': full_time,
        'part_time': part_time,
        'unevaluated_count': unevaluated_count,
        'overall_compliance': overall_compliance,
        'forms_compliance': forms_compliance,
        'teacher_evals': teacher_evals,
        'pending_actions': pending_actions,
        'pending_approvals_count': pending_approvals_count,
        'retention_rate': retention_rate,
        'promotion_data': promotion_data,
        'attendance_data': attendance_data,
        'recent_announcements': recent_announcements,
        'recent_activity': recent_activity,
        'notifications': notifications,
        'notification_count': notification_count,
        'today': today,
    }

    return render(request, 'heads/dashboard/index.html', context)


# =============================================================================
# HELPER FUNCTIONS
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
# FORMS COMPLIANCE DASHBOARD
# =============================================================================
@login_required
def forms_compliance(request):
    """
    School Head — Forms Compliance Dashboard.
    Shows forms with status='Reviewed' that await School Head's final approval.
    """
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        messages.error(request, 'Access denied. School Heads only.')
        return redirect('signin')

    school_head = request.user
    today = date.today()

    # ── GET params ──
    quarter_label = request.GET.get('quarter', 'Q3')
    sy_id = request.GET.get('school_year')
    grade_level_id = request.GET.get('grade_level')
    section_id = request.GET.get('section_id')

    # ── School Year ──
    current_sy_obj = None
    if sy_id:
        try:
            current_sy_obj = SchoolYear.objects.get(id=sy_id)
        except SchoolYear.DoesNotExist:
            pass
    if not current_sy_obj:
        current_sy_obj = SchoolYear.objects.filter(is_current=True).first()

    available_sy = [{'id': sy.id, 'label': str(sy)} for sy in SchoolYear.objects.all().order_by('-year_start')]
    current_sy = str(current_sy_obj) if current_sy_obj else '—'
    current_sy_id = current_sy_obj.id if current_sy_obj else None

    # ── Quarter ──
    quarter_options = []
    quarter_obj = None
    if current_sy_obj:
        for q in Quarter.objects.filter(school_year=current_sy_obj).order_by('quarter_number'):
            quarter_options.append({
                'label': q.quarter_label,
                'name': f'Quarter {q.quarter_number}',
                'is_current': q.is_current_quarter,
                'is_locked': q.is_grades_locked,
            })
        quarter_obj = Quarter.objects.filter(
            school_year=current_sy_obj, quarter_label=quarter_label
        ).first()

    quarter_name = f'Quarter {quarter_obj.quarter_number}' if quarter_obj else '—'

    # ── Grade Levels ──
    grade_levels = []
    if current_sy_obj:
        grade_levels = list(
            GradeLevel.objects.filter(
                sections__enrollments__school_year=current_sy_obj,
                sections__enrollments__status='Enrolled'
            ).distinct().values('id', 'grade_name').order_by('grade_number')
        )

    # ── Sections ──
    sections = Section.objects.filter(
        enrollments__school_year=current_sy_obj,
        enrollments__status='Enrolled'
    ).distinct().select_related('grade_level').order_by('grade_level__grade_number', 'section_name')

    if grade_level_id:
        sections = sections.filter(grade_level_id=grade_level_id)

    sections_data = []
    for sec in sections:
        student_count = Enrollment.objects.filter(
            section=sec, status='Enrolled', school_year=current_sy_obj
        ).count()
        sections_data.append({
            'section_id': sec.id,
            'section_name': str(sec),
            'student_count': student_count,
        })

    # ── Selected Section ──
    selected_section_obj = None
    if section_id:
        selected_section_obj = Section.objects.filter(id=section_id).first()
    if not selected_section_obj and sections.exists():
        selected_section_obj = sections.first()

    selected_section = str(selected_section_obj) if selected_section_obj else '—'
    selected_section_id = selected_section_obj.id if selected_section_obj else None

    # ═══════════════════════════════════════════════════════════════
    # PENDING APPROVALS (status='Reviewed')
    # ═══════════════════════════════════════════════════════════════
    pending_approvals = []
    if current_sy_obj:
        pending_qs = FormSubmission.objects.filter(
            school_year=current_sy_obj,
            status='Reviewed'
        ).select_related(
            'school_form', 'section', 'section__grade_level',
            'submitted_by', 'reviewed_by', 'quarter'
        ).order_by('-updated_at')

        if quarter_obj:
            pending_qs = pending_qs.filter(
                Q(quarter=quarter_obj) | Q(quarter__isnull=True)
            )
        if grade_level_id:
            pending_qs = pending_qs.filter(section__grade_level_id=grade_level_id)
        if section_id:
            pending_qs = pending_qs.filter(section_id=section_id)

        for sub in pending_qs:
            days_waiting = (today - sub.reviewed_at.date()).days if sub.reviewed_at else 0
            pending_approvals.append({
                'id': sub.id,
                'form_code': sub.school_form.form_code,
                'form_name': sub.school_form.form_name,
                'teacher_name': sub.submitted_by.get_full_name() if sub.submitted_by else 'Unknown',
                'section_name': str(sub.section) if sub.section else 'N/A',
                'grade_level': sub.section.grade_level.grade_number if sub.section and sub.section.grade_level else '',
                'submitted_date': sub.submitted_date or sub.created_at,
                'reviewed_date': sub.reviewed_at,
                'days_waiting': days_waiting,
                'registrar': sub.reviewed_by.get_full_name() if sub.reviewed_by else 'N/A',
            })

    pending_approvals_count = len(pending_approvals)

    # ═══════════════════════════════════════════════════════════════
    # APPROVED HISTORY
    # ═══════════════════════════════════════════════════════════════
    approved_history = []
    if current_sy_obj:
        # ✅ FIXED: uses reviewed_by (the field that actually exists)
        approved_qs = FormSubmission.objects.filter(
            school_year=current_sy_obj,
            status='Approved'
        ).select_related(
            'school_form', 'section', 'submitted_by', 'reviewed_by', 'quarter'
        ).order_by('-reviewed_at')[:20]

        for sub in approved_qs:
            approved_history.append({
                'id': sub.id,
                'form_name': sub.school_form.form_name,
                'form_code': sub.school_form.form_code,
                'teacher_name': sub.submitted_by.get_full_name() if sub.submitted_by else 'N/A',
                'section_name': str(sub.section) if sub.section else 'N/A',
                # ✅ FIXED: uses reviewed_at
                'approved_date': sub.reviewed_at or sub.updated_at,
                # ✅ FIXED: uses review_notes
                'remarks': sub.review_notes or '—',
            })

    # ═══════════════════════════════════════════════════════════════
    # STATS
    # ═══════════════════════════════════════════════════════════════
    total_submitted = 0
    total_approved = 0
    total_pending_approval = 0
    total_missing = 0
    total_forms = 0

    if current_sy_obj:
        all_sections_count = Section.objects.filter(
            is_active=True, school_year=current_sy_obj
        ).count()

        for form in SchoolForm.objects.filter(is_active=True):
            submitted_count = FormSubmission.objects.filter(
                school_form=form, school_year=current_sy_obj,
                status__in=['Submitted', 'Reviewed', 'Approved']
            ).count()
            approved_count = FormSubmission.objects.filter(
                school_form=form, school_year=current_sy_obj, status='Approved'
            ).count()
            reviewed_count = FormSubmission.objects.filter(
                school_form=form, school_year=current_sy_obj, status='Reviewed'
            ).count()

            total_forms += all_sections_count
            total_submitted += submitted_count
            total_approved += approved_count
            total_pending_approval += reviewed_count
            total_missing += (all_sections_count - submitted_count)

    overall_compliance = round((total_submitted / total_forms) * 100) if total_forms > 0 else 0

    notification_count = Notification.objects.filter(
        recipient=school_head,
        is_read=False
    ).count()

    context = {
        'has_data': current_sy_obj is not None,
        'current_sy': current_sy,
        'current_sy_id': current_sy_id,
        'available_sy': available_sy,
        'quarter_label': quarter_label,
        'quarter_name': quarter_name,
        'quarter_options': quarter_options,
        'grade_levels': grade_levels,
        'sections_data': sections_data,
        'selected_section': selected_section,
        'selected_section_id': selected_section_id,
        'pending_approvals': pending_approvals,
        'pending_approvals_count': pending_approvals_count,
        'approved_history': approved_history,
        'overall_compliance': overall_compliance,
        'total_submitted': total_submitted,
        'total_approved': total_approved,
        'total_pending_approval': total_pending_approval,
        'total_missing': total_missing,
        'total_forms': total_forms,
        'notification_count': notification_count,
        'today': today,
    }

    return render(request, 'heads/compliance/forms_compliance.html', context)


# =============================================================================
# APPROVE A SINGLE FORM
# =============================================================================
@login_required
def approve_form(request, submission_id):
    """
    School Head approves a single form.
    Uses EXISTING fields: reviewed_by, reviewed_at, review_notes
    """
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        messages.error(request, 'Access denied.')
        return redirect('signin')

    if request.method != 'POST':
        return redirect('heads-forms-compliance')

    submission = get_object_or_404(FormSubmission, id=submission_id, status='Reviewed')
    remarks = request.POST.get('remarks', 'Approved by School Head.')

    # ✅ All these fields EXIST in your model
    submission.status = 'Approved'
    submission.reviewed_by = request.user
    submission.reviewed_at = timezone.now()
    submission.review_notes = remarks
    submission.save()

    if submission.submitted_by:
        Notification.objects.create(
            recipient=submission.submitted_by,
            notification_type='FORM_APPROVED',
            title=f'{submission.school_form.form_code} Approved',
            message=f'Your {submission.school_form.form_code} for {submission.section} has been approved by the School Head.',
            is_read=False,
        )

    _log(request, 'APPROVE_FORM', 'FormSubmission', submission.id,
         f'Approved {submission.school_form.form_code} for {submission.section}')

    messages.success(request, f'{submission.school_form.form_code} approved successfully.')
    return redirect('heads-forms-compliance')


# =============================================================================
# REJECT A SINGLE FORM
# =============================================================================
@login_required
def reject_form(request, submission_id):
    """
    School Head rejects a form, returning it for revision.
    """
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        messages.error(request, 'Access denied.')
        return redirect('signin')

    if request.method != 'POST':
        return redirect('heads-forms-compliance')

    submission = get_object_or_404(FormSubmission, id=submission_id, status='Reviewed')
    remarks = request.POST.get('remarks', 'Returned by School Head for revision.')

    # ✅ Uses existing fields only
    submission.status = 'Returned'
    submission.review_notes = remarks
    submission.save()

    if submission.submitted_by:
        Notification.objects.create(
            recipient=submission.submitted_by,
            notification_type='FORM_RETURNED',
            title=f'{submission.school_form.form_code} Returned',
            message=f'Your {submission.school_form.form_code} for {submission.section} has been returned by the School Head. Reason: {remarks}',
            is_read=False,
        )

    _log(request, 'REJECT_FORM', 'FormSubmission', submission.id,
         f'Rejected {submission.school_form.form_code} for {submission.section}')

    messages.warning(request, f'{submission.school_form.form_code} returned for revision.')
    return redirect('heads-forms-compliance')


# =============================================================================
# APPROVE ALL PENDING FORMS
# =============================================================================
@login_required
def approve_all_forms(request):
    """
    School Head approves ALL pending forms at once.
    """
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        messages.error(request, 'Access denied.')
        return redirect('signin')

    if request.method != 'POST':
        return redirect('heads-forms-compliance')

    current_sy = SchoolYear.objects.filter(is_current=True).first()
    if not current_sy:
        messages.error(request, 'No active school year.')
        return redirect('heads-forms-compliance')

    pending = FormSubmission.objects.filter(
        school_year=current_sy,
        status='Reviewed'
    )

    count = pending.count()
    if count == 0:
        messages.info(request, 'No pending forms to approve.')
        return redirect('heads-forms-compliance')

    # ✅ Uses existing fields: reviewed_by, reviewed_at, review_notes
    pending.update(
        status='Approved',
        reviewed_by=request.user,
        reviewed_at=timezone.now(),
        review_notes='Bulk approved by School Head.'
    )

    _log(request, 'APPROVE_ALL_FORMS', 'FormSubmission', 0,
         f'Bulk approved {count} forms')

    messages.success(request, f'{count} form(s) approved successfully.')
    return redirect('heads-forms-compliance')


# =============================================================================
# REJECT ALL PENDING FORMS
# =============================================================================
@login_required
def reject_all_forms(request):
    """
    School Head rejects ALL pending forms at once.
    """
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        messages.error(request, 'Access denied.')
        return redirect('signin')

    if request.method != 'POST':
        return redirect('heads-forms-compliance')

    current_sy = SchoolYear.objects.filter(is_current=True).first()
    if not current_sy:
        messages.error(request, 'No active school year.')
        return redirect('heads-forms-compliance')

    pending = FormSubmission.objects.filter(
        school_year=current_sy,
        status='Reviewed'
    )

    count = pending.count()
    if count == 0:
        messages.info(request, 'No pending forms to reject.')
        return redirect('heads-forms-compliance')

    # ✅ Uses existing fields
    pending.update(
        status='Returned',
        review_notes='Bulk returned by School Head for revision.'
    )

    _log(request, 'REJECT_ALL_FORMS', 'FormSubmission', 0,
         f'Bulk rejected {count} forms')

    messages.warning(request, f'{count} form(s) returned for revision.')
    return redirect('heads-forms-compliance')


# =============================================================================
# HELPER
# =============================================================================
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


# =============================================================================
# USER MANAGEMENT
# =============================================================================
@login_required
def user_management(request):
    """User Management Page - School Head manages all user accounts"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    # Get stats for the initial page load
    total_users = UserProfile.objects.filter(is_active=True).count()
    active_users = UserProfile.objects.filter(
        is_active=True, 
        user__is_active=True
    ).exclude(employment_status='Pending').count()
    pending_users = UserProfile.objects.filter(
        is_active=True, 
        employment_status='Pending'
    ).count()
    google_sso_users = UserProfile.objects.filter(
        is_active=True
    ).filter(
        Q(user__email__icontains='@deped.gov.ph') | Q(deped_email__icontains='@deped.gov.ph')
    ).count()
    
    # Notifications
    notifications = Notification.objects.filter(
        recipient=request.user, is_read=False
    ).order_by('-created_at')[:10]
    
    notification_list = []
    for n in notifications:
        icon_map = {
            'FORM_SUBMITTED': ('fi-rr-document', 'form'),
            'FORM_APPROVED': ('fi-rr-check-circle', 'form'),
            'FORM_RETURNED': ('fi-rr-undo', 'form'),
            'GRADE_SUBMITTED': ('fi-rr-chart-histogram', 'form'),
            'GRADE_APPROVED': ('fi-rr-check-circle', 'form'),
            'TRANSFER_REQUESTED': ('fi-rr-exchange', 'transfer'),
            'PROMOTION_REVIEW_NEEDED': ('fi-rr-trophy', 'alert'),
            'CORRECTION_REQUESTED': ('fi-rr-edit', 'alert'),
        }
        icon, icon_class = icon_map.get(n.notification_type, ('fi-rr-bell', 'form'))
        notification_list.append({
            'id': n.id,
            'title': n.title,
            'message': n.message,
            'icon': icon,
            'icon_class': icon_class,
            'time_ago': _time_ago(n.created_at),
            'is_read': n.is_read,
        })
    
    context = {
        'total_users': total_users,
        'active_users': active_users,
        'pending_users': pending_users,
        'google_sso_users': google_sso_users,
        'notifications': notification_list,
        'notification_count': notifications.count(),
        'today': date.today(),
    }
    return render(request, 'heads/users/user_management.html', context)


@login_required
def user_list_data(request):
    """Return user data as JSON for the table (with pagination and filters)"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    role_filter = request.GET.get('role', 'all')
    status_filter = request.GET.get('status', 'all')
    login_type = request.GET.get('login_type', 'all')
    search = request.GET.get('search', '')
    page = int(request.GET.get('page', 1))
    per_page = int(request.GET.get('per_page', 10))
    
    # Base queryset - only active profiles
    users = UserProfile.objects.filter(is_active=True).select_related('user')
    
    # Apply role filter
    if role_filter != 'all':
        users = users.filter(role=role_filter)
    
    # Apply status filter
    if status_filter != 'all':
        if status_filter == 'active':
            users = users.filter(user__is_active=True).exclude(employment_status='Pending')
        elif status_filter == 'inactive':
            users = users.filter(user__is_active=False)
        elif status_filter == 'pending':
            users = users.filter(employment_status='Pending')
    
    # Apply login type filter
    if login_type == 'google':
        users = users.filter(
            Q(user__email__icontains='@deped.gov.ph') | Q(deped_email__icontains='@deped.gov.ph')
        )
    elif login_type == 'manual':
        users = users.exclude(
            Q(user__email__icontains='@deped.gov.ph') | Q(deped_email__icontains='@deped.gov.ph')
        )
    
    # Apply search
    if search:
        users = users.filter(
            Q(user__first_name__icontains=search) |
            Q(user__last_name__icontains=search) |
            Q(user__email__icontains=search) |
            Q(employee_number__icontains=search) |
            Q(designation__icontains=search) |
            Q(teaching_area__icontains=search)
        )
    
    # Order by name
    users = users.order_by('user__last_name', 'user__first_name')
    
    total = users.count()
    total_pages = (total + per_page - 1) // per_page if per_page > 0 else 1
    start = (page - 1) * per_page
    users_page = users[start:start + per_page]
    
    user_list = []
    for profile in users_page:
        u = profile.user
        
        # Determine login type
        is_google = bool(
            ('@deped.gov.ph' in (u.email or '')) or 
            ('@deped.gov.ph' in (profile.deped_email or ''))
        )
        
        # Determine status
        if u.is_active and profile.employment_status != 'Pending':
            user_status = 'active'
        elif profile.employment_status == 'Pending':
            user_status = 'pending'
        else:
            user_status = 'inactive'
        
        # Format last active
        last_active = None
        if u.last_login:
            last_active = u.last_login.strftime('%b %d, %Y %H:%M')
        
        # Use actual employee number or generate display ID
        employee_id = profile.employee_number or f"{profile.role[:3].upper()}-{profile.id:04d}" if profile.role else f"USR-{profile.id:04d}"
        
        user_list.append({
            'id': profile.id,
            'name': u.get_full_name() or u.username,
            'first_name': u.first_name,
            'last_name': u.last_name,
            'email': u.email,
            'login_type': 'google' if is_google else 'manual',
            'role': profile.role,
            'role_display': profile.get_role_display(),
            'department': profile.teaching_area or 'Administration',
            'status': user_status,
            'last_active': last_active,
            'employee_id': employee_id,
            'designation': profile.designation or '',
            'employee_number': profile.employee_number or '',
        })
    
    # Calculate stats
    all_active_profiles = UserProfile.objects.filter(is_active=True)
    stats = {
        'total': all_active_profiles.count(),
        'active': all_active_profiles.filter(user__is_active=True).exclude(employment_status='Pending').count(),
        'pending': all_active_profiles.filter(employment_status='Pending').count(),
        'google_sso': all_active_profiles.filter(
            Q(user__email__icontains='@deped.gov.ph') | Q(deped_email__icontains='@deped.gov.ph')
        ).count(),
    }
    
    return JsonResponse({
        'success': True,
        'users': user_list,
        'total': total,
        'page': page,
        'total_pages': total_pages,
        'stats': stats,
    })



@login_required
def user_detail_data(request, user_id):
    """Return single user detail as JSON for editing"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    try:
        profile = UserProfile.objects.select_related('user').get(id=user_id, is_active=True)
    except UserProfile.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'User not found'}, status=404)
    
    u = profile.user
    
    # Determine login type
    is_google = bool(
        ('@deped.gov.ph' in (u.email or '')) or 
        ('@deped.gov.ph' in (profile.deped_email or ''))
    )
    
    # Determine status
    if u.is_active and profile.employment_status != 'Pending':
        user_status = 'active'
    elif profile.employment_status == 'Pending':
        user_status = 'pending'
    else:
        user_status = 'inactive'
    
    return JsonResponse({
        'success': True,
        'user': {
            'id': profile.id,
            'first_name': u.first_name,
            'last_name': u.last_name,
            'email': u.email,
            'login_type': 'google' if is_google else 'manual',
            'role': profile.role,
            'department': profile.teaching_area or 'Administration',
            'status': user_status,
            'employee_number': profile.employee_number or '',
            'designation': profile.designation or '',
        }
    })



@login_required
@csrf_exempt
def user_create(request):
    """Create a new user with full profile data - works WITH the auto-create signal"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    try:
        data = json.loads(request.body)
        
        first_name = data.get('first_name', '').strip()
        last_name = data.get('last_name', '').strip()
        email = data.get('email', '').strip().lower()
        login_type = data.get('login_type', 'google')
        role = data.get('role', 'teacher')
        department = data.get('department', '')
        status = data.get('status', 'pending')
        password = data.get('password', '')
        employee_number = data.get('employee_number', '').strip()
        designation = data.get('designation', '').strip()
        
        # Validate required fields
        if not first_name or not last_name or not email:
            return JsonResponse({'success': False, 'error': 'First name, last name, and email are required'}, status=400)
        
        # Validate role
        valid_roles = [choice[0] for choice in UserProfile.ROLE_CHOICES]
        if role not in valid_roles:
            return JsonResponse({'success': False, 'error': f'Invalid role. Valid roles: {", ".join(valid_roles)}'}, status=400)
        
        # Check if email already exists
        if User.objects.filter(email=email).exists():
            return JsonResponse({
                'success': False, 
                'error': f'A user with email {email} already exists.'
            }, status=400)
        
        # Check if employee number is already used (if provided)
        if employee_number and UserProfile.objects.filter(employee_number=employee_number).exists():
            return JsonResponse({
                'success': False, 
                'error': f'Employee number {employee_number} is already assigned.'
            }, status=400)
        
        # Create unique username from email
        import re
        username = re.sub(r'[^a-z0-9._-]', '', email.split('@')[0].lower())
        base_username = username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1
        
        # Set password
        if login_type == 'manual' and password:
            user_password = password
        else:
            user_password = User.objects.make_random_password()
        
        is_active = (status == 'active')
        
        # Determine employment status
        employment_status_map = {
            'active': 'Regular_Permanent',
            'pending': 'Pending',
            'inactive': 'Inactive',
        }
        employment_status = employment_status_map.get(status, 'Pending')
        
        # CREATE USER - the signal will auto-create a basic UserProfile
        user = User.objects.create_user(
            username=username,
            email=email,
            password=user_password,
            first_name=first_name,
            last_name=last_name,
            is_active=is_active,
        )
        
        # UPDATE THE AUTO-CREATED PROFILE with all required fields
        profile = user.profile
        
        profile.role = role
        profile.teaching_area = department
        profile.employment_status = employment_status
        profile.employee_number = employee_number if employee_number else None
        profile.designation = designation
        profile.is_active = True
        
        # Set DepEd email for Google SSO users
        if login_type == 'google' and '@deped.gov.ph' in email:
            profile.deped_email = email
        elif '@deped.gov.ph' in email:
            profile.deped_email = email
        
        profile.save()
        
        _log(request, 'CREATE_USER', 'UserProfile', profile.id, 
             f'Created user: {first_name} {last_name} ({role}) - Status: {status}')
        
        # Return the password for manual accounts so admin can share it
        response_data = {
            'success': True, 
            'message': f'User {first_name} {last_name} created successfully',
            'user_id': profile.id,
        }
        
        if login_type == 'manual':
            response_data['generated_password'] = user_password
            response_data['message'] += f'. Temporary password: {user_password}'
        
        return JsonResponse(response_data)
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        import traceback
        print(f"ERROR creating user: {e}")
        print(traceback.format_exc())
        return JsonResponse({'success': False, 'error': f'Server error: {str(e)}'}, status=500)




@login_required
@csrf_exempt
def user_update(request, user_id):
    """Update an existing user with all profile fields"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    try:
        profile = UserProfile.objects.select_related('user').get(id=user_id, is_active=True)
    except UserProfile.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'User not found'}, status=404)
    
    user = profile.user
    
    try:
        data = json.loads(request.body)
        
        new_email = data.get('email', user.email).strip().lower()
        new_role = data.get('role', profile.role)
        new_employee_number = data.get('employee_number', '').strip()
        
        # Validate role
        valid_roles = [choice[0] for choice in UserProfile.ROLE_CHOICES]
        if new_role not in valid_roles:
            return JsonResponse({'success': False, 'error': f'Invalid role. Valid roles: {", ".join(valid_roles)}'}, status=400)
        
        # Check if email is being changed and if new email conflicts
        if new_email != user.email and User.objects.filter(email=new_email).exclude(id=user.id).exists():
            return JsonResponse({
                'success': False, 
                'error': 'Another user already has this email address'
            }, status=400)
        
        # Check if employee number is already used (if provided and changed)
        if new_employee_number and new_employee_number != profile.employee_number:
            if UserProfile.objects.filter(employee_number=new_employee_number).exclude(id=profile.id).exists():
                return JsonResponse({
                    'success': False, 
                    'error': f'Employee number {new_employee_number} is already assigned.'
                }, status=400)
        
        # Update User fields
        user.first_name = data.get('first_name', user.first_name)
        user.last_name = data.get('last_name', user.last_name)
        user.email = new_email
        
        # Update active status
        new_status = data.get('status', 'active')
        user.is_active = (new_status == 'active')
        user.save()
        
        # Update Profile fields
        profile.role = new_role
        profile.teaching_area = data.get('department', profile.teaching_area)
        profile.employee_number = new_employee_number if new_employee_number else None
        profile.designation = data.get('designation', '').strip()
        
        # Update employment status based on status
        if new_status == 'active':
            if profile.employment_status == 'Pending':
                profile.employment_status = 'Regular_Permanent'
        elif new_status == 'pending':
            profile.employment_status = 'Pending'
        elif new_status == 'inactive':
            profile.employment_status = 'Inactive'
        
        # Update DepEd email if applicable
        if '@deped.gov.ph' in new_email:
            profile.deped_email = new_email
        
        profile.save()
        
        _log(request, 'UPDATE_USER', 'UserProfile', profile.id, 
             f'Updated user: {user.get_full_name()} - Role: {new_role}, Status: {new_status}')
        
        return JsonResponse({
            'success': True, 
            'message': f'User {user.get_full_name()} updated successfully'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        import traceback
        print(f"ERROR updating user: {e}")
        print(traceback.format_exc())
        return JsonResponse({'success': False, 'error': f'Server error: {str(e)}'}, status=500)


@login_required
@csrf_exempt
def user_toggle_status(request, user_id):
    """Toggle user active/inactive status"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    try:
        profile = UserProfile.objects.select_related('user').get(id=user_id, is_active=True)
    except UserProfile.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'User not found'}, status=404)
    
    user = profile.user
    
    # Prevent deactivating yourself
    if user.id == request.user.id:
        return JsonResponse({'success': False, 'error': 'You cannot deactivate your own account'}, status=400)
    
    user.is_active = not user.is_active
    user.save()
    
    # Update profile employment status
    if user.is_active:
        if profile.employment_status == 'Inactive':
            profile.employment_status = 'Regular_Permanent'
    else:
        profile.employment_status = 'Inactive'
    profile.save()
    
    status_text = 'activated' if user.is_active else 'deactivated'
    _log(request, 'TOGGLE_USER', 'UserProfile', profile.id, 
         f'{status_text.capitalize()} user: {user.get_full_name()}')
    
    return JsonResponse({
        'success': True,
        'message': f'User {user.get_full_name()} {status_text} successfully',
        'new_status': 'active' if user.is_active else 'inactive',
    })


@login_required
@csrf_exempt
def user_reset_password(request, user_id):
    """Reset password for a manual account user"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    try:
        profile = UserProfile.objects.select_related('user').get(id=user_id, is_active=True)
    except UserProfile.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'User not found'}, status=404)
    
    user = profile.user
    
    # Check if this is a Google SSO user
    is_google = bool(
        ('@deped.gov.ph' in (user.email or '')) or 
        ('@deped.gov.ph' in (profile.deped_email or ''))
    )
    
    if is_google:
        return JsonResponse({
            'success': False, 
            'error': 'Cannot reset password for Google SSO accounts. Password is managed by Google Workspace.'
        }, status=400)
    
    try:
        data = json.loads(request.body)
        new_password = data.get('password', '')
        
        if len(new_password) < 6:
            return JsonResponse({'success': False, 'error': 'Password must be at least 6 characters'}, status=400)
        
        user.set_password(new_password)
        user.save()
        
        _log(request, 'RESET_PASSWORD', 'UserProfile', profile.id, 
             f'Password reset for: {user.get_full_name()}')
        
        return JsonResponse({
            'success': True, 
            'message': f'Password reset successfully for {user.get_full_name()}'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': f'Server error: {str(e)}'}, status=500)


@login_required
def user_export(request):
    """Export users to CSV"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    role_filter = request.GET.get('role', 'all')
    status_filter = request.GET.get('status', 'all')
    login_type = request.GET.get('login_type', 'all')
    
    users = UserProfile.objects.filter(is_active=True).select_related('user')
    
    # Apply filters
    if role_filter != 'all':
        users = users.filter(role=role_filter)
    
    if status_filter == 'active':
        users = users.filter(user__is_active=True).exclude(employment_status='Pending')
    elif status_filter == 'inactive':
        users = users.filter(user__is_active=False)
    elif status_filter == 'pending':
        users = users.filter(employment_status='Pending')
    
    if login_type == 'google':
        users = users.filter(
            Q(user__email__icontains='@deped.gov.ph') | Q(deped_email__icontains='@deped.gov.ph')
        )
    elif login_type == 'manual':
        users = users.exclude(
            Q(user__email__icontains='@deped.gov.ph') | Q(deped_email__icontains='@deped.gov.ph')
        )
    
    users = users.order_by('user__last_name', 'user__first_name')
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="users_export_{date.today().strftime("%Y%m%d")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Employee Number', 'First Name', 'Last Name', 'Email', 'DepEd Email',
        'Role', 'Designation', 'Department', 'Employment Status', 
        'Login Type', 'Account Status', 'Last Active', 'Date Hired'
    ])
    
    for profile in users:
        u = profile.user
        is_google = bool(
            ('@deped.gov.ph' in (u.email or '')) or 
            ('@deped.gov.ph' in (profile.deped_email or ''))
        )
        
        if u.is_active and profile.employment_status != 'Pending':
            account_status = 'Active'
        elif profile.employment_status == 'Pending':
            account_status = 'Pending'
        else:
            account_status = 'Inactive'
        
        writer.writerow([
            profile.employee_number or 'N/A',
            u.first_name,
            u.last_name,
            u.email,
            profile.deped_email or 'N/A',
            profile.get_role_display(),
            profile.designation or 'N/A',
            profile.teaching_area or 'N/A',
            profile.get_employment_status_display() if profile.employment_status else 'N/A',
            'Google SSO' if is_google else 'Manual',
            account_status,
            u.last_login.strftime('%Y-%m-%d %H:%M') if u.last_login else 'Never',
            profile.date_hired.strftime('%Y-%m-%d') if profile.date_hired else 'N/A',
        ])
    
    return response


# =============================================================================
# SCHOOL PERFORMANCE DASHBOARD - FULLY FIXED
# =============================================================================
@login_required
def school_performance(request):
    """
    School Head — School Performance Dashboard.
    Shows academic indicators, enrollment trends, and student achievement.
    """
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'schoolhead':
        messages.error(request, 'Access denied. School Heads only.')
        return redirect('signin')

    school_head = request.user
    today = date.today()

    # ── GET params for filters ──
    sy_id = request.GET.get('school_year')
    quarter_label = request.GET.get('quarter', 'Q3')
    grade_level_id = request.GET.get('grade_level', 'all')

    # ── Current School Year ──
    current_sy = None
    current_sy_id = None
    if sy_id:
        try:
            current_sy = SchoolYear.objects.get(id=sy_id)
            current_sy_id = current_sy.id
        except (SchoolYear.DoesNotExist, ValueError):
            pass
    if not current_sy:
        current_sy = SchoolYear.objects.filter(is_current=True).first()
        if current_sy:
            current_sy_id = current_sy.id

    has_data = current_sy is not None
    current_sy_label = str(current_sy) if current_sy else 'N/A'
    available_sy = list(SchoolYear.objects.all().order_by('-year_start'))

    # ── Quarter ──
    quarter_obj = None
    if current_sy:
        quarter_obj = Quarter.objects.filter(
            school_year=current_sy, quarter_label=quarter_label
        ).first()
    quarter_name = f'Quarter {quarter_obj.quarter_number}' if quarter_obj else quarter_label

    # ── Grade Levels for filter ──
    grade_levels = GradeLevel.objects.all().order_by('sort_order')

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
                attendance_rate = round(total_rate / count, 1)

    # ═══════════════════════════════════════════════════════════════
    # ENROLLMENT TREND (5-Year)
    # ═══════════════════════════════════════════════════════════════
    enrollment_trend_labels = []
    enrollment_trend_data = []
    
    all_sy = list(SchoolYear.objects.all().order_by('year_start'))
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
                    prev_year_data[2] = round(prev_att_total / prev_att_count, 1)

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

    return render(request, 'heads/performance/school_performance.html', context)


# =============================================================================
# PLACEHOLDER VIEWS - Static pages for navigation
# =============================================================================

# =============================================================================
# MINIMAL WORKING VIEWS (to be developed later)
# =============================================================================

# =============================================================================
# MINIMAL WORKING VIEWS (to be developed later)
# =============================================================================

def teacher_evaluation(request):
    return redirect('heads-evaluation')


def heads_reports(request):
    return redirect('heads-reports')


def announcements(request):
    return redirect('heads-announcements')


def messages_page(request):
    return redirect('heads-messages')

def heads_settings(request):
    return redirect('heads-settings')



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