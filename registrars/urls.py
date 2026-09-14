from django.urls import path
from . import views

app_name = 'registrars'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('class-list/upload/', views.upload_class_list, name='upload_class_list'),
    path('sections/', views.section_list, name='section_list'),
]