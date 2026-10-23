"""Teacher dashboard. Class records live in views_records; assessments in the assessments app."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from core.caching import cache_page_for_user

from . import dashboard as D
from .views_records import teacher_context


@login_required
@cache_page_for_user()
def dashboard(request):
    """What needs the teacher now, how each class is doing, who may need help, and assessments."""
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'teacher':
        messages.error(request, 'Access denied. Teachers only.')
        return redirect('signin')
    if not profile.school:
        messages.error(request, 'You are not assigned to any school.')
        return redirect('signin')
    school, sy, periods, current, assignments = teacher_context(request)
    context = D.build(request.user, school, periods, current, assignments)
    context.update({'school': school, 'sy': sy, 'current': current, 'periods': periods})
    return render(request, 'teachers/dashboard.html', context)
