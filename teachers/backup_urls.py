from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.dashboard, name='teachers-dashboard'),
    path('classes/', views.class_list, name='teachers-classes'),
    path('attendance/', views.attendance, name='teachers-attendance'),
    path('forms/', views.school_forms, name='teachers-forms'),
    path('forms/certify/', views.certify_form, name='teachers-certify-form'),
    path('forms/submit-correction/', views.submit_correction, name='teachers-submit-correction'),
    path('api/sf9-grades/', views.sf9_grades_api, name='teachers-sf9-grades'),
    path('reports/', views.reports, name='teachers-reports'),

    
    # Grade Encoding - Use ONE consistent URL structure
    path('grade-encoding/', views.grade_encoding, name='teachers-grades'),
    path('grade-encoding/save-cell/', views.save_grade_cell, name='teachers-save-grade-cell'),
    path('grade-encoding/parse-excel/', views.parse_excel_preview, name='teachers-parse-excel'),
    path('grade-encoding/import-excel/', views.import_excel_grades, name='teachers-import-excel'),
    path('grade-encoding/export-excel/', views.export_excel_template, name='teachers-export-excel'),
    path('reports/', views.reports, name='teachers-reports'),

    # Attendance URLs
    path('attendance/', views.attendance, name='teachers-attendance'),
    path('attendance/export/', views.export_attendance_summary, name='attendance-export'),
    path('attendance/mark/', views.mark_attendance_ajax, name='attendance-mark-ajax'),
    path('attendance/stats/', views.attendance_stats_api, name='attendance-stats-api'),
    path('attendance/import/', views.import_attendance_excel, name='attendance-import'),

    path('schedule/', views.teacher_schedule, name='teachers-schedule'),
    path('schedule/export/', views.export_schedule_pdf, name='schedule-export'),
    
    # 
]