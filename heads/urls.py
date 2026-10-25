from django.urls import path
from django.views.generic import RedirectView

from . import views, views_academic, views_honors, views_performance, views_proposals, views_school_year, views_users

urlpatterns = [
    # Academic Dashboard (the principal's landing page) and the section brief
    path('ai-dashboard/', views_academic.academic_dashboard, name='heads-ai-dashboard'),
    path('ai-dashboard/export/', views_academic.dashboard_export, name='heads-ai-dashboard-export'),
    path('ai-section/<int:section_id>/<int:subject_id>/<int:quarter_id>/',
         views_academic.section_brief, name='heads-ai-section-detail'),
    path('ai-section/<int:section_id>/<int:subject_id>/<int:quarter_id>/export/',
         views_academic.section_export, name='heads-ai-section-export'),
    path('api/poro/<str:token>/', views_academic.poro_narrative, name='heads-poro-narrative'),
    path('api/poro-brief/<str:token>/', views_academic.poro_brief, name='heads-poro-brief'),

    # Live updates (polled by every School Head page) and notifications
    path('api/updates/', views_academic.live_updates, name='heads-live-updates'),
    path('notifications/<int:notification_id>/open/', views_academic.open_notification, name='heads-open-notification'),
    path('ai-mark-recommendation/<int:recommendation_id>/',
         views.ai_mark_recommendation_implemented, name='heads-ai-mark-recommendation'),
    path('ai-remark/<int:enrollment_id>/<int:subject_id>/<int:quarter_id>/',
         views.get_ai_remark, name='get-ai-remark'),

    # School Performance: the whole school across learning areas and grade levels
    path('performance/', views_performance.school_performance, name='heads-school-performance'),
    path('performance/export/', views_performance.performance_export, name='heads-school-performance-export'),
    path('performance/<int:school_year_id>/', views_performance.school_performance, name='heads-school-performance-sy'),

    # User Management — accounts of the principal's own school (also open to staff the principal trusted with them)
    path('users/', views_users.user_management, name='heads-user-management'),
    path('users/data/', views_users.user_list_data, name='heads-user-list-data'),
    path('users/create/', views_users.user_create, name='heads-user-create'),
    path('users/export/', views_users.user_export, name='heads-user-export'),
    path('users/<int:user_id>/detail/', views_users.user_detail_data, name='heads-user-detail'),
    path('users/<int:user_id>/update/', views_users.user_update, name='heads-user-update'),
    path('users/<int:user_id>/toggle-status/', views_users.user_toggle_status, name='heads-user-toggle-status'),
    path('users/<int:user_id>/reset-password/', views_users.user_reset_password, name='heads-user-reset-password'),
    path('users/<int:user_id>/delegate/', views_users.user_toggle_delegate, name='heads-user-toggle-delegate'),

    # Honors Outlook: who is on track for an academic award this school year, and who is close
    path('honors/', views_honors.honors_outlook, name='heads-honors'),
    path('honors/export/', views_honors.honors_export, name='heads-honors-export'),

    # School Year: the school's own years and grading periods (the admin can still do the same)
    path('school-year/', views_school_year.school_year, name='heads-school-year'),
    path('school-year/<int:sy_id>/current/', views_school_year.school_year_make_current, name='heads-school-year-current'),
    path('school-year/<int:sy_id>/periods/', views_school_year.school_year_periods, name='heads-school-year-periods'),
    path('school-year/<int:sy_id>/delete/', views_school_year.school_year_delete, name='heads-school-year-delete'),
    path('school-year/period/<int:period_id>/', views_school_year.period_update, name='heads-period-update'),
    path('school-year/grading-rules/', views_school_year.grading_policy_update, name='heads-grading-policy'),

    # Page Proposals: pages that could come next, for discussion
    path('proposals/', views_proposals.proposals, name='heads-proposals'),

    path('mark-notifications-read/', views.mark_notifications_read, name='heads-mark-notifications-read'),

    # School Overview, Forms Compliance and the KPUP pages were removed; old links land on the Academic Dashboard.
    # (KPUP, DepEd Order No. 73, s. 2012, was replaced by DepEd Order No. 8, s. 2015.)
    path('', RedirectView.as_view(pattern_name='heads-ai-dashboard'), name='heads-dashboard'),
    path('no/', RedirectView.as_view(pattern_name='heads-ai-dashboard')),
    path('forms-compliance/', RedirectView.as_view(pattern_name='heads-ai-dashboard')),
    path('kpup/', RedirectView.as_view(pattern_name='heads-ai-dashboard')),
    path('kpup/subject/<int:subject_id>/', RedirectView.as_view(pattern_name='heads-ai-dashboard')),
]
