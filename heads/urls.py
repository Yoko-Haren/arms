from django.urls import path
from django.views.generic import RedirectView

from . import views, views_users

urlpatterns = [
    # Academic Dashboard (the principal's landing page)
    path('ai-dashboard/', views.ai_academic_dashboard, name='heads-ai-dashboard'),
    path('ai-section/<int:section_id>/<int:subject_id>/<int:quarter_id>/',
         views.ai_section_detail, name='heads-ai-section-detail'),
    path('api/ai-recommendation/<int:section_id>/<int:subject_id>/<int:quarter_id>/',
         views.get_ai_section_recommendation, name='ai-section-recommendation'),
    path('ai-mark-recommendation/<int:recommendation_id>/',
         views.ai_mark_recommendation_implemented, name='heads-ai-mark-recommendation'),
    path('ai-remark/<int:enrollment_id>/<int:subject_id>/<int:quarter_id>/',
         views.get_ai_remark, name='get-ai-remark'),

    path('performance/', views.school_performance, name='heads-school-performance'),
    path('performance/<int:school_year_id>/', views.school_performance, name='heads-school-performance-sy'),

    path('kpup/', views.kpup_dashboard, name='heads-kpup-dashboard'),
    path('kpup/subject/<int:subject_id>/', views.kpup_subject_detail, name='heads-kpup-subject-detail'),

    # User Management — accounts of the principal's own school
    path('users/', views_users.user_management, name='heads-user-management'),
    path('users/data/', views_users.user_list_data, name='heads-user-list-data'),
    path('users/create/', views_users.user_create, name='heads-user-create'),
    path('users/export/', views_users.user_export, name='heads-user-export'),
    path('users/<int:user_id>/detail/', views_users.user_detail_data, name='heads-user-detail'),
    path('users/<int:user_id>/update/', views_users.user_update, name='heads-user-update'),
    path('users/<int:user_id>/toggle-status/', views_users.user_toggle_status, name='heads-user-toggle-status'),
    path('users/<int:user_id>/reset-password/', views_users.user_reset_password, name='heads-user-reset-password'),

    path('mark-notifications-read/', views.mark_notifications_read, name='heads-mark-notifications-read'),

    # School Overview and Forms Compliance were removed; old links land on the Academic Dashboard.
    path('', RedirectView.as_view(pattern_name='heads-ai-dashboard'), name='heads-dashboard'),
    path('no/', RedirectView.as_view(pattern_name='heads-ai-dashboard')),
    path('forms-compliance/', RedirectView.as_view(pattern_name='heads-ai-dashboard')),
]
