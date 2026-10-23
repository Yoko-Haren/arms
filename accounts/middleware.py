from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class ForcePasswordChangeMiddleware:
    """Account set-up gates for signed-in users, in order:

    1. a temporary password must be replaced;
    2. a Google account must be linked and confirmed (when Google sign-in is required).

    Public pages stay open: the landing page, and the contact form, so someone stuck at a gate
    can still message the ARMS administrator.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        public = request.path.startswith('/static/') or request.path in (reverse('home'), reverse('contact_submit'), '/favicon.ico')
        if user is not None and user.is_authenticated and not public:
            profile = getattr(user, 'profile', None)
            if profile is not None:
                leaving = (reverse('signout'), reverse('logout'))
                if profile.must_change_password:
                    if request.path not in leaving + (reverse('password_change_required'),):
                        return redirect('password_change_required')
                elif settings.GOOGLE_BINDING_REQUIRED and not profile.google_sub:
                    linking = (
                        reverse('google_bind'), reverse('google_login'),
                        reverse('google_callback'), reverse('google_verify'),
                    )
                    if request.path not in leaving + linking:
                        return redirect('google_bind')
        return self.get_response(request)
