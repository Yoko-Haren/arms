"""Region, division and district of a school: the header every DepEd school form carries.

ARMS keeps them per school in the DepEd configuration store (one JSON entry per school, visible to
the administrator). They are learned from the SF1 the registrar imports and can be corrected on
the School Forms page. A value is only replaced by a non-empty one.
"""
import json
import re

KEY = 'SCHOOL_FORM_HEADER:{}'
FIELDS = ('region', 'division', 'district')
_NAMED_REGIONS = ('NCR', 'CAR', 'CARAGA', 'BARMM', 'MIMAROPA', 'NIR')


def get(school):
    """{'region': 'XI', 'division': 'Panabo City', 'district': '...'} ('' when not known)."""
    from configuration.models import DepEdConfiguration
    row = DepEdConfiguration.objects.filter(config_key=KEY.format(school.school_id)).first()
    try:
        stored = json.loads(row.config_value) if row else {}
    except ValueError:
        stored = {}
    return {f: str(stored.get(f) or '') for f in FIELDS}


def remember(school, values, user=None):
    """Keep the non-empty region / division / district of values; returns what is stored."""
    from configuration.models import DepEdConfiguration
    current = get(school)
    new = dict(current)
    for f in FIELDS:
        value = re.sub(r'\s+', ' ', str(values.get(f) or '')).strip()
        if f == 'region':
            value = region_code(value)
        if value:
            new[f] = value[:100]
    if new != current:
        DepEdConfiguration.objects.update_or_create(
            config_key=KEY.format(school.school_id),
            defaults={'config_value': json.dumps(new), 'config_type': 'JSON', 'category': 'Division_Office',
                      'description': f'Region, division and district printed on the school forms of {school.school_name}.',
                      'updated_by': user if user is not None and user.is_authenticated else None})
    return new


def save(school, values, user=None):
    """Set region, division and district as given (the School Forms page): an empty field clears it."""
    from configuration.models import DepEdConfiguration
    new = {f: re.sub(r'\s+', ' ', str(values.get(f) or '')).strip()[:100] for f in FIELDS}
    new['region'] = region_code(new['region'])
    DepEdConfiguration.objects.update_or_create(
        config_key=KEY.format(school.school_id),
        defaults={'config_value': json.dumps(new), 'config_type': 'JSON', 'category': 'Division_Office',
                  'description': f'Region, division and district printed on the school forms of {school.school_name}.',
                  'updated_by': user if user is not None and user.is_authenticated else None})
    return new


def region_code(text):
    """'Region XI', 'REGION 11', 'XI' -> 'XI'; 'NCR' stays; '' when empty."""
    t = re.sub(r'\s+', ' ', (text or '').strip()).upper()
    t = re.sub(r'^REGION\s*', '', t).strip(' -:')
    t = re.sub(r'\s*\(.*\)$', '', t)                       # "XI (DAVAO REGION)"
    return t


def region_label(code):
    """How the forms write a region: 'Region XI', 'Region IV-A', 'NCR'."""
    c = region_code(code)
    if not c:
        return ''
    if c in _NAMED_REGIONS or not re.fullmatch(r'[IVX]+(-[AB])?|\d{1,2}(-[AB])?', c):
        return c
    return f'Region {c}'
