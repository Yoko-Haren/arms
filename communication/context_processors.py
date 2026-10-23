"""Template values: the ready-made email links, and on admin pages the number of new requests."""
from django.utils.functional import SimpleLazyObject

from . import compose


def _new_request_count():
    from .models import ContactRequest
    return ContactRequest.objects.filter(status=ContactRequest.STATUS_NEW).count()


def contact(request):
    values = {'contact_links': compose.links()}
    if request.path.startswith(('/admin-panel/', '/admin/')):
        values['new_contact_requests'] = SimpleLazyObject(_new_request_count)   # counted only if a page shows it
    return values
