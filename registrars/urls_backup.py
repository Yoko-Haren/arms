from django.urls import path
from . import views

app_name = 'registrars'

urlpatterns = [
    # Dashboard
    path('dashboard/', views.dashboard, name='dashboard'),
    
    # Student Records
    path('students/', views.student_records, name='student-records'),
    path('students/export/', views.export_masterlist, name='export-masterlist'),
    path('students/export/csv/', views.student_export_csv, name='student-export-csv'),
    path('students/batch-sf10/', views.batch_generate_sf10, name='batch-sf10'),
    path('students/batch-status/', views.batch_update_status, name='batch-update-status'),
    path('students/batch-archive/', views.batch_archive, name='batch-archive'),
    path('students/verify/<int:student_id>/', views.student_verify, name='student-verify'),
    path('students/<int:student_id>/detail-data/', views.student_detail_data, name='student-detail-data'),
    path('students/<int:student_id>/edit/', views.student_edit, name='student-edit'),
    path('students/<int:student_id>/generate-sf10/', views.student_generate_sf10, name='student-generate-sf10'),
    path('students/<int:student_id>/sf9/', views.student_sf9, name='student-sf9'),
    path('students/print-sf1/', views.print_sf1, name='print-sf1'),

    # Enrollment Management
    path('enrollment/', views.enrollment_management, name='enrollment-management'),
    path('enrollment/list-data/', views.enrollment_list_data, name='enrollment-list-data'),
    path('enrollment/create/', views.enrollment_create, name='enrollment-create'),
    path('enrollment/<int:enrollment_id>/detail-data/', views.enrollment_detail_data, name='enrollment-detail-data'),
    path('enrollment/<int:enrollment_id>/approve/', views.enrollment_approve, name='enrollment-approve'),
    path('enrollment/<int:enrollment_id>/reject/', views.enrollment_reject, name='enrollment-reject'),
    path('enrollment/<int:enrollment_id>/print/', views.enrollment_print, name='enrollment-print'),
    path('enrollment/template/', views.enrollment_template, name='enrollment-template'),
    path('enrollment/export/', views.enrollment_export, name='enrollment-export'),
    path('enrollment/batch-upload/', views.enrollment_batch_upload, name='enrollment-batch-upload'),
    
    # Grade Validation
    path('grades/', views.grade_validation, name='grade-validation'),
    path('grades/action/', views.grade_validation_action, name='grade-action'),
    path('grades/detail/<int:component_id>/', views.grade_validation_detail, name='grade-detail'),
    path('grades/export/csv/', views.grade_validation_export_csv, name='grade-export-csv'),
    path('grades/export/excel/', views.grade_validation_export_excel, name='grade-export-excel'),
    path('grades/export/pdf/', views.grade_validation_export_pdf, name='grade-export-pdf'),
    
    # School Forms
    path('forms/', views.school_forms, name='forms'),
    path('forms/process/<int:submission_id>/', views.process_submission, name='process-submission'),
    path('forms/lock/<str:form_code>/', views.toggle_form_lock, name='toggle-form-lock'),
    path('forms/generate-sf10/', views.generate_sf10, name='generate-sf10'),
    path('forms/batch-generate/', views.batch_generate, name='batch-generate'),
    path('forms/correction/<int:correction_id>/', views.process_correction, name='process-correction'),
    path('forms/document/<int:request_id>/', views.process_document_request, name='process-document'),
    path('forms/preview/<str:form_code>/', views.form_preview, name='form-preview'),
    path('forms/compliance-report/', views.forms_compliance_report, name='compliance-report'),
    path('forms/submit-correction/', views.submit_correction, name='submit-correction'),

    # Transfer Management
    path('transfer/', views.transfer_management, name='transfer-management'),
    path('transfer/list-data/', views.transfer_list_data, name='transfer-list-data'),
    path('transfer/<int:transfer_id>/detail-data/', views.transfer_detail_data, name='transfer-detail-data'),
    path('transfer/create/', views.transfer_create, name='transfer-create'),
    path('transfer/<int:transfer_id>/process/', views.transfer_process, name='transfer-process'),
    path('transfer/<int:transfer_id>/print/', views.transfer_print, name='transfer-print'),
    path('transfer/export/', views.transfer_export, name='transfer-export'),
    path('transfer/template/', views.transfer_template, name='transfer-template'),
    path('transfer/batch-upload/', views.transfer_batch_upload, name='transfer-batch-upload'),

    # Reports & Analytics
    path('reports/', views.reports_analytics, name='reports-analytics'),
    path('reports/data/', views.reports_data, name='reports-data'),
    path('reports/export/', views.reports_export, name='reports-export'),
    path('reports/pdf/', views.reports_pdf, name='reports-pdf'),
    path('reports/compliance-export/', views.reports_compliance_export, name='reports-compliance-export'),

    # Notifications
    path('notifications/mark-read/', views.mark_notifications_read, name='mark-notifications-read'),

    # ═══════════════════════════════════════════════════════════
    # Section & Schedule Management (NEW)
    # ═══════════════════════════════════════════════════════════
    path('sections-schedule/', views.section_schedule_management, name='section-schedule-management'),
    
    # Sections API
    path('sections/data/', views.section_list_data, name='section-list-data'),
    path('sections/create/', views.section_create, name='section-create'),
    path('sections/<int:section_id>/update/', views.section_update, name='section-update'),
    path('sections/<int:section_id>/toggle/', views.section_toggle, name='section-toggle'),
    path('sections/<int:section_id>/detail/', views.section_detail, name='section-detail'),
    path('sections/batch-create/', views.section_batch_create, name='section-batch-create'),
    path('sections/export/', views.section_export, name='section-export'),
    
    # Teacher Assignments API
    path('assignments/data/', views.assignment_list_data, name='assignment-list-data'),
    path('assignments/create/', views.assignment_create, name='assignment-create'),
    path('assignments/<int:assignment_id>/delete/', views.assignment_delete, name='assignment-delete'),
    
    # Class Schedules API
    path('schedules/data/', views.schedule_list_data, name='schedule-list-data'),
    path('schedules/create/', views.schedule_create, name='schedule-create'),
    path('schedules/<int:schedule_id>/delete/', views.schedule_delete, name='schedule-delete'),
]