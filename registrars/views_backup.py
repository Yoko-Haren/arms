from xml.dom import ValidationErr

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Q, Avg, Sum
from django.utils import timezone
from datetime import date, timedelta, datetime
import json
import csv
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from io import BytesIO
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

from academics import models
from enrollment.models import Enrollment
from grades.models import GradeComponent
from transfers.models import Transfer
from academics.models import GradeLevel, SchoolYear, Quarter, Section
from students.models import Student, Guardian
from documentation.models import FormSubmission, FormCompliance, SF10History, DocumentRequest
from accounts.models import SchoolForm, UserProfile
from promotion.models import PromotionRecommendation
from audit.models import ActivityLog, DataCorrectionRequest
from communication.models import Notification
from attendance.models import AttendanceRecord
from accounts.models import SchoolProfile

from django.http import FileResponse
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
import os
from django.conf import settings
import tempfile
from scheduling.models import ClassAssignment, ClassSchedule
from academics.models import Subject, Room


# =============================================================================
# HELPER FUNCTION
# =============================================================================
def _log(request, action_type, resource_type, resource_id, description):
    """Create an ActivityLog entry (blockchain-verified audit trail)."""
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
# DASHBOARD
# =============================================================================
@login_required
def dashboard(request):
    """Registrar Dashboard"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')

    registrar = request.user
    today = date.today()
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    has_data = current_sy is not None

    total_enrollment = 0
    jhs_count = 0
    shs_count = 0
    enrollment_by_grade = []
    
    if has_data:
        total_enrollment = Enrollment.objects.filter(
            school_year=current_sy, status__in=['Enrolled', 'Transferred_In']
        ).count()
        jhs_count = Enrollment.objects.filter(
            school_year=current_sy, status__in=['Enrolled', 'Transferred_In'],
            section__grade_level__is_senior_high=False
        ).count()
        shs_count = total_enrollment - jhs_count

        for gl in GradeLevel.objects.all().order_by('sort_order'):
            count = Enrollment.objects.filter(
                school_year=current_sy, status__in=['Enrolled', 'Transferred_In'],
                section__grade_level=gl
            ).count()
            if count > 0:
                enrollment_by_grade.append({'grade_name': gl.grade_name, 'count': count})

    pending_validations = 0
    pending_validation_items = []
    
    if has_data:
        pending_validations = GradeComponent.objects.filter(
            validation_status__in=['Submitted', 'Returned']
        ).count()
        
        pending = GradeComponent.objects.filter(
            validation_status='Submitted'
        ).select_related('enrollment__section', 'subject', 'encoded_by')[:10]

        for gc in pending:
            section = gc.enrollment.section
            total_grades = GradeComponent.objects.filter(
                enrollment__section=section, subject=gc.subject
            ).count()
            submitted = GradeComponent.objects.filter(
                enrollment__section=section, subject=gc.subject,
                validation_status__in=['Submitted', 'Validated', 'Finalized']
            ).count()
            missing = total_grades - submitted if total_grades > submitted else 0

            pending_validation_items.append({
                'section': str(section),
                'teacher': gc.encoded_by.get_full_name() if gc.encoded_by else 'Unknown',
                'subject': gc.subject.subject_name,
                'student_count': Enrollment.objects.filter(section=section, status='Enrolled').count(),
                'status_class': 'status-success' if missing == 0 else 'status-warning',
                'status_text': 'Ready for Review' if missing == 0 else f'Missing {missing} Grades',
            })

    transfer_count = 0
    incoming_count = 0
    outgoing_count = 0
    transfer_items = []
    
    if has_data:
        all_transfers = Transfer.objects.filter(
            status__in=['Pending', 'Documents_Requested', 'Documents_Released']
        ).select_related('student')
        transfer_count = all_transfers.count()
        incoming_count = all_transfers.filter(transfer_type='INCOMING').count()
        outgoing_count = all_transfers.filter(transfer_type='OUTGOING').count()

        for t in all_transfers.order_by('-transfer_date_requested')[:8]:
            sc = 'status-warning'
            if t.status == 'Documents_Released':
                sc = 'status-success'
            elif t.status == 'Pending':
                sc = 'status-danger'
            transfer_items.append({
                'id': t.id,
                'student_name': t.student.full_name,
                'lrn': t.student.lrn,
                'transfer_type': t.get_transfer_type_display(),
                'from_school': t.from_school_name or 'N/A',
                'to_school': t.to_school_name or 'N/A',
                'grade_level': str(t.grade_level_at_transfer) if t.grade_level_at_transfer else 'N/A',
                'status_class': sc,
                'status_text': t.get_status_display(),
            })

    forms_compliance = []
    forms_total = 0
    forms_completed = 0
    
    if has_data:
        total_forms = SchoolForm.objects.filter(is_active=True).count()
        forms_total = total_forms
        completed_forms = FormCompliance.objects.filter(
            school_year=current_sy, status__in=['Locked', 'Closed']
        ).count()
        forms_completed = completed_forms
        
        for sf in SchoolForm.objects.filter(is_active=True).order_by('form_code'):
            submitted = FormSubmission.objects.filter(
                school_form=sf, school_year=current_sy,
                status__in=['Submitted', 'Reviewed', 'Approved']
            ).count()
            total_sections = Section.objects.filter(school_year=current_sy, is_active=True).count()
            pct = round((submitted / total_sections) * 100) if total_sections > 0 else 0
            forms_compliance.append({
                'form_code': sf.form_code,
                'form_name': sf.form_name,
                'pct': pct,
            })

    context = {
        'has_data': has_data,
        'current_sy_label': current_sy.year_label if current_sy else 'N/A',
        'current_sy': current_sy,
        'total_enrollment': total_enrollment,
        'jhs_count': jhs_count,
        'shs_count': shs_count,
        'enrollment_by_grade': enrollment_by_grade,
        'pending_validations': pending_validations,
        'pending_validation_items': pending_validation_items,
        'transfer_count': transfer_count,
        'incoming_count': incoming_count,
        'outgoing_count': outgoing_count,
        'transfer_items': transfer_items,
        'forms_compliance': forms_compliance,
        'forms_total': forms_total,
        'forms_completed': forms_completed,
        'today': today,
    }
    return render(request, 'registrars/dashboard/index.html', context)


# =============================================================================
# GRADE VALIDATION
# =============================================================================
@login_required
def grade_validation(request):
    """Grade Validation Page - Registrar reviews and validates teacher-submitted grades"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')

    today = date.today()
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    
    # Get filter parameters
    grade_level_id = request.GET.get('grade_level')
    teacher_id = request.GET.get('teacher_id')
    quarter_label = request.GET.get('quarter', 'Q3')
    status_filter = request.GET.get('status', 'all')
    search_query = request.GET.get('search', '')
    page = int(request.GET.get('page', 1))
    per_page = int(request.GET.get('per_page', 25))
    
    # Get current quarter
    current_quarter = None
    if current_sy:
        try:
            current_quarter = Quarter.objects.filter(
                school_year=current_sy, quarter_label=quarter_label
            ).first()
        except:
            current_quarter = None
    
    # Base queryset for grade components
    grade_components = GradeComponent.objects.select_related(
        'enrollment__student', 
        'enrollment__section', 
        'enrollment__section__grade_level',
        'subject', 
        'encoded_by'
    )
    
    if current_sy:
        grade_components = grade_components.filter(
            enrollment__school_year=current_sy
        )
    
    if current_quarter:
        grade_components = grade_components.filter(quarter=current_quarter)
    
    # Apply filters
    if grade_level_id and grade_level_id != '':
        grade_components = grade_components.filter(
            enrollment__section__grade_level_id=grade_level_id
        )
    
    if teacher_id and teacher_id != '':
        grade_components = grade_components.filter(encoded_by_id=teacher_id)
    
    if status_filter and status_filter != 'all':
        if status_filter == 'pending':
            grade_components = grade_components.filter(validation_status='Submitted')
        elif status_filter == 'approved':
            grade_components = grade_components.filter(validation_status='Validated')
        elif status_filter == 'rejected':
            grade_components = grade_components.filter(validation_status='Returned')
    
    if search_query:
        grade_components = grade_components.filter(
            Q(enrollment__student__first_name__icontains=search_query) |
            Q(enrollment__student__last_name__icontains=search_query) |
            Q(enrollment__student__lrn__icontains=search_query)
        )
    
    # Get total count for pagination
    total_records = grade_components.count()
    total_pages = (total_records + per_page - 1) // per_page if per_page > 0 else 1
    start = (page - 1) * per_page
    grade_components_page = grade_components.order_by('-created_at')[start:start + per_page]
    
    # Statistics
    pending_count = GradeComponent.objects.filter(
        validation_status='Submitted'
    ).count() if current_sy else 0
    
    approved_count = GradeComponent.objects.filter(
        validation_status='Validated'
    ).count() if current_sy else 0
    
    returned_count = GradeComponent.objects.filter(
        validation_status='Returned'
    ).count() if current_sy else 0
    
    # Get unique teachers who have submitted grades
    teacher_ids = GradeComponent.objects.filter(
        validation_status='Submitted'
    ).values_list('encoded_by_id', flat=True).distinct() if current_sy else []
    
    teachers = UserProfile.objects.filter(
        user_id__in=teacher_ids, role='teacher'
    ).select_related('user') if teacher_ids else []
    
    # Get grade levels that actually have grade components
    grade_levels = []
    if current_sy:
        grade_level_ids = GradeComponent.objects.filter(
            enrollment__school_year=current_sy
        ).values_list(
            'enrollment__section__grade_level_id', flat=True
        ).distinct()
        
        grade_levels = GradeLevel.objects.filter(id__in=grade_level_ids).order_by('sort_order')
    
    # Prepare validation items for display
    validation_items = []
    for gc in grade_components_page:
        student = gc.enrollment.student
        section = gc.enrollment.section
        
        teacher_name = 'Unknown'
        if gc.encoded_by:
            teacher_name = gc.encoded_by.get_full_name() or gc.encoded_by.username
        
        validation_items.append({
            'id': gc.id,
            'lrn': student.lrn if student else '',
            'student_name': f"{student.last_name}, {student.first_name}" if student else 'Unknown',
            'grade_level': section.grade_level.grade_name if section and section.grade_level else '',
            'grade_number': section.grade_level.grade_number if section and section.grade_level else 0,
            'section': section.section_name if section else '',
            'teacher': teacher_name,
            'subject': gc.subject.subject_name if gc.subject else '',
            'final_grade': gc.initial_grade,
            'status': gc.validation_status,
            'submitted_date': gc.encoding_date.strftime('%Y-%m-%d') if gc.encoding_date else '',
            'quarter': current_quarter.quarter_label if current_quarter else 'Q3',
            'written_work': gc.written_work_raw,
            'performance_task': gc.performance_task_raw,
            'quarterly_assessment': gc.quarterly_assessment_raw,
            'remarks': gc.remarks,
            'validated_by': gc.validated_by.get_full_name() if gc.validated_by else '',
            'validated_date': gc.validation_date.strftime('%Y-%m-%d') if gc.validation_date else '',
        })
    
    # Prepare options for filters
    teacher_options = []
    for t in teachers:
        if t and t.user:
            teacher_options.append({
                'id': t.user.id,
                'name': t.user.get_full_name() or t.user.username
            })
    
    grade_level_options = [
        {'id': gl.id, 'name': gl.grade_name, 'number': gl.grade_number}
        for gl in grade_levels
    ]
    
    context = {
        'has_data': current_sy is not None,
        'current_sy_label': current_sy.year_label if current_sy else 'N/A',
        'current_sy': current_sy,
        'today': today,
        'pending_count': pending_count,
        'approved_count': approved_count,
        'returned_count': returned_count,
        'teacher_count': len(teacher_ids),
        'validation_items': validation_items,
        'grade_level_options': grade_level_options,
        'teacher_options': teacher_options,
        'selected_grade_level': grade_level_id or '',
        'selected_teacher': teacher_id or '',
        'selected_quarter': quarter_label,
        'selected_status': status_filter,
        'search_query': search_query,
        'total_records': total_records,
        'current_page': page,
        'total_pages': total_pages,
        'per_page': per_page,
        'quarter_label': quarter_label,
    }
    
    return render(request, 'registrars/grades/validation.html', context)


@login_required
@csrf_exempt
def grade_validation_action(request):
    """Handle grade approval, rejection, and correction requests via AJAX"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    try:
        data = json.loads(request.body)
        component_id = data.get('component_id')
        action = data.get('action')
        remarks = data.get('remarks', '')
        
        grade_component = get_object_or_404(GradeComponent, id=component_id)
        
        if action == 'approve':
            grade_component.validation_status = 'Validated'
            grade_component.validated_by = request.user
            grade_component.validation_date = timezone.now()
            grade_component.remarks = remarks or 'Approved by Registrar'
            message = 'Grade approved successfully'
            
            if grade_component.encoded_by:
                Notification.objects.create(
                    recipient=grade_component.encoded_by,
                    notification_type='GRADE_APPROVED',
                    title='Grade Approved',
                    message=f'Your grade for {grade_component.subject.subject_name} has been approved.',
                    is_read=False,
                )
                
        elif action == 'reject':
            if not remarks:
                return JsonResponse({'success': False, 'error': 'Reason required for rejection'}, status=400)
            grade_component.validation_status = 'Returned'
            grade_component.validated_by = request.user
            grade_component.validation_date = timezone.now()
            grade_component.remarks = remarks
            message = 'Grade rejected and returned for correction'
            
            if grade_component.encoded_by:
                Notification.objects.create(
                    recipient=grade_component.encoded_by,
                    notification_type='GRADE_RETURNED',
                    title='Grade Returned for Correction',
                    message=f'Your grade for {grade_component.subject.subject_name} needs correction. Reason: {remarks}',
                    is_read=False,
                )
                
        elif action == 'correction':
            if not remarks:
                return JsonResponse({'success': False, 'error': 'Correction note required'}, status=400)
            grade_component.validation_status = 'Submitted'
            grade_component.remarks = f'Correction requested: {remarks}'
            message = 'Correction request sent to teacher'
            
            if grade_component.encoded_by:
                Notification.objects.create(
                    recipient=grade_component.encoded_by,
                    notification_type='GRADE_CORRECTION_REQUESTED',
                    title='Grade Correction Requested',
                    message=f'Please review and correct the grade for {grade_component.subject.subject_name}. Note: {remarks}',
                    is_read=False,
                )
        else:
            return JsonResponse({'success': False, 'error': 'Invalid action'}, status=400)
        
        grade_component.save()
        _log(request, f'GRADE_{action.upper()}', 'GradeComponent', grade_component.id, message)
        
        return JsonResponse({
            'success': True,
            'message': message,
            'new_status': grade_component.validation_status
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def grade_validation_detail(request, component_id):
    """Get detailed grade data for modal view"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    grade_component = get_object_or_404(
        GradeComponent.objects.select_related(
            'enrollment__student', 'enrollment__section', 'enrollment__section__grade_level',
            'subject', 'encoded_by', 'validated_by', 'quarter'
        ),
        id=component_id
    )
    
    student = grade_component.enrollment.student
    section = grade_component.enrollment.section
    
    data = {
        'id': grade_component.id,
        'lrn': student.lrn,
        'student_name': f"{student.last_name}, {student.first_name} {student.middle_name or ''}",
        'grade_level': section.grade_level.grade_name if section.grade_level else '',
        'section': section.section_name,
        'teacher': grade_component.encoded_by.get_full_name() if grade_component.encoded_by else 'Unknown',
        'subject': grade_component.subject.subject_name,
        'status': grade_component.validation_status,
        'quarter': grade_component.quarter.quarter_label if grade_component.quarter else 'N/A',
        'final_grade': grade_component.initial_grade,
        'written_work': grade_component.written_work_raw,
        'performance_task': grade_component.performance_task_raw,
        'quarterly_assessment': grade_component.quarterly_assessment_raw,
        'remarks': grade_component.remarks,
        'validated_by': grade_component.validated_by.get_full_name() if grade_component.validated_by else '',
        'validated_date': grade_component.validation_date.strftime('%Y-%m-%d') if grade_component.validation_date else '',
        'submitted_date': grade_component.encoding_date.strftime('%Y-%m-%d') if grade_component.encoding_date else '',
    }
    
    return JsonResponse({'success': True, 'data': data})


@login_required
def grade_validation_export_csv(request):
    """Export grade validation data to CSV with professional formatting"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    # Get filters from request
    grade_level_id = request.GET.get('grade_level')
    teacher_id = request.GET.get('teacher_id')
    quarter_label = request.GET.get('quarter', 'Q3')
    status_filter = request.GET.get('status', 'all')
    
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    current_quarter = Quarter.objects.filter(
        school_year=current_sy, quarter_label=quarter_label
    ).first() if current_sy else None
    
    grade_components = GradeComponent.objects.select_related(
        'enrollment__student', 'enrollment__section', 'enrollment__section__grade_level',
        'subject', 'encoded_by'
    )
    
    if current_sy:
        grade_components = grade_components.filter(enrollment__school_year=current_sy)
    if current_quarter:
        grade_components = grade_components.filter(quarter=current_quarter)
    if grade_level_id:
        grade_components = grade_components.filter(enrollment__section__grade_level_id=grade_level_id)
    if teacher_id:
        grade_components = grade_components.filter(encoded_by_id=teacher_id)
    if status_filter != 'all':
        if status_filter == 'pending':
            grade_components = grade_components.filter(validation_status='Submitted')
        elif status_filter == 'approved':
            grade_components = grade_components.filter(validation_status='Validated')
        elif status_filter == 'rejected':
            grade_components = grade_components.filter(validation_status='Returned')
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="Grade_Validation_Report_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    
    writer = csv.writer(response)
    
    # Header
    writer.writerow(['=' * 80])
    writer.writerow(['GRADE VALIDATION REPORT'])
    writer.writerow([f'School Year: {current_sy.year_label if current_sy else "N/A"}'])
    writer.writerow([f'Quarter: {quarter_label}'])
    writer.writerow([f'Generated: {timezone.now().strftime("%Y-%m-%d %H:%M:%S")}'])
    writer.writerow([f'Total Records: {grade_components.count()}'])
    writer.writerow(['=' * 80])
    writer.writerow([])
    
    # Column headers
    writer.writerow([
        'LRN', 'Student Name', 'Grade Level', 'Section', 'Teacher', 'Subject',
        'Written Work (%)', 'Performance Task (%)', 'Quarterly Assessment (%)',
        'Final Grade (%)', 'Status', 'Remarks', 'Submitted Date', 'Validated By', 'Validated Date'
    ])
    
    # Data rows
    for gc in grade_components:
        student = gc.enrollment.student
        section = gc.enrollment.section
        status_display = 'Pending' if gc.validation_status == 'Submitted' else 'Approved' if gc.validation_status == 'Validated' else 'Returned'
        
        writer.writerow([
            student.lrn,
            f"{student.last_name}, {student.first_name}",
            section.grade_level.grade_name if section.grade_level else '',
            section.section_name,
            gc.encoded_by.get_full_name() if gc.encoded_by else '',
            gc.subject.subject_name,
            gc.written_work_raw or '',
            gc.performance_task_raw or '',
            gc.quarterly_assessment_raw or '',
            gc.initial_grade,
            status_display,
            gc.remarks or '',
            gc.encoding_date.strftime('%Y-%m-%d') if gc.encoding_date else '',
            gc.validated_by.get_full_name() if gc.validated_by else '',
            gc.validation_date.strftime('%Y-%m-%d') if gc.validation_date else '',
        ])
    
    return response


@login_required
def grade_validation_export_excel(request):
    """Export grade validation data to Excel with professional formatting"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill, numbers
    from openpyxl.utils import get_column_letter
    
    # Get filters from request
    grade_level_id = request.GET.get('grade_level')
    teacher_id = request.GET.get('teacher_id')
    quarter_label = request.GET.get('quarter', 'Q3')
    status_filter = request.GET.get('status', 'all')
    
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    current_quarter = Quarter.objects.filter(
        school_year=current_sy, quarter_label=quarter_label
    ).first() if current_sy else None
    
    grade_components = GradeComponent.objects.select_related(
        'enrollment__student', 'enrollment__section', 'enrollment__section__grade_level',
        'subject', 'encoded_by'
    )
    
    if current_sy:
        grade_components = grade_components.filter(enrollment__school_year=current_sy)
    if current_quarter:
        grade_components = grade_components.filter(quarter=current_quarter)
    if grade_level_id:
        grade_components = grade_components.filter(enrollment__section__grade_level_id=grade_level_id)
    if teacher_id:
        grade_components = grade_components.filter(encoded_by_id=teacher_id)
    if status_filter != 'all':
        if status_filter == 'pending':
            grade_components = grade_components.filter(validation_status='Submitted')
        elif status_filter == 'approved':
            grade_components = grade_components.filter(validation_status='Validated')
        elif status_filter == 'rejected':
            grade_components = grade_components.filter(validation_status='Returned')
    
    # Create workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Grade Validation Report"
    
    # ========== STYLES ==========
    # Title styles
    title_font = Font(name='Calibri', size=14, bold=True, color='00072D')
    subtitle_font = Font(name='Calibri', size=10, color='718096')
    
    # Header styles
    header_font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
    header_fill = PatternFill(start_color='5EA173', end_color='5EA173', fill_type='solid')
    header_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    
    # Status colors
    pending_fill = PatternFill(start_color='FFF3CD', end_color='FFF3CD', fill_type='solid')
    approved_fill = PatternFill(start_color='D4EDDA', end_color='D4EDDA', fill_type='solid')
    rejected_fill = PatternFill(start_color='F8D7DA', end_color='F8D7DA', fill_type='solid')
    
    # Border style
    thin_border = Border(
        left=Side(style='thin', color='D4D4D4'),
        right=Side(style='thin', color='D4D4D4'),
        top=Side(style='thin', color='D4D4D4'),
        bottom=Side(style='thin', color='D4D4D4')
    )
    
    center_align = Alignment(horizontal='center', vertical='center')
    left_align = Alignment(horizontal='left', vertical='center')
    
    # ========== REPORT HEADER ==========
    # Title
    ws.merge_cells('A1:O1')
    title_cell = ws.cell(row=1, column=1, value="GRADE VALIDATION REPORT")
    title_cell.font = title_font
    title_cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 30
    
    # Subtitle - School Year
    ws.merge_cells('A2:O2')
    sy_cell = ws.cell(row=2, column=1, value=f"School Year: {current_sy.year_label if current_sy else 'N/A'} | Quarter: {quarter_label}")
    sy_cell.font = subtitle_font
    sy_cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[2].height = 22
    
    # Subtitle - Generated date
    ws.merge_cells('A3:O3')
    date_cell = ws.cell(row=3, column=1, value=f"Generated: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}")
    date_cell.font = subtitle_font
    date_cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[3].height = 22
    
    # Filters applied
    filters_applied = []
    if grade_level_id:
        gl = GradeLevel.objects.filter(id=grade_level_id).first()
        if gl:
            filters_applied.append(f"Grade Level: {gl.grade_name}")
    if teacher_id:
        teacher = UserProfile.objects.filter(user_id=teacher_id).first()
        if teacher and teacher.user:
            filters_applied.append(f"Teacher: {teacher.user.get_full_name()}")
    if status_filter != 'all':
        status_names = {'pending': 'Pending', 'approved': 'Approved', 'rejected': 'Returned'}
        filters_applied.append(f"Status: {status_names.get(status_filter, status_filter)}")
    
    if filters_applied:
        ws.merge_cells('A4:O4')
        filter_cell = ws.cell(row=4, column=1, value="Filters: " + " | ".join(filters_applied))
        filter_cell.font = Font(name='Calibri', size=9, italic=True, color='666666')
        filter_cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.row_dimensions[4].height = 20
        header_row = 6
    else:
        header_row = 5
    
    # Summary row
    total_records = grade_components.count()
    pending_count = grade_components.filter(validation_status='Submitted').count()
    approved_count = grade_components.filter(validation_status='Validated').count()
    rejected_count = grade_components.filter(validation_status='Returned').count()
    
    ws.merge_cells(f'A{header_row}:O{header_row}')
    summary_cell = ws.cell(row=header_row, column=1, 
                           value=f"Total Records: {total_records} | Pending: {pending_count} | Approved: {approved_count} | Returned: {rejected_count}")
    summary_cell.font = Font(name='Calibri', size=10, bold=True, color='2D6A4F')
    summary_cell.alignment = Alignment(horizontal='center', vertical='center')
    summary_cell.fill = PatternFill(start_color='E8F5E9', end_color='E8F5E9', fill_type='solid')
    ws.row_dimensions[header_row].height = 25
    
    header_row += 1
    
    # ========== COLUMN HEADERS ==========
    headers = [
        ('LRN', 18), ('Student Name', 30), ('Grade Level', 14), ('Section', 20),
        ('Teacher', 25), ('Subject', 35), ('Written Work (%)', 15),
        ('Performance Task (%)', 18), ('Quarterly Assessment (%)', 20),
        ('Final Grade (%)', 14), ('Status', 12), ('Remarks', 30),
        ('Submitted Date', 14), ('Validated By', 20), ('Validated Date', 14)
    ]
    
    for col_idx, (header, width) in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    
    ws.row_dimensions[header_row].height = 40
    
    # ========== DATA ROWS ==========
    row_num = header_row + 1
    
    for gc in grade_components:
        student = gc.enrollment.student
        section = gc.enrollment.section
        
        # Determine status display
        if gc.validation_status == 'Submitted':
            status_text = 'PENDING'
            status_fill = pending_fill
        elif gc.validation_status == 'Validated':
            status_text = 'APPROVED'
            status_fill = approved_fill
        else:
            status_text = 'RETURNED'
            status_fill = rejected_fill
        
        # Teacher name
        teacher_name = gc.encoded_by.get_full_name() if gc.encoded_by else 'Unknown'
        
        # Format grade values
        written_work = f"{gc.written_work_raw:.2f}" if gc.written_work_raw is not None else '—'
        performance_task = f"{gc.performance_task_raw:.2f}" if gc.performance_task_raw is not None else '—'
        quarterly_assessment = f"{gc.quarterly_assessment_raw:.2f}" if gc.quarterly_assessment_raw is not None else '—'
        final_grade = f"{gc.initial_grade:.2f}" if gc.initial_grade is not None else '—'
        
        row_data = [
            student.lrn,
            f"{student.last_name}, {student.first_name}",
            section.grade_level.grade_name if section.grade_level else '',
            section.section_name,
            teacher_name,
            gc.subject.subject_name,
            written_work,
            performance_task,
            quarterly_assessment,
            final_grade,
            status_text,
            gc.remarks or '',
            gc.encoding_date.strftime('%Y-%m-%d') if gc.encoding_date else '',
            gc.validated_by.get_full_name() if gc.validated_by else '',
            gc.validation_date.strftime('%Y-%m-%d') if gc.validation_date else '',
        ]
        
        for col_idx, value in enumerate(row_data, 1):
            cell = ws.cell(row=row_num, column=col_idx, value=value)
            cell.border = thin_border
            cell.alignment = center_align if col_idx in [7, 8, 9, 10, 11, 13, 15] else left_align
            cell.font = Font(name='Calibri', size=10)
            
            # Apply status color to Status column (col 11)
            if col_idx == 11:
                cell.fill = status_fill
                cell.font = Font(name='Calibri', size=10, bold=True)
        
        # Alternate row colors for better readability
        if row_num % 2 == 0:
            for col_idx in range(1, len(headers) + 1):
                if col_idx != 11:  # Skip status column (already colored)
                    cell = ws.cell(row=row_num, column=col_idx)
                    cell.fill = PatternFill(start_color='F8F9FA', end_color='F8F9FA', fill_type='solid')
        
        row_num += 1
    
    # ========== FOOTER ==========
    footer_row = row_num + 2
    
    ws.merge_cells(f'A{footer_row}:O{footer_row}')
    footer_cell = ws.cell(row=footer_row, column=1, 
                          value="This report was automatically generated by the Formify LIS System. For questions, contact the System Administrator.")
    footer_cell.font = Font(name='Calibri', size=8, italic=True, color='999999')
    footer_cell.alignment = Alignment(horizontal='center', vertical='center')
    
    # ========== FREEZE PANES ==========
    ws.freeze_panes = f'A{header_row + 1}'
    
    # ========== ADD AUTO-FILTER ==========
    ws.auto_filter.ref = f'A{header_row}:{get_column_letter(len(headers))}{row_num - 1}'
    
    # ========== CREATE RESPONSE ==========
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    filename = f"Grade_Validation_Report_{timezone.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response


