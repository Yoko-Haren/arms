from django.urls import path
from . import views

app_name = 'assessments'

urlpatterns = [
    path('', views.assessment_list, name='list'),
    path('create/', views.assessment_create_page, name='create_page'),
    path('api/create/', views.assessment_create_api, name='create_api'),
    path('<int:assessment_id>/', views.assessment_detail, name='detail'),
]