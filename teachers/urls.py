from django.urls import path
from . import views, views_advisory, views_records

app_name = 'teachers'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),

    # Class records: progress per grading period, uploads (check first, then save), submission
    path('class-records/', views_records.class_records, name='class_record_list'),
    path('class-records/upload/', views_records.upload, name='upload_class_record'),
    path('class-records/upload/review/', views_records.upload_review, name='upload_review'),
    path('class-records/<int:assignment_id>/period/<int:period_id>/submit/', views_records.submit_class, name='submit_class'),
    path('class-records/<int:assignment_id>/e-class-record/', views_records.class_ecr, name='class_ecr'),
    path('class-records/<int:assignment_id>/class-list.csv', views_records.class_csv, name='class_csv'),
    path('class-records/<int:assignment_id>/mapeh-final-grades/', views_records.class_mapeh_final, name='class_mapeh_final'),
    path('advisory/<int:section_id>/school-form/', views_records.advisory_form, name='advisory_form'),

    # My Advisory: every subject's grades for the section the teacher advises, and each learner's record
    path('advisory/', views_advisory.advisory, name='advisory'),

    # Notification bell
    path('api/updates/', views_records.updates, name='updates'),
    path('notifications/read-all/', views_records.read_all, name='read_all'),
    path('notifications/<int:notification_id>/open/', views_records.open_notification, name='open_notification'),
]