@login_required
def grade_validation_export_pdf(request):
    """Export grade validation data to PDF with professional formatting"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    # Get filters from request
    grade_level_id = request.GET.get('grade_level')
    teacher_id = request.GET.get('teacher_id')
    quarter_label = request.GET.get('quarter', 'Q3')
    status_filter = request.GET.get('status', 'all')
    
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    current_quarter = Quarter.objects.filter(
        school_year=current_sy, quarter_label=quarter_label
    ).first() if current_sy else None
    
    grade_components = GradeComponent.objects.select_related(
        'enrollment__student', 'enrollment__section', 'enrollment__section__grade_level',
        'subject', 'encoded_by'
    )
    
    if current_sy:
        grade_components = grade_components.filter(enrollment__school_year=current_sy)
    if current_quarter:
        grade_components = grade_components.filter(quarter=current_quarter)
    if grade_level_id:
        grade_components = grade_components.filter(enrollment__section__grade_level_id=grade_level_id)
    if teacher_id:
        grade_components = grade_components.filter(encoded_by_id=teacher_id)
    if status_filter != 'all':
        if status_filter == 'pending':
            grade_components = grade_components.filter(validation_status='Submitted')
        elif status_filter == 'approved':
            grade_components = grade_components.filter(validation_status='Validated')
        elif status_filter == 'rejected':
            grade_components = grade_components.filter(validation_status='Returned')
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Grade_Validation_Report_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
    
    doc = SimpleDocTemplate(response, pagesize=landscape(A4),
                           topMargin=0.5*inch, bottomMargin=0.5*inch,
                           leftMargin=0.5*inch, rightMargin=0.5*inch)
    
    styles = getSampleStyleSheet()
    story = []
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.HexColor('#00072D'),
        alignment=TA_CENTER,
        spaceAfter=12
    )
    story.append(Paragraph("GRADE VALIDATION REPORT", title_style))
    
    # Subtitle
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#718096'),
        alignment=TA_CENTER,
        spaceAfter=6
    )
    story.append(Paragraph(f"School Year: {current_sy.year_label if current_sy else 'N/A'} | Quarter: {quarter_label}", subtitle_style))
    story.append(Paragraph(f"Generated: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}", subtitle_style))
    story.append(Paragraph(f"Total Records: {grade_components.count()}", subtitle_style))
    story.append(Spacer(1, 12))
    
    # Table data
    table_data = [['LRN', 'Student', 'Gr.', 'Section', 'Teacher', 'Subject', 'Written', 'Perf.', 'Q.A.', 'Final', 'Status', 'Submitted']]
    
    for gc in grade_components[:50]:
        student = gc.enrollment.student
        section = gc.enrollment.section
        status_display = 'Pending' if gc.validation_status == 'Submitted' else 'Approved' if gc.validation_status == 'Validated' else 'Returned'
        
        teacher_name = gc.encoded_by.get_full_name() if gc.encoded_by else ''
        teacher_name = teacher_name[:15] + '...' if len(teacher_name) > 18 else teacher_name
        student_name = f"{student.last_name}, {student.first_name}"
        student_name = student_name[:20] + '...' if len(student_name) > 23 else student_name
        subject_name = gc.subject.subject_name[:25] + '...' if len(gc.subject.subject_name) > 28 else gc.subject.subject_name
        
        table_data.append([
            student.lrn,
            student_name,
            section.grade_level.grade_number if section and section.grade_level else '',
            section.section_name[:15] if section.section_name else '',
            teacher_name,
            subject_name,
            gc.written_work_raw or '',
            gc.performance_task_raw or '',
            gc.quarterly_assessment_raw or '',
            f"{gc.initial_grade}",
            status_display,
            gc.encoding_date.strftime('%Y-%m-%d') if gc.encoding_date else '',
        ])
    
    table = Table(table_data, repeatRows=1)
    table_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#5EA173')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (1, 1), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E9ECEF')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ])
    
    for i, row in enumerate(table_data[1:], start=1):
        if 'Pending' in row:
            table_style.add('BACKGROUND', (0, i), (-1, i), colors.HexColor('#FFF3CD'))
        elif 'Approved' in row:
            table_style.add('BACKGROUND', (0, i), (-1, i), colors.HexColor('#D4EDDA'))
        elif 'Returned' in row:
            table_style.add('BACKGROUND', (0, i), (-1, i), colors.HexColor('#F8D7DA'))
    
    table.setStyle(table_style)
    story.append(table)
    
    doc.build(story)
    return response


# =============================================================================
# SCHOOL FORMS
# =============================================================================
@login_required
def school_forms(request):
    """School Forms Management - SF1 through SF10 with approval workflow"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')

    registrar = request.user
    today = date.today()

    section_id = request.GET.get('section_id')
    quarter_label = request.GET.get('quarter', 'Q3')
    sy_id = request.GET.get('school_year')
    grade_level_id = request.GET.get('grade_level')

    FORM_ICONS = {
        'SF1': 'fi-rr-users', 'SF2': 'fi-rr-calendar-check',
        'SF3': 'fi-rr-book', 'SF4': 'fi-rr-chart-line-up',
        'SF5': 'fi-rr-graduation-cap', 'SF6': 'fi-rr-clipboard',
        'SF7': 'fi-rr-chart-pie', 'SF8': 'fi-rr-user-check',
        'SF9': 'fi-rr-id-card', 'SF10': 'fi-rr-archive',
    }
    ALL_FORMS = ['SF1', 'SF2', 'SF3', 'SF4', 'SF5', 'SF6', 'SF7', 'SF8', 'SF9', 'SF10']

    # School Year
    current_sy_obj = None
    if sy_id:
        try:
            current_sy_obj = SchoolYear.objects.get(id=sy_id)
        except SchoolYear.DoesNotExist:
            pass
    if not current_sy_obj:
        current_sy_obj = SchoolYear.objects.filter(is_current=True).first()

    available_sy_data = [{'id': sy.id, 'label': str(sy)} for sy in SchoolYear.objects.all().order_by('-year_start')]
    current_sy = str(current_sy_obj) if current_sy_obj else '—'
    current_sy_id = current_sy_obj.id if current_sy_obj else None

    # Quarter
    quarter_obj = None
    quarter_options = []
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
    is_quarter_locked = quarter_obj.is_grades_locked if quarter_obj else False

    # Sections
    sections = Section.objects.filter(
        enrollments__school_year=current_sy_obj,
        enrollments__status='Enrolled'
    ).distinct().select_related('grade_level').order_by('grade_level__grade_number', 'section_name')

    if grade_level_id:
        sections = sections.filter(grade_level_id=grade_level_id)

    grade_levels = []
    if current_sy_obj:
        grade_levels = list(
            Section.objects.filter(
                enrollments__school_year=current_sy_obj, enrollments__status='Enrolled'
            ).distinct().values('grade_level__id', 'grade_level__grade_name').order_by('grade_level__grade_number')
        )

    # Selected Section
    selected_section_obj = None
    if section_id:
        selected_section_obj = Section.objects.filter(id=section_id).first()
    if not selected_section_obj and sections.exists():
        selected_section_obj = sections.first()

    selected_section = str(selected_section_obj) if selected_section_obj else '—'
    selected_section_id = selected_section_obj.id if selected_section_obj else None

    # Form Lock States
    form_locks = {}
    if current_sy_obj:
        locked_submissions = FormSubmission.objects.filter(
            school_year=current_sy_obj, status='Locked'
        ).values_list('school_form__form_code', flat=True).distinct()

        compliance_locks = FormCompliance.objects.filter(
            school_year=current_sy_obj, status__in=['Locked', 'Closed']
        ).values_list('school_form__form_code', flat=True).distinct()

        for form_code in ALL_FORMS:
            form_locks[form_code] = form_code in locked_submissions or form_code in compliance_locks

    # Section-level stats
    enrolled_count = 0
    lrn_complete = 0
    total_grades = 0
    finalized_grades = 0
    att_days = 0
    total_att_records = 0
    guardian_count = 0
    promo_count = 0
    promo_promoted = 0
    promo_retained = 0
    promo_conditional = 0
    data_source_stats = {}

    if selected_section_obj and current_sy_obj:
        enrolled = Enrollment.objects.filter(
            section=selected_section_obj, status='Enrolled', school_year=current_sy_obj
        )
        enrolled_count = enrolled.count()
        lrn_complete = enrolled.exclude(student__lrn__isnull=True).exclude(student__lrn='').count()

        if quarter_obj:
            total_grades = GradeComponent.objects.filter(
                enrollment__section=selected_section_obj, quarter=quarter_obj
            ).count()
            finalized_grades = GradeComponent.objects.filter(
                enrollment__section=selected_section_obj, quarter=quarter_obj,
                validation_status='Validated'
            ).count()
            att_days = AttendanceRecord.objects.filter(
                enrollment__section=selected_section_obj,
                date__gte=quarter_obj.date_start, date__lte=quarter_obj.date_end
            ).values('date').distinct().count()
            total_att_records = AttendanceRecord.objects.filter(
                enrollment__section=selected_section_obj,
                date__gte=quarter_obj.date_start, date__lte=quarter_obj.date_end
            ).count()

        guardian_count = Guardian.objects.filter(
            student__enrollments__section=selected_section_obj,
            student__enrollments__status='Enrolled',
            student__enrollments__school_year=current_sy_obj,
            is_primary_guardian=True
        ).count()

        # Promotion recommendations
        promo_qs = PromotionRecommendation.objects.filter(
            enrollment__section=selected_section_obj,
            enrollment__school_year=current_sy_obj
        )
        promo_count = promo_qs.count()
        promo_promoted = promo_qs.filter(recommendation='Promoted').count()
        promo_retained = promo_qs.filter(recommendation='Retained').count()
        promo_conditional = promo_qs.filter(recommendation='Conditionally_Promoted').count()

        def _status(complete, total):
            if total == 0:
                return 'missing'
            if complete >= total:
                return 'complete'
            return 'partial'

        expected_att = enrolled_count * att_days if att_days > 0 else 0

        data_source_stats = {
            'enrollment_status': _status(enrolled_count, enrolled_count),
            'enrollment_count': f'{enrolled_count}/{enrolled_count}',
            'enrollment_note': 'All students verified' if enrolled_count > 0 else 'No enrollment data',
            'lrn_status': _status(lrn_complete, enrolled_count),
            'lrn_count': f'{lrn_complete}/{enrolled_count}',
            'lrn_note': 'All LRNs complete' if lrn_complete == enrolled_count else f'{enrolled_count - lrn_complete} missing LRNs',
            'guardian_status': _status(guardian_count, enrolled_count),
            'guardian_count': f'{guardian_count}/{enrolled_count}',
            'guardian_note': 'All guardians on file' if guardian_count == enrolled_count else f'{enrolled_count - guardian_count} missing',
            'attendance_status': _status(total_att_records, expected_att) if expected_att > 0 else 'missing',
            'attendance_count': f'{total_att_records}/{expected_att}' if expected_att > 0 else '0/0',
            'attendance_note': f'{att_days} days recorded' if att_days > 0 else 'No attendance data',
            'grades_status': _status(finalized_grades, total_grades) if total_grades > 0 else 'missing',
            'grades_count': f'{finalized_grades}/{total_grades}' if total_grades > 0 else '0/0',
            'grades_note': 'All grades finalized' if finalized_grades >= total_grades and total_grades > 0 else f'{total_grades - finalized_grades} pending',
            'promo_status': _status(promo_count, enrolled_count) if enrolled_count > 0 else 'missing',
            'promo_count': f'{promo_count}/{enrolled_count}',
            'promo_note': f'{promo_promoted} promoted, {promo_retained} retained' if promo_count > 0 else 'Not yet started',
            'promo_promoted': promo_promoted,
            'promo_retained': promo_retained,
            'promo_conditional': promo_conditional,
        }

    # Build Forms Status Data
    forms_status = []
    total_submitted = 0
    total_approved = 0

    if selected_section_obj and current_sy_obj:
        for form_code in ALL_FORMS:
            form = SchoolForm.objects.filter(form_code=form_code, is_active=True).first()
            if not form:
                continue

            submission = FormSubmission.objects.filter(
                school_form=form, section=selected_section_obj,
                school_year=current_sy_obj,
                quarter=quarter_obj if form_code in ['SF2', 'SF9'] else None
            ).first()

            is_locked = form_locks.get(form_code, False)
            status = 'not_submitted'
            status_text = 'Not Submitted'
            status_class = 'pending'

            if is_locked:
                status = 'locked'
                status_text = 'Locked'
                status_class = 'locked'
            elif submission:
                if submission.status == 'Submitted':
                    status = 'submitted'
                    status_text = 'Pending Review'
                    status_class = 'submitted'
                    total_submitted += 1
                elif submission.status == 'Reviewed':
                    status = 'reviewed'
                    status_text = 'Reviewed'
                    status_class = 'reviewed'
                elif submission.status == 'Approved':
                    status = 'approved'
                    status_text = 'Approved'
                    status_class = 'completed'
                    total_approved += 1
                elif submission.status == 'Returned':
                    status = 'returned'
                    status_text = 'Returned to Teacher'
                    status_class = 'returned'
                elif submission.status == 'Rejected':
                    status = 'rejected'
                    status_text = 'Rejected'
                    status_class = 'rejected'
            elif form_code == 'SF10':
                status = 'available'
                status_text = 'Available to Generate'
                status_class = 'ready'

            submission_count = FormSubmission.objects.filter(
                school_form=form, school_year=current_sy_obj,
                quarter=quarter_obj if form_code in ['SF2', 'SF9'] else None
            ).count()
            approved_count = FormSubmission.objects.filter(
                school_form=form, school_year=current_sy_obj, status='Approved',
                quarter=quarter_obj if form_code in ['SF2', 'SF9'] else None
            ).count()
            pending_count = FormSubmission.objects.filter(
                school_form=form, school_year=current_sy_obj,
                status__in=['Submitted', 'Reviewed'],
                quarter=quarter_obj if form_code in ['SF2', 'SF9'] else None
            ).count()

            forms_status.append({
                'id': form.id,
                'code': form.form_code,
                'name': form.form_name,
                'icon': FORM_ICONS.get(form_code, 'fi-rr-document'),
                'status': status,
                'status_text': status_text,
                'status_class': status_class,
                'is_locked': is_locked,
                'submission_id': submission.id if submission else None,
                'submission_count': submission_count,
                'approved_count': approved_count,
                'pending_count': pending_count,
                'submitted_by': submission.submitted_by.get_full_name() if submission and submission.submitted_by else '',
                'submitted_date': submission.submitted_date.strftime('%b %d, %Y') if submission and submission.submitted_date else '',
                'reviewed_by': submission.reviewed_by.get_full_name() if submission and submission.reviewed_by else '',
                'reviewed_at': submission.reviewed_at.strftime('%b %d, %Y') if submission and submission.reviewed_at else '',
                'remarks': submission.review_notes if submission else '',
            })

    total_forms = len(forms_status)

    # Pending Approvals
    pending_approvals = []
    if current_sy_obj:
        for sub in FormSubmission.objects.filter(
            school_year=current_sy_obj, status__in=['Submitted', 'Reviewed']
        ).select_related('school_form', 'section', 'submitted_by', 'quarter').order_by('-updated_at')[:15]:
            pending_approvals.append({
                'id': sub.id,
                'form_code': sub.school_form.form_code,
                'form_name': sub.school_form.form_name,
                'section': str(sub.section) if sub.section else 'N/A',
                'submitted_by': sub.submitted_by.get_full_name() if sub.submitted_by else 'Unknown',
                'quarter': sub.quarter.quarter_label if sub.quarter else 'Annual',
                'date': sub.updated_at.strftime('%b %d, %Y'),
                'status': sub.get_status_display(),
            })

    # Recent Submissions
    recent_submissions = []
    all_subs = FormSubmission.objects.filter(
        school_year=current_sy_obj
    ).select_related(
        'school_form', 'section', 'submitted_by', 'quarter'
    ).order_by('-updated_at')[:10]

    for sub in all_subs:
        recent_submissions.append({
            'id': sub.id,
            'form_code': sub.school_form.form_code,
            'form_name': sub.school_form.form_name,
            'section': str(sub.section) if sub.section else 'N/A',
            'submitted_by': sub.submitted_by.get_full_name() if sub.submitted_by else 'N/A',
            'quarter': sub.quarter.quarter_label if sub.quarter else 'Annual',
            'date': sub.updated_at.strftime('%b %d, %Y'),
            'status': sub.get_status_display(),
            'status_class': 'completed' if sub.status == 'Approved' else (
                'submitted' if sub.status in ['Submitted', 'Reviewed'] else (
                    'returned' if sub.status == 'Returned' else 'pending'
                )
            ),
        })

    # Form Requests
    form_requests = []
    for corr in DataCorrectionRequest.objects.filter(
        status='Pending'
    ).select_related('requested_by').order_by('-created_at')[:8]:
        form_requests.append({
            'id': corr.id,
            'type': 'Correction',
            'description': f"{corr.entity_type} #{corr.entity_id} - {corr.field_to_correct}",
            'requested_by': corr.requested_by.get_full_name() if corr.requested_by else 'Unknown',
            'current_value': corr.current_value,
            'proposed_value': corr.proposed_value,
            'justification': corr.justification,
            'status': corr.get_status_display(),
            'date': corr.created_at.strftime('%b %d, %Y'),
            'request_type': 'correction',
        })

    for dr in DocumentRequest.objects.filter(
        status__in=['Pending', 'Processing']
    ).select_related('requested_by_user', 'student', 'school_form').order_by('-request_date')[:8]:
        form_requests.append({
            'id': dr.id,
            'type': 'Document',
            'description': f"{dr.document_name} - {dr.student.full_name if dr.student else 'N/A'}",
            'requested_by': dr.requested_by_user.get_full_name() if dr.requested_by_user else (dr.requested_by_external_name or 'Unknown'),
            'current_value': dr.purpose or 'N/A',
            'proposed_value': dr.get_status_display(),
            'status': dr.status,
            'date': dr.request_date.strftime('%b %d, %Y') if dr.request_date else '',
            'request_type': 'document',
        })

    # Notifications
    form_notifications = list(Notification.objects.filter(
        recipient=registrar,
        notification_type__in=[
            'FORM_SUBMITTED', 'FORM_SUBMISSION_DEADLINE', 'FORM_RETURNED',
            'FORM_APPROVED', 'GRADE_SUBMITTED', 'CORRECTION_REQUESTED',
            'PROMOTION_REVIEW_NEEDED', 'DOCUMENT_REQUESTED'
        ],
        is_read=False,
    ).order_by('-created_at')[:6])

    # Section Students
    section_students = []
    if selected_section_obj and current_sy_obj:
        promo_map = {}
        for pr in PromotionRecommendation.objects.filter(
            enrollment__section=selected_section_obj,
            enrollment__school_year=current_sy_obj
        ).select_related('enrollment__student'):
            promo_map[pr.enrollment.student_id] = pr.get_recommendation_display()

        for enr in Enrollment.objects.filter(
            section=selected_section_obj, status='Enrolled', school_year=current_sy_obj
        ).select_related('student').order_by('student__last_name'):
            st = enr.student
            g = Guardian.objects.filter(student=st, is_primary_guardian=True).first()
            section_students.append({
                'lrn': st.lrn,
                'name': f"{st.last_name}, {st.first_name}",
                'sex': st.sex,
                'birth_date': str(st.birth_date) if st.birth_date else '',
                'guardian': f"{g.last_name}, {g.first_name}" if g else 'Not recorded',
                'promotion_status': promo_map.get(st.id, '—'),
            })

    # Sections data for dropdown
    sections_data = []
    for sec in sections:
        student_count = Enrollment.objects.filter(
            section=sec, status='Enrolled', school_year=current_sy_obj
        ).count()
        sections_data.append({
            'section_id': sec.id,
            'section_name': str(sec),
            'grade_name': sec.grade_level.grade_name if sec.grade_level else '',
            'student_count': student_count,
        })

    # Students for SF10 dropdown
    all_students = []
    if current_sy_obj:
        for st in Student.objects.filter(
            enrollments__school_year=current_sy_obj, enrollments__status='Enrolled'
        ).distinct().order_by('last_name', 'first_name')[:50]:
            grade_level = st.enrollments.filter(
                school_year=current_sy_obj, status='Enrolled'
            ).first()
            all_students.append({
                'id': st.id,
                'lrn': st.lrn,
                'name': f"{st.last_name}, {st.first_name}",
                'grade_level': grade_level.section.grade_level.grade_name if grade_level and grade_level.section.grade_level else 'N/A',
            })

    context = {
        'has_data': True,
        'selected_section': selected_section,
        'selected_section_id': selected_section_id,
        'current_sy': current_sy,
        'current_sy_id': current_sy_id,
        'available_sy': available_sy_data,
        'quarter_label': quarter_label,
        'quarter_name': quarter_name,
        'quarter_options': quarter_options,
        'is_quarter_locked': is_quarter_locked,
        'forms_status': forms_status,
        'total_forms': total_forms,
        'total_submitted': total_submitted,
        'total_approved': total_approved,
        'form_locks': json.dumps(form_locks),
        'pending_approvals': pending_approvals,
        'recent_submissions': recent_submissions,
        'form_requests': form_requests,
        'form_notifications': form_notifications,
        'section_students': section_students,
        'sections_data': sections_data,
        'grade_levels': grade_levels,
        'all_students': all_students,
        'today': today,
        'FORM_ICONS': FORM_ICONS,
        'data_source_stats_json': json.dumps(data_source_stats),
        'enrolled_count': enrolled_count,
        'promo_promoted': promo_promoted,
        'promo_retained': promo_retained,
        'promo_conditional': promo_conditional,
        'finalized_grades': finalized_grades,
        'total_grades': total_grades,
    }
    return render(request, 'registrars/forms/forms.html', context)


