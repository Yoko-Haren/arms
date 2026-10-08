from django.urls import path
from . import views, views_account

urlpatterns = [
    path('signin/', views.signin, name='signin'),
    path('signout/', views.signout, name='signout'),
    # Legacy templates use this spelling. Keep it as a compatible alias.
    path('logout/', views.signout, name='logout'),

    # Google sign-in and account linking
    path('google/login/', views_account.google_login, name='google_login'),
    path('google/callback/', views_account.google_callback, name='google_callback'),
    path('google/link/', views_account.google_bind, name='google_bind'),
    path('google/verify/', views_account.google_verify, name='google_verify'),

    # Passwords
    path('password/change/', views.password_change_required, name='password_change_required'),
    path('password-reset/', views_account.password_reset_request, name='password_reset'),
    path('password-reset/verify/', views_account.password_reset_verify, name='password_reset_verify'),
    path('password-reset/new/', views_account.password_reset_new, name='password_reset_new'),
    path('password-reset/done/', views_account.password_reset_done, name='password_reset_done'),

    path('settings/', views_account.account_settings, name='account_settings'),
]
