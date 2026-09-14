from django.urls import path
from . import views

urlpatterns = [
    path('no/', views.dashboard, name='heads-dashboard'),
    path('forms-compliance/', views.forms_compliance, name='heads-forms-compliance'),
    
    path('forms/approve/<int:submission_id>/', views.approve_form, name='heads-approve-form'),
    path('forms/reject/<int:submission_id>/', views.reject_form, name='heads-reject-form'),
    path('forms/approve-all/', views.approve_all_forms, name='heads-approve-all'),
    path('forms/reject-all/', views.reject_all_forms, name='heads-reject-all'),

    path('users/', views.user_management, name='heads-user-management'),
    path('users/data/', views.user_list_data, name='heads-user-list-data'),
    path('users/<int:user_id>/detail/', views.user_detail_data, name='heads-user-detail'),
    path('users/create/', views.user_create, name='heads-user-create'),
    path('users/<int:user_id>/update/', views.user_update, name='heads-user-update'),
    path('users/<int:user_id>/toggle-status/', views.user_toggle_status, name='heads-user-toggle-status'),
    path('users/<int:user_id>/reset-password/', views.user_reset_password, name='heads-user-reset-password'),
    path('users/export/', views.user_export, name='heads-user-export'),

    path('performance/', views.school_performance, name='heads-school-performance'),
    path('performance/<int:school_year_id>/', views.school_performance, name='heads-school-performance-sy'),

    # 👇 ADD THESE 6 LINES 👇
    path('evaluation/', views.dashboard, name='heads-teacher-evaluation'),
    path('reports/', views.dashboard, name='heads-reports'),
    path('announcements/', views.dashboard, name='heads-announcements'),
    path('messages/', views.dashboard, name='heads-messages'),
    path('settings/', views.dashboard, name='heads-settings'),
    path('mark-notifications-read/', views.mark_notifications_read, name='heads-mark-notifications-read'),

    # Add to your urlpatterns
    path('ai-dashboard/', views.ai_academic_dashboard, name='heads-ai-dashboard'),
    path('ai-section/<int:section_id>/<int:subject_id>/<int:quarter_id>/', 
         views.ai_section_detail, name='heads-ai-section-detail'),
    
    # 👇 ADD THIS LINE — AJAX endpoint for AI recommendation
    path('api/ai-recommendation/<int:section_id>/<int:subject_id>/<int:quarter_id>/', 
         views.get_ai_section_recommendation, name='ai-section-recommendation'),
    
    path('ai-mark-recommendation/<int:recommendation_id>/', 
         views.ai_mark_recommendation_implemented, name='heads-ai-mark-recommendation'),
    path('kpup/', views.kpup_dashboard, name='heads-kpup-dashboard'),
    path('kpup/subject/<int:subject_id>/', views.kpup_subject_detail, name='heads-kpup-subject-detail'),
    path('ai-remark/<int:enrollment_id>/<int:subject_id>/<int:quarter_id>/', 
         views.get_ai_remark, name='get-ai-remark'),
]