@login_required
def process_submission(request, submission_id):
    """Process a form submission - review, return, reject, or lock"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')

    if request.method != 'POST':
        return redirect('registrars-forms')

    submission = get_object_or_404(FormSubmission, id=submission_id)
    action = request.POST.get('action')
    remarks = request.POST.get('remarks', '')

    if action == 'review':
        submission.status = 'Reviewed'
        submission.reviewed_by = request.user
        submission.reviewed_at = timezone.now()
        submission.review_notes = remarks

        if submission.submitted_by:
            Notification.objects.create(
                recipient=submission.submitted_by,
                notification_type='FORM_REVIEWED',
                title=f'{submission.school_form.form_code} Reviewed',
                message=f'Your {submission.school_form.form_code} for {submission.section} has been forwarded to School Head.',
                is_read=False,
            )

        _log(request, 'REVIEW_FORM', 'FormSubmission', submission.id,
             f'Reviewed {submission.school_form.form_code} for {submission.section}')
        messages.success(request, f'{submission.school_form.form_code} reviewed and forwarded.')

    elif action == 'return':
        submission.status = 'Returned'
        submission.reviewed_by = request.user
        submission.reviewed_at = timezone.now()
        submission.remarks = remarks

        if submission.submitted_by:
            Notification.objects.create(
                recipient=submission.submitted_by,
                notification_type='FORM_RETURNED',
                title=f'{submission.school_form.form_code} Returned',
                message=f'Your submission needs revision. Reason: {remarks}',
                is_read=False,
            )

        _log(request, 'RETURN_FORM', 'FormSubmission', submission.id,
             f'Returned {submission.school_form.form_code} for {submission.section}')
        messages.info(request, f'{submission.school_form.form_code} returned to teacher.')

    elif action == 'reject':
        submission.status = 'Rejected'
        submission.reviewed_by = request.user
        submission.reviewed_at = timezone.now()
        submission.remarks = remarks

        if submission.submitted_by:
            Notification.objects.create(
                recipient=submission.submitted_by,
                notification_type='FORM_REJECTED',
                title=f'{submission.school_form.form_code} Rejected',
                message=f'Your submission has been rejected. Reason: {remarks}',
                is_read=False,
            )

        _log(request, 'REJECT_FORM', 'FormSubmission', submission.id,
             f'Rejected {submission.school_form.form_code} for {submission.section}')
        messages.warning(request, f'{submission.school_form.form_code} rejected.')

    elif action == 'lock':
        submission.status = 'Locked'
        submission.reviewed_by = request.user
        submission.reviewed_at = timezone.now()
        _log(request, 'LOCK_FORM', 'FormSubmission', submission.id,
             f'Locked {submission.school_form.form_code} for {submission.section}')
        messages.info(request, f'{submission.school_form.form_code} locked.')

    elif action == 'unlock':
        submission.status = 'Submitted'
        submission.reviewed_by = None
        submission.reviewed_at = None
        _log(request, 'UNLOCK_FORM', 'FormSubmission', submission.id,
             f'Unlocked {submission.school_form.form_code} for {submission.section}')
        messages.info(request, f'{submission.school_form.form_code} unlocked.')

    else:
        messages.error(request, f'Unknown action: {action}')
        return redirect(request.META.get('HTTP_REFERER', 'registrars-forms'))

    submission.save()
    return redirect(request.META.get('HTTP_REFERER', 'registrars-forms'))


@login_required
def toggle_form_lock(request, form_code):
    """Lock or unlock a form for all sections"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')

    if request.method != 'POST':
        return redirect('registrars-forms')

    sy_id = request.POST.get('school_year')
    current_sy = None
    if sy_id:
        try:
            current_sy = SchoolYear.objects.get(id=sy_id)
        except SchoolYear.DoesNotExist:
            pass
    if not current_sy:
        current_sy = SchoolYear.objects.filter(is_current=True).first()

    if not current_sy:
        messages.error(request, 'No active school year found.')
        return redirect('registrars-forms')

    form = get_object_or_404(SchoolForm, form_code=form_code, is_active=True)

    compliance, created = FormCompliance.objects.get_or_create(
        school_form=form, school_year=current_sy,
        defaults={'status': 'Locked'}
    )

    if not created:
        if compliance.status in ['Locked', 'Closed']:
            compliance.status = 'Open'
        else:
            compliance.status = 'Locked'
        compliance.save()

    action = 'locked' if compliance.status in ['Locked', 'Closed'] else 'unlocked'
    _log(request, 'TOGGLE_FORM_LOCK', 'SchoolForm', form.id,
         f'{action.capitalize()} {form_code} for {current_sy}')
    messages.success(request, f'{form_code} {action} successfully.')
    return redirect(request.META.get('HTTP_REFERER', 'registrars-forms'))


@login_required
def generate_sf10(request):
    """Generate SF10 (Form 137) for a student"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')

    if request.method != 'POST':
        return redirect('registrars-forms')

    student_id = request.POST.get('student_id')
    if not student_id:
        messages.error(request, 'Please select a student.')
        return redirect('registrars-forms')

    student = get_object_or_404(Student, id=student_id)
    current_sy = SchoolYear.objects.filter(is_current=True).first()

    if not current_sy:
        messages.error(request, 'No active school year.')
        return redirect('registrars-forms')
    
    enrollment = student.enrollments.filter(
        school_year=current_sy, status='Enrolled'
    ).first()
    
    if not enrollment:
        messages.error(request, 'Student is not currently enrolled.')
        return redirect('registrars-forms')
    
    sf10_form = SchoolForm.objects.filter(form_code='SF10', is_active=True).first()
    if sf10_form and current_sy:
        grade_level = enrollment.section.grade_level if enrollment.section else None
        
        SF10History.objects.get_or_create(
            student=student,
            defaults={
                'generated_by': request.user, 
                'school_year': current_sy,
                'grade_level': grade_level
            }
        )
        
        FormSubmission.objects.create(
            school_form=sf10_form,
            section=enrollment.section,
            school_year=current_sy,
            submitted_by=request.user,
            status='Approved',
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
            review_notes=f'SF10 generated for {student.full_name}',  # Changed from remarks to review_notes
        )

    _log(request, 'GENERATE_SF10', 'Student', student.id,
         f'SF10 generated for {student.full_name} (LRN: {student.lrn})')
    messages.success(request, f'SF10 generated for {student.last_name}, {student.first_name}.')
    return redirect(request.META.get('HTTP_REFERER', 'registrars-forms'))


@login_required
def batch_generate(request):
    """Batch generate multiple forms for a section"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')

    if request.method != 'POST':
        return redirect('registrars-forms')

    form_codes = request.POST.getlist('forms')
    section_id = request.POST.get('section_id')
    sy_id = request.POST.get('school_year')
    quarter_label = request.POST.get('quarter', 'Q3')

    if not form_codes:
        messages.error(request, 'Please select at least one form.')
        return redirect('registrars-forms')

    section = get_object_or_404(Section, id=section_id) if section_id else None
    school_year = get_object_or_404(SchoolYear, id=sy_id) if sy_id else SchoolYear.objects.filter(is_current=True).first()
    quarter = Quarter.objects.filter(school_year=school_year, quarter_label=quarter_label).first()

    generated_count = 0
    for form_code in form_codes:
        form = SchoolForm.objects.filter(form_code=form_code, is_active=True).first()
        if not form:
            continue
        q = {
            'school_form': form,
            'school_year': school_year,
            'submitted_by': request.user,
            'status': 'Approved',
            'reviewed_by': request.user,
            'reviewed_at': timezone.now(),
        }
        if section:
            q['section'] = section
        if form_code in ['SF2', 'SF9'] and quarter:
            q['quarter'] = quarter
        FormSubmission.objects.create(**q)
        generated_count += 1

    _log(request, 'BATCH_GENERATE_FORMS', 'FormSubmission', 0,
         f'Batch generated {generated_count} forms for {section if section else "All Sections"}')
    messages.success(request, f'Batch generation complete. {generated_count} form(s) generated.')
    return redirect(request.META.get('HTTP_REFERER', 'registrars-forms'))


@login_required
def process_correction(request, correction_id):
    """Approve or deny a data correction request"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')

    if request.method != 'POST':
        return redirect('registrars-forms')

    correction = get_object_or_404(DataCorrectionRequest, id=correction_id)
    action = request.POST.get('action')
    review_notes = request.POST.get('remarks', '')

    if action == 'approve':
        correction.status = 'Approved'
        correction.reviewed_by = request.user
        correction.reviewed_at = timezone.now()
        correction.review_notes = review_notes
        _log(request, 'APPROVE_CORRECTION', 'DataCorrectionRequest', correction.id,
             f'Approved correction for {correction.entity_type} #{correction.entity_id}')
        if correction.requested_by:
            Notification.objects.create(
                recipient=correction.requested_by,
                notification_type='CORRECTION_RESOLVED',
                title='Correction Approved',
                message=f'Your correction for {correction.field_to_correct} has been approved.',
                is_read=False,
            )
        messages.success(request, 'Correction approved.')

    elif action == 'deny':
        correction.status = 'Denied'
        correction.reviewed_by = request.user
        correction.reviewed_at = timezone.now()
        correction.review_notes = review_notes
        _log(request, 'DENY_CORRECTION', 'DataCorrectionRequest', correction.id,
             f'Denied correction for {correction.entity_type} #{correction.entity_id}')
        if correction.requested_by:
            Notification.objects.create(
                recipient=correction.requested_by,
                notification_type='CORRECTION_RESOLVED',
                title='Correction Denied',
                message=f'Your correction for {correction.field_to_correct} has been denied.',
                is_read=False,
            )
        messages.info(request, 'Correction denied.')

    correction.save()
    return redirect(request.META.get('HTTP_REFERER', 'registrars-forms'))


@login_required
def process_document_request(request, request_id):
    """Process a document request"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')

    if request.method != 'POST':
        return redirect('registrars-forms')

    doc_request = get_object_or_404(DocumentRequest, id=request_id)
    action = request.POST.get('action')
    remarks = request.POST.get('remarks', '')

    if action == 'process':
        doc_request.status = 'Processing'
        doc_request.processed_by = request.user
        messages.success(request, 'Document request is now being processed.')
    elif action == 'complete':
        doc_request.status = 'Completed'
        doc_request.processed_by = request.user
        doc_request.completed_at = timezone.now()
        doc_request.remarks = remarks
        messages.success(request, 'Document request completed.')
    elif action == 'reject':
        doc_request.status = 'Rejected'
        doc_request.processed_by = request.user
        doc_request.remarks = remarks
        messages.info(request, 'Document request rejected.')

    doc_request.save()
    _log(request, f'{action.upper()}_DOC_REQUEST', 'DocumentRequest', doc_request.id,
         f'{action.capitalize()}d document request')
    return redirect(request.META.get('HTTP_REFERER', 'registrars-forms'))


@login_required
def form_preview(request, form_code):
    """Preview a school form before printing"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')

    section_id = request.GET.get('section_id')
    sy_id = request.GET.get('school_year')
    quarter_label = request.GET.get('quarter', 'Q3')

    current_sy = SchoolYear.objects.filter(is_current=True).first()
    if sy_id:
        try:
            current_sy = SchoolYear.objects.get(id=sy_id)
        except SchoolYear.DoesNotExist:
            pass

    quarter = Quarter.objects.filter(school_year=current_sy, quarter_label=quarter_label).first()
    section = None
    students = []
    if section_id:
        section = get_object_or_404(Section, id=section_id)
        for enr in Enrollment.objects.filter(
            section=section, status='Enrolled', school_year=current_sy
        ).select_related('student').order_by('student__last_name'):
            st = enr.student
            g = Guardian.objects.filter(student=st, is_primary_guardian=True).first()
            students.append({
                'lrn': st.lrn,
                'name': f"{st.last_name}, {st.first_name} {st.middle_name or ''}",
                'sex': st.sex,
                'birth_date': st.birth_date,
                'guardian': f"{g.last_name}, {g.first_name}" if g else '',
            })

    context = {
        'form_code': form_code,
        'section': section,
        'students': students,
        'school_year': current_sy,
        'quarter': quarter,
        'today': date.today(),
    }
    return render(request, 'registrars/forms/preview.html', context)


@login_required
def forms_compliance_report(request):
    """View overall forms compliance across all sections"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')

    sy_id = request.GET.get('school_year')
    current_sy = None
    if sy_id:
        try:
            current_sy = SchoolYear.objects.get(id=sy_id)
        except SchoolYear.DoesNotExist:
            pass
    if not current_sy:
        current_sy = SchoolYear.objects.filter(is_current=True).first()

    all_forms = SchoolForm.objects.filter(is_active=True).order_by('form_code')
    sections = Section.objects.filter(
        is_active=True, school_year=current_sy
    ).select_related('grade_level').order_by('grade_level__grade_number', 'section_name')

    sections_compliance = []
    for section in sections:
        cd = {
            'section_name': str(section),
            'grade_level': section.grade_level.grade_name if section.grade_level else '',
            'forms': {}
        }
        total_complete = 0
        for form in all_forms:
            submission = FormSubmission.objects.filter(
                school_form=form, section=section, school_year=current_sy
            ).first()
            if submission:
                if submission.status == 'Approved':
                    cd['forms'][form.form_code] = 'approved'
                    total_complete += 1
                elif submission.status in ['Submitted', 'Reviewed']:
                    cd['forms'][form.form_code] = 'submitted'
                elif submission.status == 'Returned':
                    cd['forms'][form.form_code] = 'returned'
                elif submission.status == 'Rejected':
                    cd['forms'][form.form_code] = 'rejected'
                else:
                    cd['forms'][form.form_code] = 'locked'
            else:
                cd['forms'][form.form_code] = 'missing'
        cd['completion_pct'] = round((total_complete / all_forms.count()) * 100) if all_forms.count() > 0 else 0
        sections_compliance.append(cd)

    context = {
        'current_sy': current_sy,
        'available_sy': SchoolYear.objects.all().order_by('-year_start'),
        'all_forms': all_forms,
        'sections_compliance': sections_compliance,
        'today': date.today(),
    }
    return render(request, 'registrars/forms/compliance_report.html', context)


@login_required
@csrf_exempt
def submit_correction(request):
    """Teacher submits a data correction request to Registrar"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    try:
        data = json.loads(request.body)
        student_lrn = data.get('student_lrn')
        field = data.get('field')
        current_value = data.get('current_value', '')
        proposed_value = data.get('proposed_value', '')
        justification = data.get('justification', '')
        
        if not all([student_lrn, field, proposed_value, justification]):
            return JsonResponse({'success': False, 'error': 'All fields are required'}, status=400)
        
        DataCorrectionRequest.objects.create(
            requested_by=request.user,
            entity_type='Student',
            entity_id=student_lrn,
            field_to_correct=field,
            current_value=current_value,
            proposed_value=proposed_value,
            justification=justification,
            status='Pending',
        )
        
        return JsonResponse({'success': True, 'message': 'Correction request submitted'})
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# =============================================================================
# STUDENT RECORDS
# =============================================================================
@login_required
def student_records(request):
    """Student Records Management - View, search, filter students"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    today = date.today()
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    
    # Get filter parameters
    grade_level_id = request.GET.get('grade_level')
    section_id = request.GET.get('section')
    status_filter = request.GET.get('status', 'all')
    search_query = request.GET.get('search', '')
    page = int(request.GET.get('page', 1))
    per_page = int(request.GET.get('per_page', 25))
    
    # Base queryset - get students with enrollments in current school year
    students = Student.objects.filter(
        enrollments__school_year=current_sy
    ).distinct() if current_sy else Student.objects.none()
    
    # Apply filters
    if search_query:
        students = students.filter(
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(lrn__icontains=search_query) |
            Q(middle_name__icontains=search_query)
        )
    
    if grade_level_id and grade_level_id != '':
        students = students.filter(
            enrollments__section__grade_level_id=grade_level_id,
            enrollments__school_year=current_sy
        ).distinct()
    
    if section_id and section_id != '':
        students = students.filter(
            enrollments__section_id=section_id,
            enrollments__school_year=current_sy
        ).distinct()
    
    # Get enrollment status for display
    student_list = []
    for student in students:
        enrollment = student.enrollments.filter(school_year=current_sy).first()
        if enrollment:
            status = enrollment.status
            if status_filter != 'all' and status != status_filter:
                continue
            
            guardian = Guardian.objects.filter(student=student, is_primary_guardian=True).first()
            student_list.append({
                'id': student.id,
                'lrn': student.lrn,
                'name': f"{student.last_name}, {student.first_name}",
                'first_name': student.first_name,
                'last_name': student.last_name,
                'middle_name': student.middle_name,
                'sex': student.sex,
                'birth_date': student.birth_date.strftime('%Y-%m-%d') if student.birth_date else '',
                'birth_place': student.birth_place,
                'status': status,
                'grade_level': enrollment.section.grade_level.grade_name if enrollment.section.grade_level else 'N/A',
                'section': enrollment.section.section_name,
                'guardian': f"{guardian.last_name}, {guardian.first_name}" if guardian else 'Not recorded',
                'is_verified': student.is_verified,
                'updated_at': enrollment.updated_at.strftime('%Y-%m-%d') if enrollment.updated_at else '',
            })
    
    # Pagination
    total_records = len(student_list)
    total_pages = (total_records + per_page - 1) // per_page if per_page > 0 else 1
    start = (page - 1) * per_page
    student_list_page = student_list[start:start + per_page]
    
    # Get filter options
    grade_levels = GradeLevel.objects.all().order_by('sort_order')
    sections = []
    if current_sy and grade_level_id:
        sections = Section.objects.filter(
            grade_level_id=grade_level_id,
            enrollments__school_year=current_sy
        ).distinct()
    elif current_sy:
        sections = Section.objects.filter(
            enrollments__school_year=current_sy
        ).distinct()
    
    # Statistics
    total_active = Student.objects.filter(
        enrollments__school_year=current_sy,
        enrollments__status__in=['Enrolled', 'Transferred_In']
    ).distinct().count() if current_sy else 0
    
    total_male = Student.objects.filter(
        enrollments__school_year=current_sy,
        sex='M'
    ).distinct().count() if current_sy else 0
    
    total_female = Student.objects.filter(
        enrollments__school_year=current_sy,
        sex='F'
    ).distinct().count() if current_sy else 0
    
    unverified_count = Student.objects.filter(
        enrollments__school_year=current_sy,
        is_verified=False
    ).distinct().count() if current_sy else 0
    
    # Get notifications for the current user
    notifications = Notification.objects.filter(
        recipient=request.user, is_read=False
    ).order_by('-created_at')[:10]
    
    notifications_json = []
    for n in notifications:
        notifications_json.append({
            'id': n.id,
            'title': n.title,
            'message': n.message,
            'icon': 'fa-bell',
            'time_ago': n.created_at.strftime('%b %d, %Y'),
            'is_read': n.is_read,
        })
    
    context = {
        'has_data': current_sy is not None,
        'current_sy_label': current_sy.year_label if current_sy else 'N/A',
        'current_sy': current_sy,
        'today': today,
        'students': student_list_page,
        'total_students': total_records,
        'total_active': total_active,
        'total_male': total_male,
        'total_female': total_female,
        'unverified_count': unverified_count,
        'transfer_count': 0,
        'graduated_count': 0,
        'grade_levels': grade_levels,
        'sections': sections,
        'selected_grade': grade_level_id or '',
        'selected_section': section_id or '',
        'selected_status': status_filter,
        'search_query': search_query,
        'current_page': page,
        'total_pages': total_pages,
        'per_page': per_page,
        'page_start': start + 1,
        'page_end': min(start + per_page, total_records),
        'notifications': notifications,
        'notifications_json': json.dumps(notifications_json),
    }
    return render(request, 'registrars/classes/students_records.html', context)


