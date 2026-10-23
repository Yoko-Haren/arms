"""Enrolling a section from its SF1 (School Register): upload, review every learner, confirm.

The registrar uploads the SF1 that LIS exports for a section (Junior or Senior High). ARMS reads
it (enrollment.sf1), shows what the import would do (enrollment.sf1_import.preview) and saves
nothing until the registrar confirms. The parsed file waits in the cache for 30 minutes.
"""
import secrets

from django.contrib import messages
from django.core.cache import caches
from django.shortcuts import redirect, render

from academics.models import Section
from enrollment import sf1, sf1_import

REVIEW_SECONDS = 30 * 60


def _key(user, token):
    return f'sf1:{user.pk}:{token}'


def _adviser_options(school, sy, teacher_options):
    """Teachers for the adviser list, each with the class they already advise this year."""
    advising = {s.adviser_id: f'{s.grade_level.grade_name} {s.section_name}' for s in Section.objects.filter(
        school=school, school_year=sy, adviser__isnull=False).select_related('grade_level')}
    return [dict(t, advises=advising.get(t['user_id'])) for t in teacher_options]


def sf1_post(request, school, sy, *, teacher_options, teacher_user):
    """Both steps: a new SF1 upload (review) or the confirmation of a reviewed one (import)."""
    if request.POST.get('action') == 'confirm_sf1':
        token = request.POST.get('token', '')
        parsed = caches['default'].get(_key(request.user, token)) if token else None
        if not parsed:
            messages.error(request, 'The review expired before it was confirmed. Upload the SF1 again.')
            return redirect('registrars:upload_class_list')
        adviser = teacher_user(school, request.POST.get('adviser', ''))
        try:
            done = sf1_import.apply(parsed, school, sy, request.user,
                                    move_elsewhere=request.POST.get('move_elsewhere') == '1', adviser=adviser)
        except sf1.SF1Error as exc:
            messages.error(request, str(exc))
            return redirect('registrars:upload_class_list')
        caches['default'].delete(_key(request.user, token))
        section = done['section']
        label = f'{section.grade_level.grade_name} {section.section_name}'
        parts = [f'{done["enrolled"]} learner{"s" if done["enrolled"] != 1 else ""} enrolled']
        if done['updated']:
            parts.append(f'{done["updated"]} already in the section updated')
        if done['moved']:
            parts.append(f'{done["moved"]} moved here from another section')
        if done['left_elsewhere']:
            parts.append(f'{done["left_elsewhere"]} left in their current section')
        if done['skipped']:
            parts.append(f'{done["skipped"]} row{"s" if done["skipped"] != 1 else ""} skipped')
        messages.success(request, f'{label} {"created" if done["section_created"] else "updated"} from the SF1: '
                                  + ', '.join(parts) + '.')
        if adviser:
            messages.info(request, f'{adviser.get_full_name() or adviser.username} is the adviser of {label}.')
        _log(request, section, f'SF1 import: {label} ({done["enrolled"]} enrolled, {done["updated"]} updated, {done["moved"]} moved)')
        return redirect('registrars:section_detail', section_id=section.id)

    upload = request.FILES.get('sf1_file')
    try:
        parsed = sf1.read(upload)
    except sf1.SF1Error as exc:
        messages.error(request, str(exc))
        return redirect('registrars:upload_class_list')
    plan = sf1_import.preview(parsed, school, sy)
    token = secrets.token_urlsafe(16)
    caches['default'].set(_key(request.user, token), parsed, REVIEW_SECONDS)
    return render(request, 'registrars/class_list/sf1_preview.html', {
        'current_sy': sy, 'school': school, 'plan': plan, 'token': token, 'file_name': upload.name,
        'adviser_options': _adviser_options(school, sy, teacher_options),
        'current_adviser_id': plan['section'].adviser_id if plan['section'] else None,
        'problems': plan['counts']['invalid'] + plan['counts']['duplicate'],
    })


def _log(request, section, description):
    try:
        from audit.models import ActivityLog
        ActivityLog.objects.create(
            user=request.user, user_name=request.user.get_full_name() or request.user.username, user_role='registrar',
            action_type='IMPORT', resource_type='Section', resource_id=str(section.id),
            details_json={'description': description},
            ip_address=request.META.get('REMOTE_ADDR', '127.0.0.1'), user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
        )
    except Exception:
        pass
