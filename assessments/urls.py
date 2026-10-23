from django.urls import path

from . import views

app_name = 'assessments'

urlpatterns = [
    path('', views.assessment_list, name='list'),
    path('create/', views.assessment_create_page, name='create_page'),
    path('save/', views.assessment_save, name='save'),
    path('<int:assessment_id>/', views.assessment_detail, name='detail'),
    path('<int:assessment_id>/edit/', views.assessment_edit, name='edit'),
    path('<int:assessment_id>/action/', views.assessment_action, name='action'),
    path('<int:assessment_id>/results.xlsx', views.assessment_export, name='export'),
]