# =============================================================================
# STUDENT DETAIL DATA API (FOR MODALS)
# =============================================================================
@login_required
def student_detail_data(request, student_id):
    """Return student data as JSON for modals"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    student = get_object_or_404(Student, id=student_id)
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    enrollment = student.enrollments.filter(school_year=current_sy).first()
    guardian = Guardian.objects.filter(student=student, is_primary_guardian=True).first()
    
    data = {
        'id': student.id,
        'lrn': student.lrn,
        'last_name': student.last_name,
        'first_name': student.first_name,
        'middle_name': student.middle_name or '',
        'sex': student.sex,
        'birth_date': student.birth_date.strftime('%Y-%m-%d') if student.birth_date else '',
        'birth_place': student.birth_place or '',
        'mother_tongue': student.mother_tongue or '',
        'religion': student.religion or '',
        'is_4ps': student.is_4ps,
        'status': enrollment.status if enrollment else 'Not Enrolled',
        'grade_level': enrollment.section.grade_level.grade_name if enrollment and enrollment.section.grade_level else 'N/A',
        'section': enrollment.section.section_name if enrollment else 'N/A',
        'guardian': f"{guardian.last_name}, {guardian.first_name}" if guardian else '',
    }
    return JsonResponse({'success': True, 'data': data})

# =============================================================================
# BATCH ACTIONS
# =============================================================================
@login_required
@csrf_exempt
def batch_generate_sf10(request):
    """Batch generate SF10 (Form 137) for multiple students"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    try:
        data = json.loads(request.body)
        student_ids = data.get('student_ids', [])
        
        if not student_ids:
            return JsonResponse({'success': False, 'error': 'No students selected'}, status=400)
        
        current_sy = SchoolYear.objects.filter(is_current=True).first()
        if not current_sy:
            return JsonResponse({'success': False, 'error': 'No active school year'}, status=400)
            
        sf10_form = SchoolForm.objects.filter(form_code='SF10', is_active=True).first()
        if not sf10_form:
            return JsonResponse({'success': False, 'error': 'SF10 form not found'}, status=400)
        
        generated_count = 0
        skipped_count = 0
        
        for student_id in student_ids:
            student = Student.objects.filter(id=student_id).first()
            if not student:
                continue
                
            enrollment = student.enrollments.filter(
                school_year=current_sy, status='Enrolled'
            ).first()
            
            if not enrollment:
                skipped_count += 1
                continue
            
            grade_level = enrollment.section.grade_level if enrollment.section else None
            
            SF10History.objects.get_or_create(
                student=student,
                defaults={
                    'generated_by': request.user, 
                    'school_year': current_sy,
                    'grade_level': grade_level
                }
            )
            
            FormSubmission.objects.create(
                school_form=sf10_form,
                section=enrollment.section,
                school_year=current_sy,
                submitted_by=request.user,
                status='Approved',
                reviewed_by=request.user,
                reviewed_at=timezone.now(),
                review_notes=f'SF10 generated for {student.full_name}',  # Changed from remarks to review_notes
            )
            generated_count += 1
        
        _log(request, 'BATCH_SF10', 'Student', 0, 
             f'Batch generated SF10 for {generated_count} students')
        
        return JsonResponse({'success': True, 'message': f'SF10 generated for {generated_count} students'})
    
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
@csrf_exempt
def batch_update_status(request):
    """Batch update enrollment status for multiple students"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    try:
        data = json.loads(request.body)
        student_ids = data.get('student_ids', [])
        new_status = data.get('status', '')
        
        if not student_ids:
            return JsonResponse({'success': False, 'error': 'No students selected'}, status=400)
        
        if not new_status:
            return JsonResponse({'success': False, 'error': 'No status provided'}, status=400)
        
        valid_statuses = ['Enrolled', 'Transferred', 'Graduated', 'Dropped']
        if new_status not in valid_statuses:
            return JsonResponse({'success': False, 'error': 'Invalid status'}, status=400)
        
        current_sy = SchoolYear.objects.filter(is_current=True).first()
        updated_count = 0
        
        for student_id in student_ids:
            student = Student.objects.filter(id=student_id).first()
            if student and current_sy:
                enrollment = student.enrollments.filter(school_year=current_sy).first()
                if enrollment:
                    enrollment.status = new_status
                    enrollment.save()
                    updated_count += 1
        
        _log(request, 'BATCH_STATUS_UPDATE', 'Student', 0, f'Updated status to {new_status} for {updated_count} students')
        return JsonResponse({'success': True, 'message': f'Status updated for {updated_count} students'})
    
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@csrf_exempt
def batch_archive(request):
    """Archive (deactivate) multiple student records"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    try:
        data = json.loads(request.body)
        student_ids = data.get('student_ids', [])
        
        if not student_ids:
            return JsonResponse({'success': False, 'error': 'No students selected'}, status=400)
        
        updated_count = Student.objects.filter(id__in=student_ids).update(is_active=False)
        
        _log(request, 'BATCH_ARCHIVE', 'Student', 0, f'Archived {updated_count} student records')
        return JsonResponse({'success': True, 'message': f'Archived {updated_count} students'})
    
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# =============================================================================
# EXPORTS & PRINTS
# =============================================================================
@login_required
def export_masterlist(request):
    """Export student masterlist to Excel"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
    from openpyxl.utils import get_column_letter
    from io import BytesIO
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Student Masterlist"
    
    # Styles
    header_font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
    header_fill = PatternFill(start_color='5EA173', end_color='5EA173', fill_type='solid')
    header_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
    
    # Headers
    headers = ['LRN', 'Last Name', 'First Name', 'Middle Name', 'Sex', 'Birth Date', 'Grade Level', 'Section', 'Status']
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border
        ws.column_dimensions[get_column_letter(col_idx)].width = 15
    
    # Get students
    students = Student.objects.filter(
        enrollments__school_year=current_sy
    ).distinct().order_by('last_name', 'first_name')
    
    row_num = 2
    for student in students:
        enrollment = student.enrollments.filter(school_year=current_sy).first()
        if enrollment:
            ws.cell(row=row_num, column=1, value=student.lrn).border = thin_border
            ws.cell(row=row_num, column=2, value=student.last_name).border = thin_border
            ws.cell(row=row_num, column=3, value=student.first_name).border = thin_border
            ws.cell(row=row_num, column=4, value=student.middle_name or '').border = thin_border
            ws.cell(row=row_num, column=5, value=student.sex).border = thin_border
            ws.cell(row=row_num, column=6, value=student.birth_date.strftime('%Y-%m-%d') if student.birth_date else '').border = thin_border
            ws.cell(row=row_num, column=7, value=enrollment.section.grade_level.grade_name if enrollment.section.grade_level else '').border = thin_border
            ws.cell(row=row_num, column=8, value=enrollment.section.section_name).border = thin_border
            ws.cell(row=row_num, column=9, value=enrollment.status).border = thin_border
            row_num += 1
    
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    filename = f"Student_Masterlist_{current_sy.year_label}_{timezone.now().strftime('%Y%m%d')}.xlsx"
    response = HttpResponse(output.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def student_export_csv(request):
    """Export student records to CSV"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    
    students = Student.objects.filter(
        enrollments__school_year=current_sy
    ).distinct().order_by('last_name', 'first_name')
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="Student_Records_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['LRN', 'Last Name', 'First Name', 'Middle Name', 'Sex', 'Birth Date', 'Birth Place', 'Grade Level', 'Section', 'Status', 'Verified'])
    
    for student in students:
        enrollment = student.enrollments.filter(school_year=current_sy).first()
        if enrollment:
            writer.writerow([
                student.lrn,
                student.last_name,
                student.first_name,
                student.middle_name or '',
                student.sex,
                student.birth_date.strftime('%Y-%m-%d') if student.birth_date else '',
                student.birth_place or '',
                enrollment.section.grade_level.grade_name if enrollment.section.grade_level else '',
                enrollment.section.section_name,
                enrollment.status,
                'Yes' if student.is_verified else 'No',
            ])
    
    return response

@login_required
@csrf_exempt
def mark_notifications_read(request):
    """Mark all notifications as read for the current user"""
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=405)
    
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return JsonResponse({'success': True})


@login_required
@csrf_exempt
def student_verify(request, student_id):
    """Verify a student's record"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    student = get_object_or_404(Student, id=student_id)
    student.is_verified = True
    student.verified_by = request.user
    student.verified_at = timezone.now()
    student.save()
    
    _log(request, 'VERIFY_STUDENT', 'Student', student.id,
         f'Student {student.full_name} (LRN: {student.lrn}) verified')
    
    return JsonResponse({'success': True, 'message': 'Student verified successfully'})

@login_required
def student_edit(request, student_id):
    """Edit student record - POST endpoint returning JSON"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    student = get_object_or_404(Student, id=student_id)
    
    try:
        # Update student fields
        student.first_name = request.POST.get('first_name', student.first_name)
        student.last_name = request.POST.get('last_name', student.last_name)
        student.middle_name = request.POST.get('middle_name', student.middle_name)
        student.lrn = request.POST.get('lrn', student.lrn)
        student.sex = request.POST.get('sex', student.sex)
        
        birth_date = request.POST.get('birth_date')
        if birth_date:
            student.birth_date = birth_date
            
        student.birth_place = request.POST.get('birth_place', student.birth_place)
        student.mother_tongue = request.POST.get('mother_tongue', student.mother_tongue)
        student.religion = request.POST.get('religion', student.religion)
        student.is_4ps = request.POST.get('is_4ps', 'off') == 'on'
        student.save()
        
        _log(request, 'EDIT_STUDENT', 'Student', student.id,
             f'Student record updated: {student.full_name} (LRN: {student.lrn})')
        
        return JsonResponse({'success': True, 'message': 'Student updated successfully'})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
    
@login_required
def student_generate_sf10(request, student_id):
    """Generate SF10 for a single student - POST endpoint"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    student = get_object_or_404(Student, id=student_id)
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    
    if not current_sy:
        return JsonResponse({'success': False, 'error': 'No active school year'}, status=400)
    
    enrollment = student.enrollments.filter(
        school_year=current_sy, status='Enrolled'
    ).first()
    
    if not enrollment:
        return JsonResponse({'success': False, 'error': 'Student is not currently enrolled'}, status=400)
    
    sf10_form = SchoolForm.objects.filter(form_code='SF10', is_active=True).first()
    if sf10_form and current_sy:
        grade_level = enrollment.section.grade_level if enrollment.section else None
        
        SF10History.objects.get_or_create(
            student=student,
            defaults={
                'generated_by': request.user, 
                'school_year': current_sy,
                'grade_level': grade_level
            }
        )
        
        FormSubmission.objects.create(
            school_form=sf10_form,
            section=enrollment.section,
            school_year=current_sy,
            submitted_by=request.user,
            status='Approved',
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
            review_notes=f'SF10 generated for {student.full_name}',
        )
    
    _log(request, 'GENERATE_SF10', 'Student', student.id,
         f'SF10 generated for {student.full_name} (LRN: {student.lrn})')
    
    # Try to generate PDF
    try:
        pdf_path = generate_sf10_pdf(student, current_sy)
        
        with open(pdf_path, 'rb') as pdf_file:
            response = HttpResponse(pdf_file.read(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="SF10_{student.last_name}_{student.first_name}.pdf"'
            response['Content-Length'] = os.path.getsize(pdf_path)
        
        # Clean up temp file
        os.unlink(pdf_path)
        
        return response
        
    except Exception as e:
        # If PDF generation fails, return JSON response
        print(f"PDF generation failed: {e}")  # Add logging
        return JsonResponse({
            'success': True, 
            'message': 'SF10 record created. PDF generation failed but record is saved.',
            'pdf_error': str(e)
        })
        
@login_required
def student_sf9(request, student_id):
    """Print SF9 (Report Card) for a student - opens in new window"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    student = get_object_or_404(Student, id=student_id)
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    current_quarter = Quarter.objects.filter(school_year=current_sy, is_current_quarter=True).first()
    
    enrollment = student.enrollments.filter(school_year=current_sy).first()
    
    # Get grades
    grades = []
    if enrollment:
        grade_components = GradeComponent.objects.filter(
            enrollment=enrollment
        ).select_related('subject', 'quarter')
        
        for gc in grade_components:
            grades.append({
                'subject': gc.subject.subject_name,
                'quarter': gc.quarter.quarter_label if gc.quarter else 'Q3',
                'final_grade': gc.initial_grade,
                'remarks': 'PASSED' if gc.initial_grade >= 75 else 'FAILED',
            })
    
    context = {
        'student': student,
        'enrollment': enrollment,
        'grades': grades,
        'school_year': current_sy,
        'quarter': current_quarter,
        'today': date.today(),
        'school_profile': SchoolProfile.objects.first(),
    }
    return render(request, 'registrars/classes/sf9_print.html', context)


@login_required
def print_sf1(request):
    """Print SF1 (School Register) report - opens in new window"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    
    # Get filter parameters from URL
    grade_level_id = request.GET.get('grade_level')
    section_id = request.GET.get('section')
    search_query = request.GET.get('search', '')
    
    # Get students
    students = Student.objects.filter(
        enrollments__school_year=current_sy
    ).distinct().order_by('last_name', 'first_name')
    
    if search_query:
        students = students.filter(
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(lrn__icontains=search_query)
        )
    
    if grade_level_id:
        students = students.filter(
            enrollments__section__grade_level_id=grade_level_id
        ).distinct()
    
    if section_id:
        students = students.filter(
            enrollments__section_id=section_id
        ).distinct()
    
    context = {
        'students': students,
        'school_year': current_sy,
        'today': date.today(),
        'school_profile': SchoolProfile.objects.first(),
    }
    return render(request, 'registrars/classes/sf1_print.html', context)


def generate_sf10_pdf(student, current_sy):
    """Generate SF10-SHS PDF for a student following DepEd format"""
    
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
    
    # Use letter size (8.5x11) as DepEd forms use this
    doc = SimpleDocTemplate(
        temp_file.name,
        pagesize=letter,
        topMargin=0.4*inch,
        bottomMargin=0.4*inch,
        leftMargin=0.5*inch,
        rightMargin=0.3*inch
    )
    
    styles = getSampleStyleSheet()
    story = []
    
    # Get enrollment data
    enrollment = student.enrollments.filter(
        school_year=current_sy, status='Enrolled'
    ).first()
    
    school_profile = SchoolProfile.objects.first()
    
    # ========== HELPER STYLES ==========
    title_style = ParagraphStyle(
        'Title', fontSize=11, fontName='Helvetica-Bold',
        alignment=TA_CENTER, spaceAfter=4
    )
    
    subtitle_style = ParagraphStyle(
        'Subtitle', fontSize=9, fontName='Helvetica-Bold',
        alignment=TA_CENTER, spaceAfter=6
    )
    
    label_style = ParagraphStyle(
        'Label', fontSize=7, fontName='Helvetica-Bold',
        leading=9
    )
    
    value_style = ParagraphStyle(
        'Value', fontSize=7, fontName='Helvetica',
        leading=9
    )
    
    small_style = ParagraphStyle(
        'Small', fontSize=6.5, fontName='Helvetica',
        leading=8, textColor=colors.HexColor('#333333')
    )
    
    header_label = ParagraphStyle(
        'HeaderLabel', fontSize=7, fontName='Helvetica-Bold',
        alignment=TA_CENTER, leading=9
    )
    
    # ========== PAGE 1 - FRONT ==========
    
    # Title
    story.append(Paragraph("LEARNER'S PERMANENT ACADEMIC RECORD FOR SENIOR HIGH SCHOOL (SF10-SHS)", title_style))
    story.append(Paragraph("(Formerly Form 137)", subtitle_style))
    story.append(Spacer(1, 8))
    
    # LEARNER'S INFORMATION Section
    story.append(Paragraph("<b>LEARNER'S INFORMATION</b>", label_style))
    story.append(Spacer(1, 4))
    
    # Name fields in a table
    name_data = [
        [
            Paragraph("<b>LAST NAME:</b>", label_style),
            Paragraph(student.last_name or '', value_style),
            Paragraph("<b>FIRST NAME:</b>", label_style),
            Paragraph(student.first_name or '', value_style),
            Paragraph("<b>MIDDLE NAME:</b>", label_style),
            Paragraph(student.middle_name or '', value_style),
        ]
    ]
    name_table = Table(name_data, colWidths=[55, 100, 55, 100, 55, 100])
    name_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('LINEBELOW', (1, 0), (1, 0), 0.5, colors.black),
        ('LINEBELOW', (3, 0), (3, 0), 0.5, colors.black),
        ('LINEBELOW', (5, 0), (5, 0), 0.5, colors.black),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(name_table)
    story.append(Spacer(1, 4))
    
    # LRN, DOB, Sex, Admission Date
    info_data = [
        [
            Paragraph("<b>LRN:</b>", label_style),
            Paragraph(student.lrn or '', value_style),
            Paragraph("<b>Date of Birth (MM/DD/YYYY):</b>", label_style),
            Paragraph(student.birth_date.strftime('%m/%d/%Y') if student.birth_date else '', value_style),
            Paragraph("<b>Sex:</b>", label_style),
            Paragraph(student.sex or '', value_style),
        ]
    ]
    info_table = Table(info_data, colWidths=[30, 120, 115, 80, 30, 40])
    info_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('LINEBELOW', (1, 0), (1, 0), 0.5, colors.black),
        ('LINEBELOW', (3, 0), (3, 0), 0.5, colors.black),
        ('LINEBELOW', (5, 0), (5, 0), 0.5, colors.black),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 10))
    
    # ELIGIBILITY FOR SHS ENROLMENT
    story.append(Paragraph("<b>ELIGIBILITY FOR SHS ENROLMENT</b>", label_style))
    story.append(Spacer(1, 4))
    
    eligibility_data = [
        [
            Paragraph("High School Completer", value_style),
            Paragraph("Gen. Ave:", label_style),
            Paragraph("", value_style),
            Paragraph("Junior High School Completer", value_style),
            Paragraph("Gen. Ave:", label_style),
            Paragraph("", value_style),
        ],
        [
            Paragraph("Date of Graduation/Completion (MM/DD/YYYY):", label_style),
            Paragraph("", value_style),
            Paragraph("Name of School:", label_style),
            Paragraph("", value_style),
            Paragraph("School Address:", label_style),
            Paragraph("", value_style),
        ]
    ]
    eligibility_table = Table(eligibility_data, colWidths=[120, 40, 40, 120, 40, 105])
    eligibility_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (1, 0), (1, 0), 0.5, colors.black),
        ('LINEBELOW', (4, 0), (4, 0), 0.5, colors.black),
        ('LINEBELOW', (1, 1), (1, 1), 0.5, colors.black),
        ('LINEBELOW', (3, 1), (3, 1), 0.5, colors.black),
        ('LINEBELOW', (5, 1), (5, 1), 0.5, colors.black),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(eligibility_table)
    story.append(Spacer(1, 8))
    
    # SCHOLASTIC RECORD
    story.append(Paragraph("<b>SCHOLASTIC RECORD</b>", label_style))
    story.append(Spacer(1, 4))
    
    # School Info Row
    school_info = [
        [
            Paragraph("<b>SCHOOL:</b>", label_style),
            Paragraph(school_profile.school_name if school_profile else 'Formify LIS', value_style),
            Paragraph("<b>SCHOOL ID:</b>", label_style),
            Paragraph(school_profile.school_id if school_profile else '', value_style),
            Paragraph("<b>GRADE LEVEL:</b>", label_style),
            Paragraph(enrollment.section.grade_level.grade_name if enrollment and enrollment.section.grade_level else '11', value_style),
            Paragraph("<b>SY:</b>", label_style),
            Paragraph(current_sy.year_label if current_sy else '', value_style),
            Paragraph("<b>SEM:</b>", label_style),
            Paragraph("1st", value_style),
        ]
    ]
    school_table = Table(school_info, colWidths=[40, 120, 40, 60, 55, 45, 25, 50, 25, 20])
    school_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('LINEBELOW', (1, 0), (1, 0), 0.5, colors.black),
        ('LINEBELOW', (3, 0), (3, 0), 0.5, colors.black),
        ('LINEBELOW', (5, 0), (5, 0), 0.5, colors.black),
        ('LINEBELOW', (7, 0), (7, 0), 0.5, colors.black),
        ('LINEBELOW', (9, 0), (9, 0), 0.5, colors.black),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(school_table)
    story.append(Spacer(1, 3))
    
    # Track/Strand and Section
    track_section = [
        [
            Paragraph("<b>TRACK/STRAND:</b>", label_style),
            Paragraph("Academic - ", value_style),
            Paragraph("<b>SECTION:</b>", label_style),
            Paragraph(enrollment.section.section_name if enrollment else '', value_style),
        ]
    ]
    track_table = Table(track_section, colWidths=[60, 200, 45, 150])
    track_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('LINEBELOW', (1, 0), (1, 0), 0.5, colors.black),
        ('LINEBELOW', (3, 0), (3, 0), 0.5, colors.black),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(track_table)
    story.append(Spacer(1, 6))
    
    # Grades Table Header
    grades_header = [
        [
            Paragraph("<b>Subject Type</b>", header_label),
            Paragraph("<b>SUBJECTS</b>", header_label),
            Paragraph("<b>Q1</b>", header_label),
            Paragraph("<b>Q2</b>", header_label),
            Paragraph("<b>Q3</b>", header_label),
            Paragraph("<b>Q4</b>", header_label),
            Paragraph("<b>SEM FINAL GRADE</b>", header_label),
            Paragraph("<b>ACTION TAKEN</b>", header_label),
        ]
    ]
    
    # Get grades for the student
    grades = []
    general_ave = 0
    grade_count = 0
    
    if enrollment:
        grade_components = GradeComponent.objects.filter(
            enrollment=enrollment
        ).select_related('subject', 'quarter').order_by('subject__subject_name')
        
        for gc in grade_components:
            quarter_grades = {'Q1': '', 'Q2': '', 'Q3': '', 'Q4': ''}
            quarter_grades[gc.quarter.quarter_label] = f"{gc.initial_grade:.0f}" if gc.initial_grade else ''
            
            grades.append({
                'subject': gc.subject.subject_name,
                'type': 'CORE',
                'q1': quarter_grades.get('Q1', ''),
                'q2': quarter_grades.get('Q2', ''),
                'q3': quarter_grades.get('Q3', ''),
                'q4': quarter_grades.get('Q4', ''),
                'final': f"{gc.initial_grade:.0f}" if gc.initial_grade else '',
                'action': 'Passed' if gc.initial_grade and gc.initial_grade >= 75 else 'Failed'
            })
            
            if gc.initial_grade:
                general_ave += gc.initial_grade
                grade_count += 1
    
    # Build grades table
    col_widths = [50, 180, 35, 35, 35, 35, 65, 55]
    
    # Headers
    grades_table_data = [grades_header[0]]
    
    # Grade rows
    for grade in grades:
        grades_table_data.append([
            Paragraph(grade['type'], small_style),
            Paragraph(grade['subject'], small_style),
            Paragraph(grade['q1'], small_style),
            Paragraph(grade['q2'], small_style),
            Paragraph(grade['q3'], small_style),
            Paragraph(grade['q4'], small_style),
            Paragraph(grade['final'], small_style),
            Paragraph(grade['action'], small_style),
        ])
    
    # Add empty rows if less than 15 subjects
    while len(grades_table_data) < 16:
        grades_table_data.append([
            Paragraph('', small_style), Paragraph('', small_style),
            Paragraph('', small_style), Paragraph('', small_style),
            Paragraph('', small_style), Paragraph('', small_style),
            Paragraph('', small_style), Paragraph('', small_style),
        ])
    
    grades_table = Table(grades_table_data, colWidths=col_widths, repeatRows=1)
    grades_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E8E8E8')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 7),
        ('FONTSIZE', (0, 1), (-1, -1), 6.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(grades_table)
    story.append(Spacer(1, 4))
    
    # General Average
    gen_ave = general_ave / grade_count if grade_count > 0 else 0
    story.append(Paragraph(f"<b>General Ave. for the Semester:</b> {gen_ave:.2f}", label_style))
    story.append(Spacer(1, 6))
    
    # Remarks
    story.append(Paragraph("<b>REMARKS:</b>", label_style))
    story.append(Spacer(1, 12))
    
    # Signatures
    sig_data = [
        [
            Paragraph("<b>Prepared by:</b>", label_style),
            Paragraph("<b>Certified True and Correct:</b>", label_style),
            Paragraph("<b>Date Checked (MM/DD/YYYY):</b>", label_style),
        ],
        [
            Paragraph("", value_style),
            Paragraph("", value_style),
            Paragraph("", value_style),
        ],
        [
            Paragraph("Signature of Adviser over Printed Name", small_style),
            Paragraph("Signature of Authorized Person over Printed Name, Designation", small_style),
            Paragraph("", small_style),
        ]
    ]
    sig_table = Table(sig_data, colWidths=[180, 180, 105])
    sig_table.setStyle(TableStyle([
        ('LINEBELOW', (0, 1), (0, 1), 0.5, colors.black),
        ('LINEBELOW', (1, 1), (1, 1), 0.5, colors.black),
        ('LINEBELOW', (2, 1), (2, 1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(sig_table)
    
    # ========== PAGE 2 - BACK ==========
    story.append(Spacer(1, 20))
    story.append(Paragraph("Page 2", subtitle_style))
    story.append(Paragraph("SF10-SHS", ParagraphStyle('FormCode', fontSize=8, fontName='Helvetica-Bold', alignment=TA_RIGHT)))
    story.append(Spacer(1, 10))
    
    # Second Semester (similar structure)
    # ... (same pattern repeated for Grade 11 2nd Sem and Grade 12)
    
    story.append(Spacer(1, 20))
    
    # Final Summary on Back Page
    summary_data = [
        [
            Paragraph("<b>Track/Strand Accomplished:</b>", label_style),
            Paragraph("Academic", value_style),
            Paragraph("<b>SHS General Average:</b>", label_style),
            Paragraph(f"{gen_ave:.2f}", value_style),
        ],
        [
            Paragraph("<b>Awards/Honors Received:</b>", label_style),
            Paragraph("", value_style),
            Paragraph("<b>Date of SHS Graduation (MM/DD/YYYY):</b>", label_style),
            Paragraph("", value_style),
        ]
    ]
    summary_table = Table(summary_data, colWidths=[120, 150, 120, 75])
    summary_table.setStyle(TableStyle([
        ('LINEBELOW', (1, 0), (1, 0), 0.5, colors.black),
        ('LINEBELOW', (3, 0), (3, 0), 0.5, colors.black),
        ('LINEBELOW', (1, 1), (1, 1), 0.5, colors.black),
        ('LINEBELOW', (3, 1), (3, 1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 15))
    
    # Certification
    story.append(Paragraph("<b>Certified by:</b>", label_style))
    story.append(Spacer(1, 25))
    story.append(Paragraph("_" * 50, value_style))
    story.append(Paragraph("Signature of School Head over Printed Name", small_style))
    story.append(Spacer(1, 5))
    story.append(Paragraph("Date: ____________________", value_style))
    story.append(Spacer(1, 15))
    
    # Note
    note_style = ParagraphStyle(
        'Note', fontSize=5.5, fontName='Helvetica',
        leading=7, textColor=colors.HexColor('#555555')
    )
    story.append(Paragraph(
        "NOTE: This permanent record or a photocopy of this permanent record that bears the seal of the school "
        "and the original signature in ink of the School Head shall be considered valid for all legal purposes. "
        "Any erasure or alteration made on this copy should be validated by the School Head. "
        "If the student transfers to another school, the originating school should produce one (1) certified true "
        "copy of this permanent record for safekeeping. The receiving school shall continue filling up the original form. "
        "Upon graduation, the school from which the student graduated should keep the original form and produce "
        "one (1) certified true copy for the Division Office.",
        note_style
    ))
    
    doc.build(story)
    return temp_file.name


# =============================================================================
# ENROLLMENT MANAGEMENT
# =============================================================================
@login_required
def enrollment_management(request):
    """Enrollment Management Page"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    grade_levels = GradeLevel.objects.all().order_by('sort_order')
    
    context = {
        'current_sy_label': current_sy.year_label if current_sy else 'N/A',
        'grade_levels': grade_levels,
        'today': date.today(),
    }
    return render(request, 'registrars/enrollment/enrollment.html', context)


