from django.urls import path
from django.views.generic import RedirectView

from . import views, views_academic, views_users

urlpatterns = [
    # Academic Dashboard (the principal's landing page) and the section brief
    path('ai-dashboard/', views_academic.academic_dashboard, name='heads-ai-dashboard'),
    path('ai-dashboard/export/', views_academic.dashboard_export, name='heads-ai-dashboard-export'),
    path('ai-section/<int:section_id>/<int:subject_id>/<int:quarter_id>/',
         views_academic.section_brief, name='heads-ai-section-detail'),
    path('ai-section/<int:section_id>/<int:subject_id>/<int:quarter_id>/export/',
         views_academic.section_export, name='heads-ai-section-export'),
    path('api/poro/<str:token>/', views_academic.poro_narrative, name='heads-poro-narrative'),

    # Live updates (polled by every School Head page) and notifications
    path('api/updates/', views_academic.live_updates, name='heads-live-updates'),
    path('notifications/<int:notification_id>/open/', views_academic.open_notification, name='heads-open-notification'),
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
