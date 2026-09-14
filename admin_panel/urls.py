from django.urls import path
from . import views

app_name = 'admin_panel'

urlpatterns = [
    # Auth
    path('login/', views.admin_login, name='login'),
    path('logout/', views.admin_logout, name='logout'),
    
    # Dashboard
    path('', views.dashboard, name='dashboard'),
    
    # Schools
    path('schools/', views.school_list, name='school_list'),
    path('schools/create/', views.school_create, name='school_create'),
    path('schools/<int:school_id>/', views.school_detail, name='school_detail'),
    path('schools/<int:school_id>/edit/', views.school_edit, name='school_edit'),
    path('schools/<int:school_id>/toggle/', views.school_toggle_status, name='school_toggle'),
    path('schools/<int:school_id>/delete/', views.school_delete, name='school_delete'),
    
    # Principals
    path('principals/', views.principal_list, name='principal_list'),
    path('principals/create/', views.principal_create, name='principal_create'),
    path('principals/<int:principal_id>/', views.principal_detail, name='principal_detail'),
    path('principals/<int:principal_id>/edit/', views.principal_edit, name='principal_edit'),
    path('principals/<int:principal_id>/toggle/', views.principal_toggle_status, name='principal_toggle'),
    path('principals/<int:principal_id>/reset-password/', views.principal_reset_password, name='principal_reset_password'),
    
    # Grade Levels
    path('grade-levels/', views.grade_level_list, name='grade_level_list'),
    path('grade-levels/create/', views.grade_level_create, name='grade_level_create'),
    
    # School Years
    path('school-years/', views.school_year_manage, name='school_year_manage'),
    path('school-years/<int:sy_id>/set-current/', views.school_year_set_current, name='school_year_set_current'),
    path('school-years/<int:sy_id>/delete/', views.school_year_delete, name='school_year_delete'),
    
    # Quarters
    path('quarters/', views.quarter_manage, name='quarter_manage'),
    path('quarters/<int:sy_id>/bulk-create/', views.quarter_bulk_create, name='quarter_bulk_create'),
    path('quarters/<int:quarter_id>/delete/', views.quarter_delete, name='quarter_delete'),
    
    # AJAX
    path('api/school/<int:school_id>/', views.get_school_details, name='get_school_details'),
    path('api/school/<int:school_id>/grade-levels/', views.get_grade_levels_for_school, name='get_grade_levels'),
    path('api/school/<int:school_id>/school-years/', views.get_school_years_for_school, name='get_school_years'),
    path('api/check-school-id/', views.check_school_id, name='check_school_id'),
    path('api/check-username/', views.check_username, name='check_username'),
]