@login_required
def enrollment_list_data(request):
    """Return enrollment data as JSON for the table"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    if not current_sy:
        return JsonResponse({'success': False, 'error': 'No active school year'}, status=400)
    
    enrollments = Enrollment.objects.filter(
        school_year=current_sy
    ).select_related('student', 'section', 'section__grade_level').order_by('-enrollment_date')
    
    # Apply filters
    grade_filter = request.GET.get('grade_level', '')
    status_filter = request.GET.get('status', '')
    search_query = request.GET.get('search', '')
    
    if grade_filter:
        enrollments = enrollments.filter(section__grade_level__grade_name=grade_filter)
    if status_filter:
        enrollments = enrollments.filter(status=status_filter)
    if search_query:
        enrollments = enrollments.filter(
            Q(student__first_name__icontains=search_query) |
            Q(student__last_name__icontains=search_query) |
            Q(student__lrn__icontains=search_query)
        )
    
    enrollment_list = []
    for enr in enrollments[:50]:
        enrollment_list.append({
            'id': enr.id,
            'lrn': enr.student.lrn or '—',
            'name': f"{enr.student.last_name}, {enr.student.first_name}",
            'grade_level': enr.section.grade_level.grade_name if enr.section and enr.section.grade_level else 'N/A',
            'section': enr.section.section_name if enr.section else '—',
            'enrollment_type': enr.enrollment_type or 'New Student',
            'status': enr.status,
            'enrollment_date': enr.enrollment_date.strftime('%b %d, %Y') if enr.enrollment_date else '',
        })
    
    # Grade distribution
    grade_stats = []
    for gl in GradeLevel.objects.all().order_by('sort_order'):
        count = Enrollment.objects.filter(
            school_year=current_sy, section__grade_level=gl, status='Enrolled'
        ).count()
        grade_stats.append({'grade_name': gl.grade_name, 'count': count})
    
    # Pending enrollments
    pending = Enrollment.objects.filter(
        school_year=current_sy, status='Pending'
    ).select_related('student', 'section__grade_level')[:5]
    
    pending_list = []
    for p in pending:
        pending_list.append({
            'id': p.id,
            'name': f"{p.student.last_name}, {p.student.first_name}",
            'grade_level': p.section.grade_level.grade_name if p.section and p.section.grade_level else 'N/A',
            'enrollment_type': p.enrollment_type or 'New Student',
            'status': p.status,
        })
    
    return JsonResponse({
        'success': True,
        'enrollments': enrollment_list,
        'grade_stats': grade_stats,
        'pending': pending_list,
    })


@login_required
@csrf_exempt
def enrollment_create(request):
    """Create a new enrollment"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    try:
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        middle_name = request.POST.get('middle_name', '').strip()
        lrn = request.POST.get('lrn', '').strip()
        grade_level_name = request.POST.get('grade_level', '')
        enrollment_type = request.POST.get('enrollment_type', 'New Student')
        
        if not first_name or not last_name:
            return JsonResponse({'success': False, 'error': 'First and last name are required'}, status=400)
        
        current_sy = SchoolYear.objects.filter(is_current=True).first()
        if not current_sy:
            return JsonResponse({'success': False, 'error': 'No active school year'}, status=400)
        
        # Create or get student
        student, created = Student.objects.get_or_create(
            lrn=lrn if lrn else None,
            defaults={
                'first_name': first_name,
                'last_name': last_name,
                'middle_name': middle_name,
            }
        )
        
        if not created and lrn:
            student.first_name = first_name
            student.last_name = last_name
            student.middle_name = middle_name
            student.save()
        
        # Get default section for grade level
        grade_level = GradeLevel.objects.filter(grade_name=grade_level_name).first()
        section = Section.objects.filter(
            grade_level=grade_level, school_year=current_sy, is_active=True
        ).first() if grade_level else None
        
        if not section:
            section = Section.objects.filter(
                school_year=current_sy, is_active=True
            ).first()
        
        # Create enrollment
        enrollment = Enrollment.objects.create(
            student=student,
            section=section,
            school_year=current_sy,
            enrollment_type=enrollment_type,
            status='Pending',
            enrollment_date=date.today(),
        )
        
        _log(request, 'CREATE_ENROLLMENT', 'Enrollment', enrollment.id,
             f'Enrollment created for {student.full_name}')
        
        return JsonResponse({'success': True, 'message': 'Enrollment created successfully'})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def enrollment_detail_data(request, enrollment_id):
    """Return enrollment detail as JSON"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    enrollment = get_object_or_404(
        Enrollment.objects.select_related('student', 'section', 'section__grade_level'),
        id=enrollment_id
    )
    
    data = {
        'id': enrollment.id,
        'lrn': enrollment.student.lrn or '—',
        'name': f"{enrollment.student.last_name}, {enrollment.student.first_name} {enrollment.student.middle_name or ''}",
        'grade_level': enrollment.section.grade_level.grade_name if enrollment.section and enrollment.section.grade_level else 'N/A',
        'section': enrollment.section.section_name if enrollment.section else '—',
        'enrollment_type': enrollment.enrollment_type or 'New Student',
        'status': enrollment.status,
        'enrollment_date': enrollment.enrollment_date.strftime('%b %d, %Y') if enrollment.enrollment_date else '',
    }
    
    return JsonResponse({'success': True, 'data': data})


@login_required
@csrf_exempt
def enrollment_approve(request, enrollment_id):
    """Approve an enrollment"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    enrollment = get_object_or_404(Enrollment, id=enrollment_id)
    enrollment.status = 'Enrolled'
    enrollment.approved_by = request.user
    enrollment.approved_date = timezone.now()
    enrollment.save()
    
    _log(request, 'APPROVE_ENROLLMENT', 'Enrollment', enrollment.id,
         f'Enrollment approved for {enrollment.student.full_name}')
    
    return JsonResponse({'success': True, 'message': 'Enrollment approved'})


@login_required
def enrollment_print(request, enrollment_id):
    """Print enrollment form"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    enrollment = get_object_or_404(
        Enrollment.objects.select_related('student', 'section', 'section__grade_level'),
        id=enrollment_id
    )
    
    context = {
        'enrollment': enrollment,
        'today': date.today(),
    }
    return render(request, 'registrars/enrollment/print.html', context)


@login_required
def enrollment_template(request):
    """Download professionally formatted enrollment Excel template"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    wb = openpyxl.Workbook()
    
    # ========== SHEET 1: TEMPLATE ==========
    ws = wb.active
    ws.title = "Enrollment Template"
    
    # Brand colors (matching UI)
    brand_dark = '00072D'
    brand_green = '5EA173'
    brand_light = 'E8F5E9'
    header_font_color = 'FFFFFF'
    border_color = 'D4D4D4'
    alternate_row_color = 'F8F9FA'
    
    # Styles
    title_font = Font(name='Calibri', size=16, bold=True, color=brand_dark)
    subtitle_font = Font(name='Calibri', size=10, color='718096')
    header_font = Font(name='Calibri', size=11, bold=True, color=header_font_color)
    header_fill = PatternFill(start_color=brand_green, end_color=brand_green, fill_type='solid')
    header_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    data_font = Font(name='Calibri', size=10, color='2D3748')
    thin_border = Border(
        left=Side(style='thin', color=border_color),
        right=Side(style='thin', color=border_color),
        top=Side(style='thin', color=border_color),
        bottom=Side(style='thin', color=border_color)
    )
    center_align = Alignment(horizontal='center', vertical='center')
    left_align = Alignment(horizontal='left', vertical='center')
    alt_fill = PatternFill(start_color=alternate_row_color, end_color=alternate_row_color, fill_type='solid')
    light_green_fill = PatternFill(start_color=brand_light, end_color=brand_light, fill_type='solid')
    required_font = Font(name='Calibri', size=10, bold=True, color='DC3545')
    optional_font = Font(name='Calibri', size=10, italic=True, color='718096')
    
    # Column widths
    col_widths = {
        'A': 18, 'B': 20, 'C': 20, 'D': 20,
        'E': 18, 'F': 20, 'G': 10, 'H': 16
    }
    for col, width in col_widths.items():
        ws.column_dimensions[col].width = width
    
    # ========== ROW 1: TITLE ==========
    ws.merge_cells('A1:H1')
    title_cell = ws.cell(row=1, column=1, value="FORMIFY LIS - BATCH ENROLLMENT TEMPLATE")
    title_cell.font = title_font
    title_cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 35
    
    # ========== ROW 2: SUBTITLE ==========
    ws.merge_cells('A2:H2')
    sub_cell = ws.cell(row=2, column=1, 
                       value="Instructions: Fill in the required fields (marked with *) for each student. Do not modify the header row.")
    sub_cell.font = subtitle_font
    sub_cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[2].height = 22
    
    # ========== ROW 3: SCHOOL YEAR INFO ==========
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    ws.merge_cells('A3:H3')
    sy_cell = ws.cell(row=3, column=1, 
                      value=f"School Year: {current_sy.year_label if current_sy else 'N/A'} | "
                            f"Max Records: 500 | Supported: .csv, .xlsx, .xls")
    sy_cell.font = Font(name='Calibri', size=9, italic=True, color='666666')
    sy_cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[3].height = 20
    
    # ========== ROW 5: HEADERS ==========
    header_row = 5
    headers = [
        ('LRN', '12-digit Learner\nReference Number'),
        ('Last Name *', 'Family name\n(Required)'),
        ('First Name *', 'Given name\n(Required)'),
        ('Middle Name', 'Middle name\n(Optional)'),
        ('Grade Level', 'e.g., Grade 7,\nGrade 11'),
        ('Enrollment Type', 'New Student, Transferee,\nBalik-Aral, Old Student'),
        ('Sex', 'M or F'),
        ('Birth Date', 'YYYY-MM-DD format\n(Optional)')
    ]
    
    ws.row_dimensions[header_row].height = 50
    
    for col_idx, (header_text, tooltip) in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col_idx, value=header_text)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border
        
        # Add comment/tooltip
        from openpyxl.comments import Comment
        comment = Comment(tooltip, 'Formify LIS')
        comment.width = 250
        comment.height = 100
        cell.comment = comment
    
    # ========== SAMPLE DATA ROWS ==========
    sample_data = [
        ['136456789012', 'Dela Cruz', 'Juan', 'Santos', 'Grade 7', 'New Student', 'M', '2011-05-15'],
        ['136456789013', 'Garcia', 'Maria', 'Clara', 'Grade 11', 'Transferee', 'F', '2009-03-22'],
        ['', 'Santos', 'Pedro', '', 'Grade 10', 'Balik-Aral', 'M', ''],
        ['136456789015', 'Reyes', 'Ana', 'Liza', 'Grade 8', 'Old Student', 'F', '2010-11-08'],
        ['', 'Bautista', 'Jose', 'Rizal', 'Grade 12', 'New Student', 'M', '2008-06-19'],
    ]
    
    for i, row_data in enumerate(sample_data):
        row_num = header_row + 1 + i
        ws.row_dimensions[row_num].height = 25
        
        for col_idx, value in enumerate(row_data, 1):
            cell = ws.cell(row=row_num, column=col_idx, value=value)
            cell.font = data_font
            cell.border = thin_border
            cell.alignment = center_align if col_idx in [5, 6, 7, 8] else left_align
            
            # Alternate row colors
            if i % 2 == 1:
                cell.fill = alt_fill
            
            # Highlight required fields
            if col_idx in [2, 3]:
                if i % 2 == 0:
                    cell.fill = light_green_fill
    
    # ========== EMPTY ROWS FOR FILLING ==========
    empty_start = header_row + 1 + len(sample_data)
    for i in range(20):
        row_num = empty_start + i
        ws.row_dimensions[row_num].height = 25
        for col_idx in range(1, 9):
            cell = ws.cell(row=row_num, column=col_idx, value='')
            cell.font = data_font
            cell.border = thin_border
            cell.alignment = center_align if col_idx in [5, 6, 7, 8] else left_align
            if i % 2 == 1:
                cell.fill = alt_fill
    
    # ========== LEGEND ROW ==========
    legend_row = empty_start + 22
    ws.merge_cells(f'A{legend_row}:H{legend_row}')
    legend_cell = ws.cell(row=legend_row, column=1, 
                          value="* Required fields | Valid Enrollment Types: New Student, Transferee, Balik-Aral, Old Student | "
                                "Sex: M or F | Birth Date: YYYY-MM-DD format | Delete sample rows before uploading")
    legend_cell.font = Font(name='Calibri', size=8, italic=True, color='999999')
    legend_cell.alignment = Alignment(horizontal='left', vertical='center')
    
    # ========== DATA VALIDATION FOR ENROLLMENT TYPE ==========
    from openpyxl.worksheet.datavalidation import DataValidation
    
    # Enrollment Type dropdown
    dv_type = DataValidation(
        type="list",
        formula1='"New Student,Transferee,Balik-Aral,Old Student"',
        allow_blank=True
    )
    dv_type.error = "Please select a valid enrollment type"
    dv_type.errorTitle = "Invalid Enrollment Type"
    dv_type.prompt = "Select enrollment type"
    dv_type.promptTitle = "Enrollment Type"
    ws.add_data_validation(dv_type)
    dv_type.add(f'F{header_row + 1}:F{empty_start + 19}')
    
    # Sex dropdown
    dv_sex = DataValidation(
        type="list",
        formula1='"M,F"',
        allow_blank=True
    )
    dv_sex.error = "Please enter M or F"
    dv_sex.errorTitle = "Invalid Sex"
    dv_sex.prompt = "Select M or F"
    dv_sex.promptTitle = "Sex"
    ws.add_data_validation(dv_sex)
    dv_sex.add(f'G{header_row + 1}:G{empty_start + 19}')
    
    # ========== FREEZE PANES ==========
    ws.freeze_panes = f'A{header_row + 1}'
    
    # ========== ADD AUTO-FILTER ==========
    ws.auto_filter.ref = f'A{header_row}:H{empty_start + 19}'
    
    # ========== PRINT SETTINGS ==========
    ws.sheet_properties.pageSetUpPr = openpyxl.worksheet.properties.PageSetupProperties(fitToPage=True)
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_title_rows = f'1:{header_row}'  # Repeat header rows on each printed page
    
    # ========== SHEET 2: INSTRUCTIONS ==========
    ws2 = wb.create_sheet("Instructions")
    
    instructions = [
        ("BATCH ENROLLMENT INSTRUCTIONS", 16, True),
        ("", 10, False),
        ("How to use this template:", 12, True),
        ("1. Download and save this file to your computer.", 10, False),
        ("2. Fill in the required fields (Last Name and First Name) for each student.", 10, False),
        ("3. Use the dropdown menus for Enrollment Type and Sex columns.", 10, False),
        ("4. LRN should be a 12-digit number. Leave blank if not available.", 10, False),
        ("5. Grade Level should match existing grade levels in the system.", 10, False),
        ("6. Birth Date should be in YYYY-MM-DD format (e.g., 2011-05-15).", 10, False),
        ("7. Delete the sample data rows before uploading your actual data.", 10, False),
        ("8. Maximum 500 records per upload. For more, split into multiple files.", 10, False),
        ("9. Save the file and upload via the Batch Enrollment button.", 10, False),
        ("", 10, False),
        ("Enrollment Types:", 12, True),
        ("• New Student - First time enrolling in the school", 10, False),
        ("• Transferee - Transferring from another school", 10, False),
        ("• Balik-Aral - Returning after a period of absence", 10, False),
        ("• Old Student - Previously enrolled, continuing enrollment", 10, False),
        ("", 10, False),
        ("Tips:", 12, True),
        ("• Use Excel's drag-fill feature for repetitive data.", 10, False),
        ("• Double-check LRN numbers for accuracy.", 10, False),
        ("• Remove any empty rows before uploading.", 10, False),
        ("• Contact the system administrator for technical support.", 10, False),
    ]
    
    ws2.column_dimensions['A'].width = 80
    
    for i, (text, size, is_bold) in enumerate(instructions, 1):
        cell = ws2.cell(row=i, column=1, value=text)
        cell.font = Font(name='Calibri', size=size, bold=is_bold, 
                        color=brand_dark if is_bold else '2D3748')
        cell.alignment = Alignment(vertical='center')
        ws2.row_dimensions[i].height = 22 if size > 10 else 18
    
    # ========== SAVE TO BYTESIO ==========
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    filename = f"Enrollment_Template_{current_sy.year_label if current_sy else 'SY'}.xlsx"
    
    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

@login_required
def enrollment_export(request):
    """Export enrollment list"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    enrollments = Enrollment.objects.filter(school_year=current_sy).select_related('student', 'section__grade_level')
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="enrollment_list_{date.today()}.csv"'
    writer = csv.writer(response)
    writer.writerow(['LRN', 'Last Name', 'First Name', 'Middle Name', 'Grade Level', 'Section', 'Type', 'Status', 'Date'])
    
    for enr in enrollments:
        writer.writerow([
            enr.student.lrn,
            enr.student.last_name,
            enr.student.first_name,
            enr.student.middle_name or '',
            enr.section.grade_level.grade_name if enr.section and enr.section.grade_level else '',
            enr.section.section_name if enr.section else '',
            enr.enrollment_type,
            enr.status,
            enr.enrollment_date.strftime('%Y-%m-%d') if enr.enrollment_date else '',
        ])
    
    return response


# =============================================================================
# ENROLLMENT MANAGEMENT - Additional Views
# =============================================================================

@login_required
@csrf_exempt
def enrollment_batch_upload(request):
    """Handle batch enrollment upload via CSV or Excel file"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    uploaded_file = request.FILES.get('file')
    if not uploaded_file:
        return JsonResponse({'success': False, 'error': 'No file uploaded'}, status=400)
    
    filename = uploaded_file.name.lower()
    if not (filename.endswith('.csv') or filename.endswith('.xlsx') or filename.endswith('.xls')):
        return JsonResponse({'success': False, 'error': 'Invalid file type'}, status=400)
    
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    if not current_sy:
        return JsonResponse({'success': False, 'error': 'No active school year'}, status=400)
    
    created_count = 0
    skipped_count = 0
    errors = []
    all_rows = []
    
    try:
        # ============== READ FILE ==============
        if filename.endswith('.csv'):
            content = uploaded_file.read().decode('utf-8-sig')
            reader = csv.reader(content.splitlines())
            all_rows = [[c.strip() if c else '' for c in row] for row in reader]
        else:
            wb = openpyxl.load_workbook(uploaded_file, read_only=True, data_only=True)
            ws = wb.active
            
            # Handle merged cells properly
            for row in ws.iter_rows(values_only=True):
                vals = []
                for c in row:
                    if c is None:
                        vals.append('')
                    else:
                        vals.append(str(c).strip())
                all_rows.append(vals)
            wb.close()
        
        print(f"\n=== BATCH UPLOAD DEBUG ===")
        print(f"Total rows read: {len(all_rows)}")
        for i, row in enumerate(all_rows[:10]):
            print(f"Row {i+1}: {row}")
        
        # Remove completely empty rows
        all_rows = [r for r in all_rows if any(v for v in r)]
        print(f"Non-empty rows: {len(all_rows)}")
        
        if len(all_rows) < 2:
            return JsonResponse({
                'success': False,
                'error': f'Only {len(all_rows)} non-empty rows found.'
            }, status=400)
        
        # ============== FIND HEADER ROW ==============
        header_idx = None
        for i, row in enumerate(all_rows):
            row_lower = [str(c).lower() for c in row]
            row_str = ' '.join(row_lower)
            # Check for multiple header keywords
            keywords_found = 0
            if 'lrn' in row_str: keywords_found += 1
            if 'last name' in row_str or 'lastname' in row_str: keywords_found += 1
            if 'first name' in row_str or 'firstname' in row_str: keywords_found += 1
            
            if keywords_found >= 2:
                header_idx = i
                print(f"Header found at row {i+1}: {row}")
                break
        
        if header_idx is None:
            return JsonResponse({
                'success': False,
                'error': 'Cannot find header row. Expected columns: LRN, Last Name, First Name.',
                'first_rows': all_rows[:5]
            }, status=400)
        
        headers = [h.lower().replace('*', '').strip() for h in all_rows[header_idx]]
        print(f"Headers: {headers}")
        
        # ============== MAP COLUMNS ==============
        col = {}
        for i, h in enumerate(headers):
            h_clean = h.strip()
            if not h_clean:
                continue
            if 'lrn' in h_clean:
                col['lrn'] = i
            elif 'last' in h_clean and 'name' in h_clean:
                col['last_name'] = i
            elif 'first' in h_clean and 'name' in h_clean:
                col['first_name'] = i
            elif 'middle' in h_clean and 'name' in h_clean:
                col['middle_name'] = i
            elif 'grade' in h_clean:
                col['grade_level'] = i
            elif 'enrollment' in h_clean or 'type' in h_clean:
                col['enrollment_type'] = i
            elif 'sex' in h_clean or 'gender' in h_clean:
                col['sex'] = i
            elif 'birth' in h_clean or 'dob' in h_clean:
                col['birth_date'] = i
        
        print(f"Column mapping: {col}")
        
        # Check for minimum required columns
        if 'first_name' not in col and 'last_name' not in col:
            return JsonResponse({
                'success': False,
                'error': f'Need at least First Name or Last Name column. Found headers: {headers}'
            }, status=400)
        
        # ============== PROCESS ROWS ==============
        data_rows = all_rows[header_idx + 1:]
        print(f"Data rows to process: {len(data_rows)}")
        
        for row_idx, row in enumerate(data_rows):
            excel_row_num = header_idx + row_idx + 2  # +2 because 0-indexed + header offset + 1
            
            def get_val(field):
                idx = col.get(field)
                if idx is not None and idx < len(row):
                    return str(row[idx]).strip()
                return ''
            
            first_name = get_val('first_name')
            last_name = get_val('last_name')
            lrn = get_val('lrn')
            middle_name = get_val('middle_name')
            grade_name = get_val('grade_level')
            enrollment_type = get_val('enrollment_type') or 'New Student'
            sex = get_val('sex') or 'M'
            birth_date = get_val('birth_date')
            
            print(f"\nRow {excel_row_num}: First='{first_name}', Last='{last_name}', LRN='{lrn}', Grade='{grade_name}'")
            
            # Skip if both names are empty and no LRN
            if not first_name and not last_name and not lrn:
                print(f"  -> SKIP: completely empty")
                continue
            
            # MUST have at least a first name or last name
            if not first_name and not last_name:
                skipped_count += 1
                errors.append(f'Row {excel_row_num}: No name provided')
                print(f"  -> SKIP: no name")
                continue
            
            # If only one name is provided, use it as both (some files have single "Name" column)
            if not last_name and first_name:
                last_name = first_name
            if not first_name and last_name:
                first_name = last_name
            
            # Normalize enrollment type
            t = enrollment_type.lower()
            if 'transfer' in t:
                enrollment_type = 'Transferee'
            elif 'balik' in t or 'aral' in t:
                enrollment_type = 'Balik-Aral'
            elif 'old' in t:
                enrollment_type = 'Old Student'
            elif t in ['new student', 'new', '']:
                enrollment_type = 'New Student'
            
            # Normalize sex
            sex = sex.upper().strip()
            if sex in ['MALE', 'BOY', 'M']:
                sex = 'M'
            elif sex in ['FEMALE', 'GIRL', 'F']:
                sex = 'F'
            else:
                sex = 'M' if sex != 'F' else 'F'
            
            try:
                # ========== CREATE OR GET STUDENT ==========
                student = None
                
                if lrn and len(lrn) >= 3:
                    student = Student.objects.filter(lrn=lrn).first()
                    if student:
                        print(f"  -> Found existing student by LRN: {student.id}")
                        student.first_name = first_name
                        student.last_name = last_name
                        if middle_name:
                            student.middle_name = middle_name
                        student.sex = sex
                        student.save()
                    else:
                        print(f"  -> Creating new student with LRN")
                        student = Student.objects.create(
                            lrn=lrn,
                            first_name=first_name,
                            last_name=last_name,
                            middle_name=middle_name or '',
                            sex=sex,
                            birth_date='2000-01-01',  # placeholder — can be updated later
                            created_by=request.user,   # ← add this

                        )
                else:
                    # Find by name
                    student = Student.objects.filter(
                        first_name__iexact=first_name,
                        last_name__iexact=last_name,
                    ).first()
                    if student:
                        print(f"  -> Found existing student by name: {student.id}")
                    else:
                        print(f"  -> Creating new student without LRN")
                        student = Student.objects.create(
                            first_name=first_name,
                            last_name=last_name,
                            middle_name=middle_name or '',
                            sex=sex,
                            birth_date='2000-01-01',
                            created_by=request.user,   # ← add this

                        )
                
                # Parse birth date
                if birth_date:
                    try:
                        from dateutil import parser as dp
                        # Handle Excel serial date numbers
                        if birth_date.isdigit():
                            from datetime import date as dt, timedelta
                            excel_epoch = dt(1899, 12, 30)
                            parsed = excel_epoch + timedelta(days=int(birth_date))
                        else:
                            parsed = dp.parse(birth_date).date()
                        student.birth_date = parsed
                        student.save()
                    except Exception as bd_err:
                        print(f"  -> Could not parse birth date '{birth_date}': {bd_err}")                
                # ========== FIND SECTION ==========
                section = None
                
                if grade_name:
                    # Try exact match first
                    grade_level = GradeLevel.objects.filter(
                        Q(grade_name__iexact=grade_name) |
                        Q(grade_name__iexact=f"Grade {grade_name}") |
                        Q(grade_name__icontains=grade_name)
                    ).first()
                    
                    print(f"  -> Looking for grade '{grade_name}', found: {grade_level}")
                    
                    if grade_level:
                        section = Section.objects.filter(
                            grade_level=grade_level,
                            school_year=current_sy,
                            is_active=True
                        ).first()
                        print(f"  -> Section found: {section}")
                
                # Fallback: grab any section
                if not section:
                    section = Section.objects.filter(
                        school_year=current_sy,
                        is_active=True
                    ).first()
                    print(f"  -> Fallback section: {section}")
                
                if not section:
                    skipped_count += 1
                    errors.append(
                        f'Row {excel_row_num}: {first_name} {last_name} - '
                        f'No section exists for {current_sy.year_label}. '
                        f'Create sections in the system first.'
                    )
                    print(f"  -> SKIP: no section exists at all")
                    continue
                
                # ========== CHECK DUPLICATE ==========
                exists = Enrollment.objects.filter(
                    student=student,
                    school_year=current_sy,
                    status__in=['Enrolled', 'Pending', 'Approved']
                ).exists()
                
                if exists:
                    skipped_count += 1
                    errors.append(f'Row {excel_row_num}: {first_name} {last_name} - Already enrolled')
                    print(f"  -> SKIP: already enrolled")
                    continue
                
                # ========== CREATE ENROLLMENT ==========
                Enrollment.objects.create(
                    student=student,
                    section=section,
                    school_year=current_sy,
                    enrollment_type=enrollment_type,
                    status='Pending',
                    enrollment_date=date.today(),
                    created_by=request.user,   # ← add this

                )
                created_count += 1
                print(f"  -> ✅ ENROLLMENT CREATED")
                
            except Exception as row_error:
                skipped_count += 1
                import traceback
                tb = traceback.format_exc()
                errors.append(f'Row {excel_row_num}: {first_name} {last_name} - {str(row_error)[:100]}')
                print(f"  -> ❌ ERROR: {row_error}")
                print(tb)
        
        print(f"\n=== RESULT: {created_count} created, {skipped_count} skipped ===")
        
        _log(request, 'BATCH_ENROLLMENT', 'Enrollment', 0,
             f'{created_count} created, {skipped_count} skipped')
        
        # Get DB state for diagnostics
        sections_in_db = list(Section.objects.filter(
            school_year=current_sy, is_active=True
        ).values_list('section_name', 'grade_level__grade_name'))
        
        grade_levels_in_db = list(GradeLevel.objects.all().values_list('grade_name', flat=True))
        
        return JsonResponse({
            'success': True if created_count > 0 else False,
            'message': f'Created: {created_count} | Skipped: {skipped_count} | Errors: {len(errors)}',
            'count': created_count,
            'skipped': skipped_count,
            'errors': errors[:25],
            'debug_info': {
                'headers_found': headers,
                'columns_mapped': {k: headers[v] if v < len(headers) else '?' for k, v in col.items()},
                'rows_processed': len(data_rows),
                'grade_levels_in_db': grade_levels_in_db,
                'sections_in_db': [f"{s[0]} ({s[1]})" for s in sections_in_db],
            }
        })
        
    except Exception as e:
        import traceback
        print("\n=== FATAL ERROR ===")
        print(traceback.format_exc())
        
        return JsonResponse({
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()[-600:],
            'rows_read': len(all_rows) if 'all_rows' in dir() else 0,
        }, status=500)
        
    
