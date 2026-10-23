from django.urls import path
from . import views, views_forms

app_name = 'registrars'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('class-list/upload/', views.upload_class_list, name='upload_class_list'),

    path('sections/', views.section_list, name='section_list'),
    path('sections/<int:section_id>/', views.section_detail, name='section_detail'),

    path('teachers/', views.teacher_list, name='teacher_list'),
    path('teachers/create/', views.teacher_create, name='teacher_create'),
    path('teachers/import/', views.teacher_import, name='teacher_import'),
    path('teachers/email-preview/', views.teacher_email_preview, name='teacher_email_preview'),
    path('teachers/<int:profile_id>/reset-password/', views.teacher_reset_password, name='teacher_reset_password'),
    path('teachers/<int:profile_id>/toggle/', views.teacher_toggle_status, name='teacher_toggle_status'),

    path('school-forms/', views.registrar_required(views_forms.school_forms), name='school_forms'),
    path('school-forms/download/', views.registrar_required(views_forms.school_form_download), name='school_form_download'),

    path('grades/', views.grade_validation, name='grade_validation'),
    path('grades/class/<int:assignment_id>/period/<int:period_id>/', views.grade_class_detail, name='grade_class_detail'),

    path('api/updates/', views.grade_updates, name='updates'),
    path('notifications/read-all/', views.read_all_notifications, name='read_all'),
    path('notifications/<int:notification_id>/open/', views.open_notification, name='open_notification'),
]
