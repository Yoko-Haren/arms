# config/urls.py
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from assessments import views_public as quiz_views



urlpatterns = [
    path('', RedirectView.as_view(url='/accounts/signin/', permanent=False), name='home'),

    # path('django-admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('teachers/', include('teachers.urls')),
    path('registrars/', include('registrars.urls')),
    path('heads/', include('heads.urls')),
    # Keep /admin/ as a legacy URL, but give each mount a distinct namespace.
    # The primary application namespace remains admin_panel for templates and
    # reverse() calls; this removes Django's duplicate-namespace ambiguity.
    path('admin-panel/', include('admin_panel.urls', namespace='admin_panel')),
    path('admin/', include('admin_panel.urls', namespace='legacy_admin_panel')),
    path('assessments/', include('assessments.urls')),
    path('quiz/<str:access_code>/', quiz_views.quiz_login, name='quiz_login'),
    path('quiz/<str:access_code>/take/', quiz_views.take_quiz, name='take_quiz'),
    path('quiz/<str:access_code>/submit/', quiz_views.submit_quiz, name='submit_quiz'),
]   