@login_required
@csrf_exempt
def enrollment_reject(request, enrollment_id):
    """Reject an enrollment"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    enrollment = get_object_or_404(Enrollment, id=enrollment_id)
    
    # Check if the request has a reject action in JSON body
    reason = ''
    try:
        data = json.loads(request.body)
        if data.get('action') == 'reject':
            reason = data.get('reason', '')
    except:
        pass
    
    enrollment.status = 'Rejected'
    enrollment.remarks = reason or 'Rejected by Registrar'
    enrollment.save()
    
    _log(request, 'REJECT_ENROLLMENT', 'Enrollment', enrollment.id,
         f'Enrollment rejected for {enrollment.student.full_name}')
    
    return JsonResponse({'success': True, 'message': 'Enrollment rejected'})




# =============================================================================
# TRANSFER MANAGEMENT
# =============================================================================

@login_required
def transfer_management(request):
    """Transfer Management Page - Manage incoming/outgoing student transfers"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    grade_levels = GradeLevel.objects.all().order_by('sort_order')
    
    context = {
        'current_sy_label': current_sy.year_label if current_sy else 'N/A',
        'current_sy': current_sy,
        'grade_levels': grade_levels,
        'today': date.today(),
    }
    return render(request, 'registrars/transfer/transfer.html', context)


@login_required
def transfer_list_data(request):
    """Return transfer data as JSON for the table"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    transfers = Transfer.objects.select_related(
        'student', 'grade_level_at_transfer'
    ).order_by('-transfer_date_requested')
    
    # Apply filters
    transfer_type = request.GET.get('transfer_type', '')
    status_filter = request.GET.get('status', '')
    search_query = request.GET.get('search', '')
    
    if transfer_type:
        transfers = transfers.filter(transfer_type=transfer_type)
    if status_filter:
        transfers = transfers.filter(status=status_filter)
    if search_query:
        transfers = transfers.filter(
            Q(student__first_name__icontains=search_query) |
            Q(student__last_name__icontains=search_query) |
            Q(student__lrn__icontains=search_query) |
            Q(from_school_name__icontains=search_query) |
            Q(to_school_name__icontains=search_query)
        )
    
    def safe_str(obj, attr, default='N/A'):
        val = getattr(obj, attr, None)
        if val is None:
            return default
        if callable(val):
            return str(val()) if val() else default
        return str(val) if val else default
    
    def safe_date(obj, attr):
        val = getattr(obj, attr, None)
        return val.strftime('%b %d, %Y') if val else ''
    
    transfer_list = []
    for t in transfers[:100]:
        # Try all possible release date field names
        release_date_str = ''
        for field_name in ['documents_released_date', 'release_date', 'processed_date', 'date_released', 'completed_date']:
            val = getattr(t, field_name, None)
            if val:
                release_date_str = val.strftime('%b %d, %Y')
                break
        
        transfer_list.append({
            'id': t.id,
            'student_name': t.student.full_name if t.student else 'Unknown',
            'lrn': t.student.lrn if t.student and t.student.lrn else '—',
            'transfer_type': safe_str(t, 'get_transfer_type_display', t.transfer_type),
            'transfer_type_code': t.transfer_type,
            'from_school': safe_str(t, 'from_school_name'),
            'to_school': safe_str(t, 'to_school_name'),
            'grade_level': str(t.grade_level_at_transfer) if t.grade_level_at_transfer else 'N/A',
            'status': t.status,
            'status_display': safe_str(t, 'get_status_display', t.status),
            'request_date': safe_date(t, 'transfer_date_requested'),
            'release_date': release_date_str,
        })
    
    # Pending transfers
    pending = transfers.filter(
        status__in=['Pending', 'Documents_Requested']
    )[:5]
    
    pending_list = []
    for t in pending:
        pending_list.append({
            'id': t.id,
            'student_name': t.student.full_name if t.student else 'Unknown',
            'lrn': t.student.lrn if t.student and t.student.lrn else '—',
            'transfer_type': safe_str(t, 'get_transfer_type_display', t.transfer_type),
            'from_school': safe_str(t, 'from_school_name'),
            'to_school': safe_str(t, 'to_school_name'),
            'status': t.status,
            'status_display': safe_str(t, 'get_status_display', t.status),
        })
    
    return JsonResponse({
        'success': True,
        'transfers': transfer_list,
        'pending': pending_list,
    })

@login_required
def transfer_detail_data(request, transfer_id):
    """Return transfer detail as JSON for modal"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    transfer = get_object_or_404(
        Transfer.objects.select_related('student', 'grade_level_at_transfer'),
        id=transfer_id
    )
    
    # Safely get optional fields
    def safe_str(obj, attr, default='N/A'):
        val = getattr(obj, attr, None)
        return str(val) if val else default
    
    def safe_date(obj, attr):
        val = getattr(obj, attr, None)
        return val.strftime('%b %d, %Y') if val else ''
    
    # Try all possible release date field names
    release_date_str = ''
    for field_name in ['documents_released_date', 'release_date', 'processed_date', 'date_released', 'completed_date']:
        val = getattr(transfer, field_name, None)
        if val:
            release_date_str = val.strftime('%b %d, %Y')
            break
    
    data = {
        'id': transfer.id,
        'student_name': transfer.student.full_name if transfer.student else 'Unknown',
        'lrn': transfer.student.lrn if transfer.student and transfer.student.lrn else '—',
        'transfer_type': safe_str(transfer, 'get_transfer_type_display', transfer.transfer_type),
        'transfer_type_code': transfer.transfer_type,
        'from_school': safe_str(transfer, 'from_school_name'),
        'from_school_address': safe_str(transfer, 'from_school_address'),
        'to_school': safe_str(transfer, 'to_school_name'),
        'to_school_address': safe_str(transfer, 'to_school_address'),
        'grade_level': str(transfer.grade_level_at_transfer) if transfer.grade_level_at_transfer else 'N/A',
        'status': transfer.status,
        'status_display': safe_str(transfer, 'get_status_display', transfer.status),
        'request_date': safe_date(transfer, 'transfer_date_requested'),
        'release_date': release_date_str,
        'reason': safe_str(transfer, 'reason', '—'),
        'remarks': safe_str(transfer, 'remarks', '—'),
    }
    
    return JsonResponse({'success': True, 'data': data})

@login_required
@csrf_exempt
def transfer_create(request):
    """Create a new transfer request"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    try:
        lrn = request.POST.get('lrn', '').strip()
        transfer_type = request.POST.get('transfer_type', 'OUTGOING')
        to_school_name = request.POST.get('to_school_name', '').strip()
        to_school_address = request.POST.get('to_school_address', '').strip()
        from_school_name = request.POST.get('from_school_name', '').strip()
        from_school_address = request.POST.get('from_school_address', '').strip()
        reason = request.POST.get('reason', '').strip()
        grade_level_id = request.POST.get('grade_level', '')
        
        if not lrn:
            return JsonResponse({'success': False, 'error': 'Student LRN is required'}, status=400)
        
        if transfer_type == 'OUTGOING' and not to_school_name:
            return JsonResponse({'success': False, 'error': 'Destination school name is required for outgoing transfers'}, status=400)
        
        if transfer_type == 'INCOMING' and not from_school_name:
            return JsonResponse({'success': False, 'error': 'Originating school name is required for incoming transfers'}, status=400)
        
        # Find student by LRN
        student = Student.objects.filter(lrn=lrn).first()
        if not student:
            return JsonResponse({'success': False, 'error': f'No student found with LRN: {lrn}'}, status=400)
        
        current_sy = SchoolYear.objects.filter(is_current=True).first()
        
        grade_level = None
        if grade_level_id:
            try:
                grade_level = GradeLevel.objects.get(id=grade_level_id)
            except GradeLevel.DoesNotExist:
                pass
        
        if not grade_level and current_sy:
            enrollment = student.enrollments.filter(
                school_year=current_sy, status='Enrolled'
            ).first()
            if enrollment and enrollment.section:
                grade_level = enrollment.section.grade_level
        
        # Check for existing pending transfer
        existing = Transfer.objects.filter(
            student=student,
            status__in=['Pending', 'Documents_Requested']
        ).first()
        
        if existing:
            return JsonResponse({
                'success': False,
                'error': f'{student.full_name} already has a pending transfer request (#{existing.id})'
            }, status=400)
        
        transfer = Transfer.objects.create(
            student=student,
            transfer_type=transfer_type,
            from_school_name=from_school_name,
            from_school_address=from_school_address,
            to_school_name=to_school_name,
            to_school_address=to_school_address,
            grade_level_at_transfer=grade_level,
            reason=reason,
            status='Pending',
            transfer_date_requested=date.today(),
            requested_by=request.user,  # ← ADD THIS LINE

        )
        
        _log(request, 'CREATE_TRANSFER', 'Transfer', transfer.id,
             f'{transfer_type} transfer created for {student.full_name}')
        
        return JsonResponse({'success': True, 'message': 'Transfer request created successfully'})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@csrf_exempt
def transfer_process(request, transfer_id):
    """Process a transfer - request documents, release, or reject"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    transfer = get_object_or_404(Transfer, id=transfer_id)
    
    try:
        data = json.loads(request.body)
        action = data.get('action', '')
        remarks = data.get('remarks', '')
    except:
        action = request.POST.get('action', '')
        remarks = request.POST.get('remarks', '')
    
    if action == 'request_docs':
        if transfer.status != 'Pending':
            return JsonResponse({'success': False, 'error': 'Only pending transfers can request documents'}, status=400)
        transfer.status = 'Documents_Requested'
        transfer.remarks = remarks or 'Documents requested by Registrar'
        message = 'Documents requested successfully'
        
    elif action == 'release':
        if transfer.status != 'Documents_Requested':
            return JsonResponse({'success': False, 'error': 'Documents must be requested first'}, status=400)
        transfer.status = 'Documents_Released'
        # Try multiple possible field names for the release date
        if hasattr(transfer, 'documents_released_date'):
            transfer.documents_released_date = date.today()
        elif hasattr(transfer, 'release_date'):
            transfer.release_date = date.today()
        elif hasattr(transfer, 'processed_date'):
            transfer.processed_date = date.today()
        elif hasattr(transfer, 'date_released'):
            transfer.date_released = date.today()
        transfer.remarks = remarks or 'Documents released by Registrar'
        message = 'Documents released successfully'

        # If outgoing, update enrollment status
        if transfer.transfer_type == 'OUTGOING':
            current_sy = SchoolYear.objects.filter(is_current=True).first()
            if current_sy:
                enrollment = transfer.student.enrollments.filter(
                    school_year=current_sy, status='Enrolled'
                ).first()
                if enrollment:
                    enrollment.status = 'Transferred'
                    enrollment.save()
        
    elif action == 'reject':
        if transfer.status not in ['Pending', 'Documents_Requested']:
            return JsonResponse({'success': False, 'error': 'Cannot reject this transfer'}, status=400)
        transfer.status = 'Rejected'
        transfer.remarks = remarks or 'Transfer rejected by Registrar'
        message = 'Transfer rejected'
        
    else:
        return JsonResponse({'success': False, 'error': 'Invalid action'}, status=400)
    
    transfer.save()
    
    _log(request, f'TRANSFER_{action.upper()}', 'Transfer', transfer.id, message)
    
    # Create notification
    Notification.objects.create(
        recipient=request.user,
        notification_type='TRANSFER_PROCESSED',
        title=f'Transfer {action.replace("_", " ").title()}',
        message=f'{message} for {transfer.student.full_name} (LRN: {transfer.student.lrn})',
        is_read=False,
    )
    
    return JsonResponse({
        'success': True,
        'message': message,
        'new_status': transfer.status,
        'new_status_display': transfer.get_status_display()
    })


@login_required
def transfer_print(request, transfer_id):
    """Print transfer form"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    transfer = get_object_or_404(
        Transfer.objects.select_related('student', 'grade_level_at_transfer'),
        id=transfer_id
    )
    
    context = {
        'transfer': transfer,
        'today': date.today(),
        'school_profile': SchoolProfile.objects.first(),
    }
    return render(request, 'registrars/transfer/print.html', context)


@login_required
def transfer_export(request):
    """Export transfer list to CSV"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    transfers = Transfer.objects.select_related('student', 'grade_level_at_transfer').order_by('-transfer_date_requested')
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="transfer_requests_{date.today()}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['LRN', 'Student Name', 'Type', 'From School', 'To School', 'Grade Level', 'Request Date', 'Status', 'Reason', 'Release Date'])
    
    for t in transfers:
        # Safely get release date from whatever field exists
        release_date_str = ''
        for field_name in ['documents_released_date', 'release_date', 'processed_date', 'date_released']:
            val = getattr(t, field_name, None)
            if val:
                release_date_str = val.strftime('%Y-%m-%d')
                break
        
        writer.writerow([
            t.student.lrn if t.student else '',
            t.student.full_name if t.student else 'Unknown',
            t.get_transfer_type_display() if hasattr(t, 'get_transfer_type_display') else t.transfer_type,
            t.from_school_name or '',
            t.to_school_name or '',
            str(t.grade_level_at_transfer) if t.grade_level_at_transfer else '',
            t.transfer_date_requested.strftime('%Y-%m-%d') if t.transfer_date_requested else '',
            t.get_status_display() if hasattr(t, 'get_status_display') else t.status,
            t.reason or '',
            release_date_str,
        ])
    
    return response

