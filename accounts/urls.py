from django.urls import path
from . import views

urlpatterns = [
    path('signin/', views.signin, name='signin'),
    path('signout/', views.signout, name='signout'),
    # Legacy templates use this spelling. Keep it as a compatible alias.
    path('logout/', views.signout, name='logout'),
    path('password-reset/', views.password_reset_request, name='password_reset'),
    path('password-reset/done/', views.password_reset_done, name='password_reset_done'),
]
