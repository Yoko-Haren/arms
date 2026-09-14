from django.urls import path
from . import views

app_name = 'teachers'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('class-records/', views.class_record_list, name='class_record_list'),
    path('class-records/upload/', views.upload_class_record, name='upload_class_record'),

]