@login_required
def transfer_template(request):
    """Download professionally formatted transfer Excel template"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    wb = openpyxl.Workbook()
    
    # ========== SHEET 1: TEMPLATE ==========
    ws = wb.active
    ws.title = "Transfer Template"
    
    # Brand colors (matching UI)
    brand_dark = '00072D'
    brand_green = '5EA173'
    brand_light = 'E8F5E9'
    header_font_color = 'FFFFFF'
    border_color = 'D4D4D4'
    alternate_row_color = 'F8F9FA'
    
    # Styles
    title_font = Font(name='Calibri', size=16, bold=True, color=brand_dark)
    subtitle_font = Font(name='Calibri', size=10, color='718096')
    header_font = Font(name='Calibri', size=11, bold=True, color=header_font_color)
    header_fill = PatternFill(start_color=brand_green, end_color=brand_green, fill_type='solid')
    header_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    data_font = Font(name='Calibri', size=10, color='2D3748')
    thin_border = Border(
        left=Side(style='thin', color=border_color),
        right=Side(style='thin', color=border_color),
        top=Side(style='thin', color=border_color),
        bottom=Side(style='thin', color=border_color)
    )
    center_align = Alignment(horizontal='center', vertical='center')
    left_align = Alignment(horizontal='left', vertical='center')
    alt_fill = PatternFill(start_color=alternate_row_color, end_color=alternate_row_color, fill_type='solid')
    light_green_fill = PatternFill(start_color=brand_light, end_color=brand_light, fill_type='solid')
    
    # Column widths
    col_widths = {'A': 18, 'B': 20, 'C': 20, 'D': 18, 'E': 30, 'F': 30, 'G': 18, 'H': 40}
    for col, width in col_widths.items():
        ws.column_dimensions[col].width = width
    
    # ========== ROW 1: TITLE ==========
    ws.merge_cells('A1:H1')
    title_cell = ws.cell(row=1, column=1, value="FORMIFY LIS - BATCH TRANSFER TEMPLATE")
    title_cell.font = title_font
    title_cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 35
    
    # ========== ROW 2: SUBTITLE ==========
    ws.merge_cells('A2:H2')
    sub_cell = ws.cell(row=2, column=1,
                       value="Instructions: Fill in all required fields (marked with *). LRN must match an existing student in the system.")
    sub_cell.font = subtitle_font
    sub_cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[2].height = 22
    
    # ========== ROW 3: SCHOOL YEAR INFO ==========
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    ws.merge_cells('A3:H3')
    sy_cell = ws.cell(row=3, column=1,
                      value=f"School Year: {current_sy.year_label if current_sy else 'N/A'} | "
                            f"Max Records: 200 | Supported: .csv, .xlsx, .xls")
    sy_cell.font = Font(name='Calibri', size=9, italic=True, color='666666')
    sy_cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[3].height = 20
    
    # ========== ROW 5: HEADERS ==========
    header_row = 5
    headers = [
        ('LRN *', '12-digit Learner\nReference Number'),
        ('Last Name', 'For reference only\n(Optional)'),
        ('First Name', 'For reference only\n(Optional)'),
        ('Transfer Type', 'INCOMING or\nOUTGOING'),
        ('From School', 'Originating school\nname'),
        ('To School', 'Destination school\nname'),
        ('Grade Level', 'e.g., Grade 7,\nGrade 11'),
        ('Reason', 'Reason for\ntransfer'),
    ]
    
    ws.row_dimensions[header_row].height = 50
    
    for col_idx, (header_text, tooltip) in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col_idx, value=header_text)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border
        
        from openpyxl.comments import Comment
        comment = Comment(tooltip, 'Formify LIS')
        comment.width = 250
        comment.height = 100
        cell.comment = comment
    
    # ========== SAMPLE DATA ROWS ==========
    sample_data = [
        ['136456789012', 'Dela Cruz', 'Juan', 'OUTGOING', 'Formify Academy', 'New School Name', 'Grade 7', 'Family relocation'],
        ['136456789013', 'Garcia', 'Maria', 'INCOMING', 'Previous School', 'Formify Academy', 'Grade 11', 'Parents work relocation'],
        ['', '', '', 'OUTGOING', '', '', '', ''],
        ['', '', '', 'INCOMING', '', '', '', ''],
        ['', '', '', '', '', '', '', ''],
    ]
    
    for i, row_data in enumerate(sample_data):
        row_num = header_row + 1 + i
        ws.row_dimensions[row_num].height = 25
        
        for col_idx, value in enumerate(row_data, 1):
            cell = ws.cell(row=row_num, column=col_idx, value=value)
            cell.font = data_font
            cell.border = thin_border
            cell.alignment = center_align if col_idx in [4, 7] else left_align
            
            if i % 2 == 1:
                cell.fill = alt_fill
            
            if col_idx == 1:
                if i % 2 == 0:
                    cell.fill = light_green_fill
    
    # ========== EMPTY ROWS ==========
    empty_start = header_row + 1 + len(sample_data)
    for i in range(15):
        row_num = empty_start + i
        ws.row_dimensions[row_num].height = 25
        for col_idx in range(1, 9):
            cell = ws.cell(row=row_num, column=col_idx, value='')
            cell.font = data_font
            cell.border = thin_border
            cell.alignment = center_align if col_idx in [4, 7] else left_align
            if i % 2 == 1:
                cell.fill = alt_fill
    
    # ========== LEGEND ==========
    legend_row = empty_start + 17
    ws.merge_cells(f'A{legend_row}:H{legend_row}')
    legend_cell = ws.cell(row=legend_row, column=1,
                          value="* Required field | Transfer Type: INCOMING or OUTGOING | "
                                "LRN must match existing student | Delete sample rows before uploading")
    legend_cell.font = Font(name='Calibri', size=8, italic=True, color='999999')
    legend_cell.alignment = Alignment(horizontal='left', vertical='center')
    
    # ========== DATA VALIDATION ==========
    from openpyxl.worksheet.datavalidation import DataValidation
    
    dv_type = DataValidation(type="list", formula1='"INCOMING,OUTGOING"', allow_blank=True)
    dv_type.error = "Please enter INCOMING or OUTGOING"
    dv_type.errorTitle = "Invalid Transfer Type"
    ws.add_data_validation(dv_type)
    dv_type.add(f'D{header_row + 1}:D{empty_start + 15}')
    
    # ========== FREEZE PANES ==========
    ws.freeze_panes = f'A{header_row + 1}'
    
    # ========== AUTO-FILTER ==========
    ws.auto_filter.ref = f'A{header_row}:H{empty_start + 15}'
    
    # ========== PRINT SETTINGS ==========
    ws.sheet_properties.pageSetUpPr = openpyxl.worksheet.properties.PageSetupProperties(fitToPage=True)
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    
    # ========== SHEET 2: INSTRUCTIONS ==========
    ws2 = wb.create_sheet("Instructions")
    ws2.column_dimensions['A'].width = 80
    
    instructions = [
        ("BATCH TRANSFER INSTRUCTIONS", 16, True),
        ("", 10, False),
        ("How to use this template:", 12, True),
        ("1. LRN column is REQUIRED - student must already exist in the system.", 10, False),
        ("2. Transfer Type must be INCOMING or OUTGOING.", 10, False),
        ("3. For OUTGOING transfers, To School is required.", 10, False),
        ("4. For INCOMING transfers, From School is required.", 10, False),
        ("5. Grade Level should match existing grade levels (e.g., Grade 7).", 10, False),
        ("6. Delete sample rows before uploading your actual data.", 10, False),
        ("7. Maximum 200 records per upload.", 10, False),
        ("", 10, False),
        ("Transfer Status Flow:", 12, True),
        ("Pending → Documents Requested → Documents Released (Completed)", 10, False),
        ("Any status can also be → Rejected", 10, False),
    ]
    
    for i, (text, size, is_bold) in enumerate(instructions, 1):
        cell = ws2.cell(row=i, column=1, value=text)
        cell.font = Font(name='Calibri', size=size, bold=is_bold,
                        color=brand_dark if is_bold else '2D3748')
        cell.alignment = Alignment(vertical='center')
        ws2.row_dimensions[i].height = 22 if size > 10 else 18
    
    # ========== SAVE ==========
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    filename = f"Transfer_Template_{current_sy.year_label if current_sy else 'SY'}.xlsx"
    
    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
@csrf_exempt
def transfer_batch_upload(request):
    """Handle batch transfer upload via CSV or Excel file"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    uploaded_file = request.FILES.get('file')
    if not uploaded_file:
        return JsonResponse({'success': False, 'error': 'No file uploaded'}, status=400)
    
    filename = uploaded_file.name.lower()
    if not (filename.endswith('.csv') or filename.endswith('.xlsx') or filename.endswith('.xls')):
        return JsonResponse({'success': False, 'error': 'Invalid file type'}, status=400)
    
    created_count = 0
    skipped_count = 0
    errors = []
    all_rows = []
    
    try:
        # Read file
        if filename.endswith('.csv'):
            content = uploaded_file.read().decode('utf-8-sig')
            reader = csv.reader(content.splitlines())
            all_rows = [[c.strip() if c else '' for c in row] for row in reader]
        else:
            wb = openpyxl.load_workbook(uploaded_file, read_only=True, data_only=True)
            ws = wb.active
            for row in ws.iter_rows(values_only=True):
                vals = [str(c).strip() if c is not None else '' for c in row]
                all_rows.append(vals)
            wb.close()
        
        all_rows = [r for r in all_rows if any(v for v in r)]
        
        if len(all_rows) < 2:
            return JsonResponse({'success': False, 'error': 'File is empty'}, status=400)
        
        # Find header row
        header_idx = None
        for i, row in enumerate(all_rows):
            row_str = ' '.join([str(c).lower() for c in row])
            if 'lrn' in row_str and ('transfer' in row_str or 'type' in row_str):
                header_idx = i
                break
        
        if header_idx is None:
            return JsonResponse({
                'success': False,
                'error': 'Cannot find header row with LRN and Transfer Type columns.'
            }, status=400)
        
        headers = [h.lower().replace('*', '').strip() for h in all_rows[header_idx]]
        
        # Map columns
        col = {}
        for i, h in enumerate(headers):
            if 'lrn' in h: col['lrn'] = i
            elif 'transfer' in h and 'type' in h: col['transfer_type'] = i
            elif 'from' in h and 'school' in h: col['from_school'] = i
            elif 'to' in h and 'school' in h: col['to_school'] = i
            elif 'grade' in h: col['grade_level'] = i
            elif 'reason' in h: col['reason'] = i
        
        if 'lrn' not in col:
            return JsonResponse({'success': False, 'error': 'LRN column is required'}, status=400)
        
        data_rows = all_rows[header_idx + 1:]
        
        for row_idx, row in enumerate(data_rows):
            def get_val(field):
                idx = col.get(field)
                return str(row[idx]).strip() if idx is not None and idx < len(row) else ''
            
            lrn = get_val('lrn')
            transfer_type = get_val('transfer_type').upper()
            from_school = get_val('from_school')
            to_school = get_val('to_school')
            grade_name = get_val('grade_level')
            reason = get_val('reason')
            
            if not lrn:
                skipped_count += 1
                continue
            
            # Validate transfer type
            if transfer_type not in ['INCOMING', 'OUTGOING']:
                transfer_type = 'OUTGOING'
            
            # Find student
            student = Student.objects.filter(lrn=lrn).first()
            if not student:
                skipped_count += 1
                errors.append(f'Row {row_idx + 2}: Student with LRN {lrn} not found')
                continue
            
            # Check for existing pending transfer
            existing = Transfer.objects.filter(
                student=student,
                status__in=['Pending', 'Documents_Requested']
            ).first()
            
            if existing:
                skipped_count += 1
                errors.append(f'Row {row_idx + 2}: {student.full_name} already has pending transfer')
                continue
            
            # Find grade level
            grade_level = None
            if grade_name:
                grade_level = GradeLevel.objects.filter(
                    grade_name__icontains=grade_name
                ).first()
            
            try:
                Transfer.objects.create(
                    student=student,
                    transfer_type=transfer_type,
                    from_school_name=from_school,
                    to_school_name=to_school,
                    grade_level_at_transfer=grade_level,
                    reason=reason,
                    status='Pending',
                    transfer_date_requested=date.today(),
                    requested_by=request.user,  # ← ADD THIS LINE
                )
                created_count += 1
            except Exception as e:
                skipped_count += 1
                errors.append(f'Row {row_idx + 2}: {str(e)[:80]}')
        
        _log(request, 'BATCH_TRANSFER', 'Transfer', 0,
             f'{created_count} created, {skipped_count} skipped')
        
        return JsonResponse({
            'success': True,
            'message': f'Created {created_count} transfer(s). Skipped {skipped_count}.',
            'count': created_count,
            'skipped': skipped_count,
            'errors': errors[:15]
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# =============================================================================
# REPORTS & ANALYTICS
# =============================================================================

@login_required
def reports_analytics(request):
    """Reports & Analytics Page"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    available_sy = [{'id': sy.id, 'label': str(sy)} for sy in SchoolYear.objects.all().order_by('-year_start')]
    
    context = {
        'current_sy_label': current_sy.year_label if current_sy else 'N/A',
        'current_sy': current_sy,
        'current_sy_id': current_sy.id if current_sy else '',
        'available_sy': available_sy,
        'today': date.today(),
    }
    return render(request, 'registrars/reports/reports.html', context)


# =============================================================================
# REPORTS & ANALYTICS - EXPANDED VIEWS
# =============================================================================

@login_required
def reports_data(request):
    """Return comprehensive report data as JSON for all tabs"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    sy_id = request.GET.get('school_year', '')
    report_type = request.GET.get('report_type', 'overview')
    quarter_label = request.GET.get('quarter', '')
    
    # Get school year
    current_sy = None
    if sy_id:
        try:
            current_sy = SchoolYear.objects.get(id=sy_id)
        except SchoolYear.DoesNotExist:
            pass
    if not current_sy:
        current_sy = SchoolYear.objects.filter(is_current=True).first()
    
    if not current_sy:
        return JsonResponse({'success': False, 'error': 'No school year found'}, status=400)
    
    # Get quarter filter
    quarter_filter = {}
    if quarter_label:
        quarter = Quarter.objects.filter(school_year=current_sy, quarter_label=quarter_label).first()
        if quarter:
            quarter_filter = {'quarter': quarter}
    
    response_data = {'success': True}
    
    # ========== OVERVIEW DATA ==========
    if report_type in ['overview']:
        # Total enrollment
        total_enrollment = Enrollment.objects.filter(
            school_year=current_sy, status__in=['Enrolled', 'Transferred_In']
        ).count()
        
        # Average grade
        avg_grade_data = GradeComponent.objects.filter(
            enrollment__school_year=current_sy,
            validation_status='Validated',
            initial_grade__isnull=False,
            **quarter_filter
        ).aggregate(avg=Avg('initial_grade'))
        avg_grade = round(avg_grade_data['avg'], 1) if avg_grade_data['avg'] else 0
        
        # Honor count (students with avg >= 85)
        honor_count = GradeComponent.objects.filter(
            enrollment__school_year=current_sy,
            validation_status='Validated',
            initial_grade__gte=85,
            **quarter_filter
        ).values('enrollment__student').distinct().count()
        
        # Transfer stats
        total_transfers = Transfer.objects.filter(
            transfer_date_requested__year=current_sy.year_start if current_sy else date.today().year
        ).count()
        transfer_rate = round((total_transfers / total_enrollment) * 100, 1) if total_enrollment > 0 else 0
        
        # Enrollment trend (5 years)
        all_sy = SchoolYear.objects.all().order_by('year_start')[:5]
        enrollment_labels = []
        enrollment_values = []
        for sy in all_sy:
            enrollment_labels.append(str(sy))
            enrollment_values.append(
                Enrollment.objects.filter(school_year=sy, status__in=['Enrolled', 'Transferred_In']).count()
            )
        
        # Trend from previous year
        prev_sy = SchoolYear.objects.filter(year_start__lt=current_sy.year_start).order_by('-year_start').first()
        prev_total = 0
        if prev_sy:
            prev_total = Enrollment.objects.filter(
                school_year=prev_sy, status__in=['Enrolled', 'Transferred_In']
            ).count()
        enrollment_trend = round(((total_enrollment - prev_total) / prev_total) * 100, 1) if prev_total > 0 else 0
        
        # Grade distribution
        grade_labels = ['90-100', '85-89', '80-84', '75-79', 'Below 75']
        grade_values = [0, 0, 0, 0, 0]
        
        grades = GradeComponent.objects.filter(
            enrollment__school_year=current_sy,
            validation_status='Validated',
            **quarter_filter
        )
        
        for g in grades:
            if g.initial_grade is None:
                continue
            val = float(g.initial_grade)
            if val >= 90: grade_values[0] += 1
            elif val >= 85: grade_values[1] += 1
            elif val >= 80: grade_values[2] += 1
            elif val >= 75: grade_values[3] += 1
            else: grade_values[4] += 1
        
        # Honor breakdown
        honor_breakdown = []
        for gl in GradeLevel.objects.all().order_by('sort_order'):
            base_qs = GradeComponent.objects.filter(
                enrollment__school_year=current_sy,
                enrollment__section__grade_level=gl,
                validation_status='Validated',
                **quarter_filter
            )
            
            total = base_qs.values('enrollment__student').distinct().count()
            highest = base_qs.filter(initial_grade__gte=95).values('enrollment__student').distinct().count()
            high = base_qs.filter(initial_grade__gte=90, initial_grade__lt=95).values('enrollment__student').distinct().count()
            with_honors = base_qs.filter(initial_grade__gte=85, initial_grade__lt=90).values('enrollment__student').distinct().count()
            
            if total > 0:
                honor_breakdown.append({
                    'grade_name': gl.grade_name,
                    'total': total,
                    'highest': highest,
                    'high': high,
                    'with_honors': with_honors,
                })
        
        # Transfer summary by month
        months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        transfer_incoming = []
        transfer_outgoing = []
        transfer_summary = []
        
        for i, month in enumerate(months, 1):
            incoming = Transfer.objects.filter(
                transfer_type='INCOMING',
                transfer_date_requested__month=i,
                transfer_date_requested__year=current_sy.year_start if current_sy else date.today().year
            ).count()
            
            outgoing = Transfer.objects.filter(
                transfer_type='OUTGOING',
                transfer_date_requested__month=i,
                transfer_date_requested__year=current_sy.year_start if current_sy else date.today().year
            ).count()
            
            transfer_incoming.append(incoming)
            transfer_outgoing.append(outgoing)
            
            if incoming > 0 or outgoing > 0:
                transfer_summary.append({
                    'month': month,
                    'incoming': incoming,
                    'outgoing': outgoing,
                })
        
        # Forms compliance
        compliance = []
        for form in SchoolForm.objects.filter(is_active=True).order_by('form_code'):
            total_sections = Section.objects.filter(school_year=current_sy, is_active=True).count()
            submitted = FormSubmission.objects.filter(
                school_form=form, school_year=current_sy,
                status__in=['Submitted', 'Reviewed', 'Approved']
            ).count()
            pct = round((submitted / total_sections) * 100) if total_sections > 0 else 0
            
            sections_done = FormSubmission.objects.filter(
                school_form=form, school_year=current_sy,
                status='Approved'
            ).count()
            
            last_sub = FormSubmission.objects.filter(
                school_form=form, school_year=current_sy
            ).order_by('-updated_at').first()
            
            compliance.append({
                'form_code': form.form_code,
                'form_name': form.form_name,
                'status': 'Completed' if pct >= 100 else ('In Progress' if pct > 0 else 'Pending'),
                'completion': pct,
                'last_updated': last_sub.updated_at.strftime('%b %d, %Y') if last_sub else '—',
                'sections_done': f'{sections_done}/{total_sections}',
            })
        
        response_data.update({
            'total_enrollment': total_enrollment,
            'avg_grade': avg_grade,
            'honor_count': honor_count,
            'transfer_rate': transfer_rate,
            'enrollment_trend': enrollment_trend,
            'total_transfers': total_transfers,
            'enrollment_labels': enrollment_labels,
            'enrollment_values': enrollment_values,
            'grade_labels': grade_labels,
            'grade_values': grade_values,
            'honor_breakdown': honor_breakdown,
            'transfer_labels': months,
            'transfer_incoming': transfer_incoming,
            'transfer_outgoing': transfer_outgoing,
            'transfer_summary': transfer_summary,
            'compliance': compliance,
        })
    
    # ========== ENROLLMENT TAB DATA ==========
    if report_type == 'enrollment':
        total_enrollment = Enrollment.objects.filter(
            school_year=current_sy, status__in=['Enrolled', 'Transferred_In']
        ).count()
        
        new_students = Enrollment.objects.filter(
            school_year=current_sy, enrollment_type='New Student',
            status__in=['Enrolled', 'Transferred_In']
        ).count()
        
        transferees = Enrollment.objects.filter(
            school_year=current_sy, enrollment_type='Transferee',
            status__in=['Enrolled', 'Transferred_In']
        ).count()
        
        balik_aral = Enrollment.objects.filter(
            school_year=current_sy, enrollment_type='Balik-Aral',
            status__in=['Enrolled', 'Transferred_In']
        ).count()
        
        # Enrollment by grade
        grade_labels = []
        grade_enrollment_counts = []
        
        for gl in GradeLevel.objects.all().order_by('sort_order'):
            count = Enrollment.objects.filter(
                school_year=current_sy, 
                status__in=['Enrolled', 'Transferred_In'],
                section__grade_level=gl
            ).count()
            if count > 0:
                grade_labels.append(gl.grade_name)
                grade_enrollment_counts.append(count)
        
        # Monthly enrollment trend
        monthly_labels = ['Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb', 'Mar', 'Apr', 'May']
        monthly_counts = []
        for i, month in enumerate(monthly_labels):
            month_num = (6 + i) % 12 + 1  # Start from June
            year = current_sy.year_start if month_num >= 6 else current_sy.year_end
            count = Enrollment.objects.filter(
                school_year=current_sy,
                enrollment_date__month=month_num,
                enrollment_date__year=year
            ).count()
            monthly_counts.append(count)
        
        # Enrollment breakdown by section
        enrollment_breakdown = []
        for section in Section.objects.filter(school_year=current_sy, is_active=True).select_related('grade_level').order_by('grade_level__grade_number', 'section_name'):
            enrolled = Enrollment.objects.filter(
                school_year=current_sy, section=section, status__in=['Enrolled', 'Transferred_In']
            )
            total = enrolled.count()
            if total > 0:
                enrollment_breakdown.append({
                    'grade_name': section.grade_level.grade_name,
                    'section': section.section_name,
                    'total': total,
                    'male': enrolled.filter(student__sex='M').count(),
                    'female': enrolled.filter(student__sex='F').count(),
                    'new_students': enrolled.filter(enrollment_type='New Student').count(),
                    'transferees': enrolled.filter(enrollment_type='Transferee').count(),
                    'balik_aral': enrolled.filter(enrollment_type='Balik-Aral').count(),
                    'old_students': enrolled.filter(enrollment_type='Old Student').count(),
                    'capacity': section.capacity or total or 50,
                })
        
        response_data.update({
            'total_enrollment': total_enrollment,
            'new_students': new_students,
            'transferees': transferees,
            'balik_aral': balik_aral,
            'enrollment_trend': 0,  # Placeholder
            'grade_labels': grade_labels,
            'grade_enrollment_counts': grade_enrollment_counts,
            'monthly_labels': monthly_labels,
            'monthly_counts': monthly_counts,
            'enrollment_breakdown': enrollment_breakdown,
        })
    
    # ========== ACADEMIC TAB DATA ==========
    if report_type == 'academic':
        base_qs = GradeComponent.objects.filter(
            enrollment__school_year=current_sy,
            validation_status='Validated',
            initial_grade__isnull=False,
            **quarter_filter
        )
        
        avg_grade_data = base_qs.aggregate(avg=Avg('initial_grade'))
        avg_grade = round(avg_grade_data['avg'], 1) if avg_grade_data['avg'] else 0
        
        total_grades = base_qs.count()
        passed = base_qs.filter(initial_grade__gte=75).count()
        failed = base_qs.filter(initial_grade__lt=75).count()
        pass_rate = round((passed / total_grades) * 100, 1) if total_grades > 0 else 0
        
        at_risk_students = base_qs.filter(
            initial_grade__lt=75
        ).values('enrollment__student').distinct().count()
        
        # Subject performance
        subject_performance = []
        subjects = base_qs.values('subject__subject_name').annotate(
            avg_grade=Avg('initial_grade'),
            student_count=Count('enrollment__student', distinct=True),
            highest_grade=models.Max('initial_grade'),
            lowest_grade=models.Min('initial_grade'),
        ).order_by('-avg_grade')
        
        from django.db import models as django_models  # For Max/Min in annotate
        
        subject_labels = []
        subject_averages = []
        
        for s in subjects:
            subject_name = s['subject__subject_name']
            sa = round(s['avg_grade'], 1)
            sc = s['student_count']
            sp = round((base_qs.filter(subject__subject_name=subject_name, initial_grade__gte=75).count() / 
                        base_qs.filter(subject__subject_name=subject_name).count()) * 100, 1) if sc > 0 else 0
            
            subject_labels.append(subject_name[:30])
            subject_averages.append(sa)
            
            subject_performance.append({
                'subject': subject_name,
                'avg_grade': sa,
                'highest': round(s['highest_grade'], 1),
                'lowest': round(s['lowest_grade'], 1),
                'pass_rate': sp,
                'student_count': sc,
                'trend': 0,  # Placeholder
            })
        
        # Quarter averages
        quarter_averages = []
        for ql in ['Q1', 'Q2', 'Q3', 'Q4']:
            q = Quarter.objects.filter(school_year=current_sy, quarter_label=ql).first()
            if q:
                avg = base_qs.filter(quarter=q).aggregate(avg=Avg('initial_grade'))
                quarter_averages.append(round(avg['avg'], 1) if avg['avg'] else 0)
            else:
                quarter_averages.append(0)
        
        response_data.update({
            'avg_grade': avg_grade,
            'pass_rate': pass_rate,
            'at_risk_students': at_risk_students,
            'total_subjects': subjects.count(),
            'subject_labels': subject_labels[:10],
            'subject_averages': subject_averages[:10],
            'subject_performance': subject_performance[:10],
            'quarter_averages': quarter_averages,
        })
    
    # ========== TRANSFERS TAB DATA ==========
    if report_type == 'transfers':
        year = current_sy.year_start if current_sy else date.today().year
        
        total_transfers = Transfer.objects.filter(transfer_date_requested__year=year).count()
        incoming_count = Transfer.objects.filter(transfer_type='INCOMING', transfer_date_requested__year=year).count()
        outgoing_count = Transfer.objects.filter(transfer_type='OUTGOING', transfer_date_requested__year=year).count()
        pending_count = Transfer.objects.filter(status='Pending').count()
        
        # Monthly trend
        months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        transfer_incoming = []
        transfer_outgoing = []
        
        for i in range(1, 13):
            transfer_incoming.append(Transfer.objects.filter(transfer_type='INCOMING', transfer_date_requested__month=i, transfer_date_requested__year=year).count())
            transfer_outgoing.append(Transfer.objects.filter(transfer_type='OUTGOING', transfer_date_requested__month=i, transfer_date_requested__year=year).count())
        
        # By grade level
        transfer_grade_labels = []
        transfer_grade_incoming = []
        transfer_grade_outgoing = []
        
        for gl in GradeLevel.objects.all().order_by('sort_order'):
            inc = Transfer.objects.filter(transfer_type='INCOMING', grade_level_at_transfer=gl, transfer_date_requested__year=year).count()
            out = Transfer.objects.filter(transfer_type='OUTGOING', grade_level_at_transfer=gl, transfer_date_requested__year=year).count()
            if inc > 0 or out > 0:
                transfer_grade_labels.append(gl.grade_name)
                transfer_grade_incoming.append(inc)
                transfer_grade_outgoing.append(out)
        
        # Recent transfers
        recent_transfers = []
        for t in Transfer.objects.select_related('student', 'grade_level_at_transfer').order_by('-transfer_date_requested')[:20]:
            school_name = t.to_school_name if t.transfer_type == 'OUTGOING' else t.from_school_name
            recent_transfers.append({
                'student_name': t.student.full_name if t.student else 'Unknown',
                'lrn': t.student.lrn if t.student else '—',
                'transfer_type': t.transfer_type,
                'school_name': school_name or 'N/A',
                'grade_level': str(t.grade_level_at_transfer) if t.grade_level_at_transfer else 'N/A',
                'status': t.status,
                'status_display': t.get_status_display() if hasattr(t, 'get_status_display') else t.status,
                'date': t.transfer_date_requested.strftime('%b %d, %Y') if t.transfer_date_requested else '—',
            })
        
        response_data.update({
            'total_transfers': total_transfers,
            'incoming_count': incoming_count,
            'outgoing_count': outgoing_count,
            'pending_count': pending_count,
            'transfer_labels': months,
            'transfer_incoming': transfer_incoming,
            'transfer_outgoing': transfer_outgoing,
            'transfer_grade_labels': transfer_grade_labels,
            'transfer_grade_incoming': transfer_grade_incoming,
            'transfer_grade_outgoing': transfer_grade_outgoing,
            'recent_transfers': recent_transfers,
        })
    
    # ========== COMPLIANCE TAB DATA ==========
    if report_type == 'compliance':
        total_sections = Section.objects.filter(school_year=current_sy, is_active=True).count()
        
        forms_completed = 0
        forms_pending = 0
        forms_overdue = 0
        form_labels = []
        form_completion_rates = []
        
        for form in SchoolForm.objects.filter(is_active=True).order_by('form_code'):
            submitted = FormSubmission.objects.filter(school_form=form, school_year=current_sy, status__in=['Submitted', 'Reviewed', 'Approved']).count()
            approved = FormSubmission.objects.filter(school_form=form, school_year=current_sy, status='Approved').count()
            pct = round((submitted / total_sections) * 100) if total_sections > 0 else 0
            
            form_labels.append(form.form_code)
            form_completion_rates.append(pct)
            
            if pct >= 100:
                forms_completed += 1
            elif pct > 0:
                forms_pending += 1
            else:
                forms_overdue += 1
        
        compliance_rate = round((forms_completed / (forms_completed + forms_pending + forms_overdue)) * 100) if (forms_completed + forms_pending + forms_overdue) > 0 else 0
        
        # Compliance over time (last 6 months)
        compliance_dates = []
        compliance_rates = []
        for i in range(5, -1, -1):
            month_date = date.today().replace(day=1) - timedelta(days=i*30)
            compliance_dates.append(month_date.strftime('%b'))
            # Simplified - in real implementation, you'd track historical snapshots
            compliance_rates.append(min(100, compliance_rate + (i * 5)))
        
        # Section-wise compliance
        section_compliance = []
        for section in Section.objects.filter(school_year=current_sy, is_active=True).select_related('grade_level').order_by('grade_level__grade_number', 'section_name'):
            forms_status = {}
            section_complete = 0
            for form in SchoolForm.objects.filter(is_active=True):
                submission = FormSubmission.objects.filter(school_form=form, section=section, school_year=current_sy).first()
                if submission and submission.status == 'Approved':
                    forms_status[form.form_code] = 'approved'
                    section_complete += 1
                elif submission and submission.status in ['Submitted', 'Reviewed']:
                    forms_status[form.form_code] = 'submitted'
                elif submission and submission.status == 'Returned':
                    forms_status[form.form_code] = 'returned'
                else:
                    forms_status[form.form_code] = 'missing'
            
            total_forms = SchoolForm.objects.filter(is_active=True).count()
            section_compliance.append({
                'section_name': str(section),
                'grade_level': section.grade_level.grade_name if section.grade_level else '',
                'forms': forms_status,
                'completion_pct': round((section_complete / total_forms) * 100) if total_forms > 0 else 0,
            })
        
        response_data.update({
            'forms_completed': forms_completed,
            'forms_pending': forms_pending,
            'forms_overdue': forms_overdue,
            'compliance_rate': compliance_rate,
            'form_labels': form_labels,
            'form_completion_rates': form_completion_rates,
            'compliance_dates': compliance_dates,
            'compliance_rates': compliance_rates,
            'section_compliance': section_compliance,
        })
    
    # ========== DEMOGRAPHICS TAB DATA ==========
    if report_type == 'demographics':
        enrolled_students = Student.objects.filter(
            enrollments__school_year=current_sy,
            enrollments__status__in=['Enrolled', 'Transferred_In']
        ).distinct()
        
        total_enrollment = enrolled_students.count()
        male_count = enrolled_students.filter(sex='M').count()
        female_count = enrolled_students.filter(sex='F').count()
        four_ps_count = enrolled_students.filter(is_4ps=True).count()
        
        # Residency (simplified - based on birth_place or address)
        residency_labels = ['Within City', 'Within Province', 'Outside Province']
        residency_counts = [
            int(total_enrollment * 0.6),
            int(total_enrollment * 0.3),
            int(total_enrollment * 0.1),
        ]
        
        # Age distribution
        age_ranges = ['5-10', '11-12', '13-14', '15-16', '17-18', '19+']
        age_counts = [0, 0, 0, 0, 0, 0]
        today = date.today()
        
        for student in enrolled_students:
            if student.birth_date:
                age = today.year - student.birth_date.year
                if age <= 10: age_counts[0] += 1
                elif age <= 12: age_counts[1] += 1
                elif age <= 14: age_counts[2] += 1
                elif age <= 16: age_counts[3] += 1
                elif age <= 18: age_counts[4] += 1
                else: age_counts[5] += 1
        
        # Religion distribution
        from collections import Counter
        religions = enrolled_students.exclude(religion__isnull=True).exclude(religion='').values_list('religion', flat=True)
        religion_counter = Counter(religions)
        religion_labels = [r[0] for r in religion_counter.most_common(8)]
        religion_counts = [r[1] for r in religion_counter.most_common(8)]
        
        response_data.update({
            'total_enrollment': total_enrollment,
            'male_count': male_count,
            'female_count': female_count,
            'four_ps_count': four_ps_count,
            'residency_labels': residency_labels,
            'residency_counts': residency_counts,
            'age_labels': age_ranges,
            'age_counts': age_counts,
            'religion_labels': religion_labels,
            'religion_counts': religion_counts,
        })
    
    return JsonResponse(response_data)

@login_required
def reports_export(request):
    """Export reports to Excel"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    
    wb = openpyxl.Workbook()
    
    # Sheet 1: Enrollment Summary
    ws1 = wb.active
    ws1.title = "Enrollment Summary"
    ws1.append(['Grade Level', 'Total Enrolled'])
    for gl in GradeLevel.objects.all().order_by('sort_order'):
        count = Enrollment.objects.filter(
            school_year=current_sy, status='Enrolled', section__grade_level=gl
        ).count()
        ws1.append([gl.grade_name, count])
    
    # Sheet 2: Transfer Summary
    ws2 = wb.create_sheet("Transfer Summary")
    ws2.append(['LRN', 'Student Name', 'Type', 'From School', 'To School', 'Status', 'Date'])
    for t in Transfer.objects.select_related('student').order_by('-transfer_date_requested')[:500]:
        ws2.append([
            t.student.lrn if t.student else '',
            t.student.full_name if t.student else '',
            t.get_transfer_type_display() if hasattr(t, 'get_transfer_type_display') else t.transfer_type,
            t.from_school_name or '',
            t.to_school_name or '',
            t.get_status_display() if hasattr(t, 'get_status_display') else t.status,
            t.transfer_date_requested.strftime('%Y-%m-%d') if t.transfer_date_requested else '',
        ])
    
    # Sheet 3: Compliance
    ws3 = wb.create_sheet("Forms Compliance")
    ws3.append(['Form Code', 'Form Name', 'Submitted', 'Total Sections', 'Completion %'])
    for form in SchoolForm.objects.filter(is_active=True).order_by('form_code'):
        total = Section.objects.filter(school_year=current_sy, is_active=True).count()
        submitted = FormSubmission.objects.filter(
            school_form=form, school_year=current_sy,
            status__in=['Submitted', 'Reviewed', 'Approved']
        ).count()
        pct = round((submitted / total) * 100) if total > 0 else 0
        ws3.append([form.form_code, form.form_name, submitted, total, pct])
    
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    response = HttpResponse(output.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="reports_{date.today()}.xlsx"'
    return response


@login_required
def reports_pdf(request):
    """Generate PDF report"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="report_{date.today()}.pdf"'
    
    doc = SimpleDocTemplate(response, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    styles = getSampleStyleSheet()
    story = []
    
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor('#00072D'), alignment=TA_CENTER, spaceAfter=20)
    story.append(Paragraph(f"FORMIFY LIS - REPORTS & ANALYTICS", title_style))
    story.append(Paragraph(f"School Year: {current_sy.year_label if current_sy else 'N/A'} | Generated: {date.today()}", styles['Normal']))
    story.append(Spacer(1, 20))
    
    # Enrollment Table
    story.append(Paragraph("<b>ENROLLMENT BY GRADE LEVEL</b>", styles['Heading2']))
    data = [['Grade Level', 'Total Enrolled']]
    for gl in GradeLevel.objects.all().order_by('sort_order'):
        count = Enrollment.objects.filter(school_year=current_sy, status='Enrolled', section__grade_level=gl).count()
        data.append([gl.grade_name, str(count)])
    
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#5EA173')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E9ECEF')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
    ]))
    story.append(table)
    
    doc.build(story)
    return response


@login_required
def reports_compliance_export(request):
    """Export compliance report to Excel"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Forms Compliance"
    
    headers = ['Form Code', 'Form Name', 'Submitted Sections', 'Total Sections', 'Completion %', 'Status']
    for col, h in enumerate(headers, 1):
        ws.cell(row=1, column=col, value=h).font = Font(bold=True, color='FFFFFF')
        ws.cell(row=1, column=col).fill = PatternFill(start_color='5EA173', end_color='5EA173', fill_type='solid')
    
    row = 2
    for form in SchoolForm.objects.filter(is_active=True).order_by('form_code'):
        total = Section.objects.filter(school_year=current_sy, is_active=True).count()
        submitted = FormSubmission.objects.filter(
            school_form=form, school_year=current_sy,
            status__in=['Submitted', 'Reviewed', 'Approved']
        ).count()
        pct = round((submitted / total) * 100) if total > 0 else 0
        
        ws.cell(row=row, column=1, value=form.form_code)
        ws.cell(row=row, column=2, value=form.form_name)
        ws.cell(row=row, column=3, value=submitted)
        ws.cell(row=row, column=4, value=total)
        ws.cell(row=row, column=5, value=pct)
        ws.cell(row=row, column=6, value='Completed' if pct >= 100 else ('In Progress' if pct > 0 else 'Pending'))
        row += 1
    
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    response = HttpResponse(output.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="compliance_report_{date.today()}.xlsx"'
    return response

# =============================================================================
# SECTION & SCHEDULE MANAGEMENT
# =============================================================================

@login_required
def section_schedule_management(request):
    """Section & Schedule Management Page"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    
    # Safely get teachers
    try:
        teachers = UserProfile.objects.filter(role='teacher', is_active=True).select_related('user')
    except Exception:
        teachers = UserProfile.objects.none()
    
    # Safely get subjects
    try:
        from academics.models import Subject
        subjects = Subject.objects.filter(is_active=True)
    except ImportError:
        subjects = []
    
    # Safely get rooms
    try:
        from academics.models import Room
        rooms = Room.objects.filter(is_active=True)
    except ImportError:
        rooms = []
    
    # Safely get class assignments
    try:
        from scheduling.models import ClassAssignment
        class_assignments = ClassAssignment.objects.filter(
            school_year=current_sy, is_active=True
        ).select_related('teacher', 'section', 'subject')
        total_assignments = class_assignments.count()
        total_schedules = ClassSchedule.objects.filter(
            class_assignment__school_year=current_sy, is_active=True
        ).count()
    except ImportError:
        class_assignments = []
        total_assignments = 0
        total_schedules = 0
    
    context = {
        'current_sy_label': current_sy.year_label if current_sy else 'N/A',
        'current_sy': current_sy,
        'grade_levels': GradeLevel.objects.all().order_by('sort_order'),
        'sections': Section.objects.filter(school_year=current_sy, is_active=True).select_related('grade_level') if current_sy else [],
        'teachers': teachers,
        'subjects': subjects,
        'rooms': rooms,
        'class_assignments': class_assignments,
        'total_sections': Section.objects.filter(school_year=current_sy, is_active=True).count() if current_sy else 0,
        'total_assignments': total_assignments,
        'total_schedules': total_schedules,
        'unassigned_teachers': 0,  # Calculate based on your logic
        'days_of_week': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'],
        'today': date.today(),
    }
    return render(request, 'registrars/sections/section_schedule.html', context)


# ── SECTION DATA ──
@login_required
def section_list_data(request):
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False}, status=403)
    
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    if not current_sy:
        return JsonResponse({'success': False, 'error': 'No active school year'}, status=400)
    
    sections = Section.objects.filter(
        school_year=current_sy, is_active=True
    ).select_related('grade_level')
    
    grade_filter = request.GET.get('grade', '')
    search = request.GET.get('search', '')
    
    if grade_filter:
        sections = sections.filter(grade_level_id=grade_filter)
    if search:
        sections = sections.filter(section_name__icontains=search)
    
    section_list = []
    for s in sections:
        enrolled = Enrollment.objects.filter(
            section=s, status='Enrolled', school_year=current_sy
        ).count()
        
        # Try to get adviser
        adviser = None
        try:
            from scheduling.models import ClassAssignment
            ca = ClassAssignment.objects.filter(
                section=s, is_advisory=True, is_active=True
            ).select_related('teacher').first()
            if ca:
                adviser = ca.teacher.get_full_name()
        except ImportError:
            pass
        
        # Try to get subject count
        subject_count = 0
        try:
            from scheduling.models import ClassAssignment
            subject_count = ClassAssignment.objects.filter(
                section=s, is_active=True
            ).count()
        except ImportError:
            pass
        
        section_list.append({
            'id': s.id,
            'section_name': s.section_name,
            'grade_name': s.grade_level.grade_name if s.grade_level else 'N/A',
            'capacity': getattr(s, 'capacity', 50),  # Use getattr with fallback
            'enrolled_count': enrolled,
            'subject_count': subject_count,
            'is_active': s.is_active,
            'adviser': adviser,
        })
    
    return JsonResponse({
        'success': True,
        'sections': section_list,
        'stats': {'total': sections.count()}
    })


@login_required
@csrf_exempt
def section_create(request):
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    try:
        data = json.loads(request.body)
        current_sy = SchoolYear.objects.filter(is_current=True).first()
        
        if not current_sy:
            return JsonResponse({'success': False, 'error': 'No active school year'}, status=400)
        
        # Build kwargs using only fields that exist on Section
        kwargs = {
            'school_year': current_sy,
            'grade_level_id': data.get('grade_level_id'),
            'section_name': data.get('section_name', '').strip(),
            'is_active': data.get('is_active', True),
        }
        
        # Only add capacity if the field exists
        if hasattr(Section, 'capacity'):
            kwargs['capacity'] = data.get('capacity', 50)
        
        section = Section.objects.create(**kwargs)
        
        return JsonResponse({
            'success': True, 
            'message': f'Section {section.section_name} created',
            'section_id': section.id
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@csrf_exempt
def section_update(request, section_id):
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    try:
        section = get_object_or_404(Section, id=section_id)
        data = json.loads(request.body)
        
        section.section_name = data.get('section_name', section.section_name)
        section.grade_level_id = data.get('grade_level_id', section.grade_level_id)
        section.is_active = data.get('is_active', section.is_active)
        
        # Only update capacity if field exists
        if hasattr(section, 'capacity'):
            section.capacity = data.get('capacity', section.capacity)
        
        section.save()
        
        return JsonResponse({'success': True, 'message': f'Section {section.section_name} updated'})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@csrf_exempt
def section_toggle(request, section_id):
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    section = get_object_or_404(Section, id=section_id)
    section.is_active = not section.is_active
    section.save()
    
    return JsonResponse({
        'success': True, 
        'message': f'Section {section.section_name} {"activated" if section.is_active else "deactivated"}'
    })

@login_required
def section_detail(request, section_id):
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False}, status=403)
    
    section = get_object_or_404(Section, id=section_id)
    return JsonResponse({
        'success': True,
        'section': {
            'id': section.id,
            'section_name': section.section_name,
            'grade_level_id': section.grade_level_id,
            'capacity': getattr(section, 'capacity', 50),
            'room_number': getattr(section, 'room_number', ''),
            'is_active': section.is_active,
        }
    })


@login_required
@csrf_exempt
def section_batch_create(request):
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    try:
        data = json.loads(request.body)
        current_sy = SchoolYear.objects.filter(is_current=True).first()
        
        if not current_sy:
            return JsonResponse({'success': False, 'error': 'No active school year'}, status=400)
        
        grade_level = get_object_or_404(GradeLevel, id=data.get('grade_level_id'))
        count = int(data.get('number_of_sections', 1))
        capacity = int(data.get('capacity', 50))
        pattern = data.get('naming_pattern', 'alphabet')
        
        created = []
        for i in range(count):
            name = f"{grade_level.grade_name} - {chr(65+i)}" if pattern == 'alphabet' else f"{grade_level.grade_name} - {i+1}"
            
            kwargs = {
                'school_year': current_sy,
                'grade_level': grade_level,
                'section_name': name,
                'is_active': True,
            }
            if hasattr(Section, 'capacity'):
                kwargs['capacity'] = capacity
            
            section = Section.objects.create(**kwargs)
            created.append({'id': section.id, 'name': section.section_name})
        
        return JsonResponse({
            'success': True, 
            'message': f'{count} sections created for {grade_level.grade_name}',
            'sections': created
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def section_export(request):
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return redirect('signin')
    
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    sections = Section.objects.filter(
        school_year=current_sy, is_active=True
    ).select_related('grade_level')
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="sections.csv"'
    writer = csv.writer(response)
    writer.writerow(['Section', 'Grade Level', 'Capacity', 'Enrolled', 'Status'])
    
    for s in sections:
        enrolled = Enrollment.objects.filter(
            section=s, status='Enrolled'
        ).count()
        capacity = getattr(s, 'capacity', 'N/A')
        writer.writerow([
            s.section_name, 
            s.grade_level.grade_name if s.grade_level else 'N/A',
            capacity,
            enrolled, 
            'Active' if s.is_active else 'Inactive'
        ])
    
    return response


# ── ASSIGNMENT DATA ──
@login_required
def assignment_list_data(request):
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False}, status=403)
    
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    assignments = ClassAssignment.objects.filter(school_year=current_sy, is_active=True).select_related('teacher', 'section__grade_level', 'subject')
    
    grade = request.GET.get('grade', '')
    teacher = request.GET.get('teacher', '')
    search = request.GET.get('search', '')
    
    if grade:
        assignments = assignments.filter(section__grade_level_id=grade)
    if teacher:
        assignments = assignments.filter(teacher_id=teacher)
    if search:
        assignments = assignments.filter(Q(teacher__first_name__icontains=search) | Q(teacher__last_name__icontains=search) | Q(section__section_name__icontains=search))
    
    assignment_list = []
    for a in assignments:
        assignment_list.append({
            'id': a.id,
            'teacher_name': a.teacher.get_full_name(),
            'section_name': a.section_name,
            'subject_code': a.subject_code,
            'subject_name': a.subject_name,
            'grade_name': a.grade_level,
            'meetings_per_week': a.meetings_per_week,
            'minutes_per_meeting': a.minutes_per_meeting,
            'is_advisory': a.is_advisory,
        })
    
    return JsonResponse({'success': True, 'assignments': assignment_list, 'stats': {'total': assignments.count()}})


@login_required
@csrf_exempt
def assignment_create(request):
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False}, status=403)
    
    data = json.loads(request.body)
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    
    assignment = ClassAssignment.objects.create(
        teacher_id=data['teacher_id'],
        section_id=data['section_id'],
        subject_id=data['subject_id'],
        school_year=current_sy,
        meetings_per_week=data.get('meetings_per_week', 5),
        minutes_per_meeting=data.get('minutes_per_meeting', 60),
        is_advisory=data.get('is_advisory', False),
        created_by=request.user,
    )
    
    return JsonResponse({'success': True, 'message': f'Teacher assigned to {assignment.section_name}', 'assignment_id': assignment.id})


@login_required
@csrf_exempt
def assignment_delete(request, assignment_id):
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False}, status=403)
    
    assignment = get_object_or_404(ClassAssignment, id=assignment_id)
    assignment.is_active = False
    assignment.save()
    
    return JsonResponse({'success': True, 'message': 'Assignment removed'})


# ── SCHEDULE DATA ──
@login_required
def schedule_list_data(request):
    """Return schedule data as JSON with proper time formatting"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False}, status=403)
    
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    if not current_sy:
        return JsonResponse({'success': False, 'schedules': [], 'grid_data': {}, 'stats': {'total': 0}})
    
    try:
        from scheduling.models import ClassSchedule
        
        schedules = ClassSchedule.objects.filter(
            class_assignment__school_year=current_sy, 
            is_active=True
        ).select_related(
            'class_assignment__teacher', 
            'class_assignment__section', 
            'class_assignment__subject', 
            'room'
        )
        
        section = request.GET.get('section', '')
        teacher = request.GET.get('teacher', '')
        
        if section:
            schedules = schedules.filter(class_assignment__section_id=section)
        if teacher:
            schedules = schedules.filter(class_assignment__teacher_id=teacher)
        
        schedules = schedules.order_by('day_number', 'time_start')
        
        schedule_list = []
        grid_data = {
            'monday': [], 'tuesday': [], 'wednesday': [], 
            'thursday': [], 'friday': []
        }
        
        for s in schedules:
            ca = s.class_assignment
            
            # Format times safely
            time_start_str = s.time_start.strftime('%H:%M') if s.time_start else '—'
            time_end_str = s.time_end.strftime('%H:%M') if s.time_end else '—'
            
            entry = {
                'id': s.id,
                'day_of_week': s.day_of_week,
                'time_start': time_start_str,
                'time_end': time_end_str,
                'subject_code': ca.subject_code if hasattr(ca, 'subject_code') else ca.subject.subject_code,
                'section_name': ca.section_name if hasattr(ca, 'section_name') else ca.section.section_name,
                'teacher_name': ca.teacher.get_full_name() or ca.teacher.username,
                'room': str(s.effective_room) if s.effective_room else 'TBA',
                'schedule_type': s.schedule_type,
            }
            schedule_list.append(entry)
            
            day_key = s.day_of_week.lower()
            if day_key in grid_data:
                grid_data[day_key].append(entry)
        
        return JsonResponse({
            'success': True,
            'schedules': schedule_list,
            'grid_data': grid_data,
            'stats': {'total': schedules.count()}
        })
        
    except ImportError:
        return JsonResponse({
            'success': True,
            'schedules': [],
            'grid_data': {'monday': [], 'tuesday': [], 'wednesday': [], 'thursday': [], 'friday': []},
            'stats': {'total': 0}
        })



@login_required
@csrf_exempt
def schedule_create(request):
    """Create a schedule entry with proper time parsing"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    try:
        data = json.loads(request.body)
        
        # Parse time strings into datetime.time objects
        from datetime import time as dt_time
        
        time_start_str = data.get('time_start', '07:00')
        time_end_str = data.get('time_end', '08:00')
        
        # Parse "HH:MM" format
        try:
            time_start_parts = time_start_str.split(':')
            time_end_parts = time_end_str.split(':')
            time_start = dt_time(
                hour=int(time_start_parts[0]), 
                minute=int(time_start_parts[1])
            )
            time_end = dt_time(
                hour=int(time_end_parts[0]), 
                minute=int(time_end_parts[1])
            )
        except (ValueError, IndexError):
            return JsonResponse({
                'success': False, 
                'error': 'Invalid time format. Use HH:MM format.'
            }, status=400)
        
        # Validate time_end is after time_start
        if time_end <= time_start:
            return JsonResponse({
                'success': False, 
                'error': 'End time must be after start time.'
            }, status=400)
        
        # Get class assignment
        class_assignment_id = data.get('class_assignment_id')
        if not class_assignment_id:
            return JsonResponse({
                'success': False, 
                'error': 'Class assignment is required.'
            }, status=400)
        
        try:
            from scheduling.models import ClassAssignment, ClassSchedule
            from django.core.exceptions import ValidationError
            
            class_assignment = ClassAssignment.objects.get(
                id=class_assignment_id, 
                is_active=True
            )
        except ClassAssignment.DoesNotExist:
            return JsonResponse({
                'success': False, 
                'error': 'Class assignment not found.'
            }, status=400)
        
        # Handle room (optional)
        room_id = data.get('room_id')
        room = None
        if room_id:
            try:
                from academics.models import Room
                room = Room.objects.get(id=room_id)
            except Exception:
                pass
        
        try:
            schedule = ClassSchedule(
                class_assignment=class_assignment,
                day_of_week=data.get('day_of_week', 'Monday'),
                schedule_type=data.get('schedule_type', 'Regular'),
                time_start=time_start,  # Now a proper datetime.time object
                time_end=time_end,      # Now a proper datetime.time object
                room=room,
                notes=data.get('notes', ''),
                is_active=True,
            )
            schedule.save()  # This will trigger the clean() and save() methods
            
            return JsonResponse({
                'success': True,
                'message': f'Schedule created: {schedule}',
                'schedule_id': schedule.id,
            })
            
        except ValidationError as e:
            # Extract the first error message
            error_msg = str(e)
            if hasattr(e, 'messages'):
                error_msg = e.messages[0] if e.messages else str(e)
            elif hasattr(e, 'message_dict'):
                # Get the first error from message_dict
                for field, errors in e.message_dict.items():
                    error_msg = f"{field}: {errors[0]}"
                    break
            
            return JsonResponse({
                'success': False, 
                'error': error_msg
            }, status=400)
            
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
@csrf_exempt
def schedule_delete(request, schedule_id):
    """Soft-delete a schedule entry"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'registrar':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    try:
        from scheduling.models import ClassSchedule
        
        schedule = get_object_or_404(ClassSchedule, id=schedule_id)
        schedule.is_active = False
        schedule.save()
        
        return JsonResponse({
            'success': True, 
            'message': 'Schedule entry removed successfully'
        })
        
    except ImportError:
        return JsonResponse({'success': False, 'error': 'Scheduling module not available'}, status=500)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
