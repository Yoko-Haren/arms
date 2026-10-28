"""Put every subject without a discipline into the one DepEd's curriculum gives it (academics/subject_catalog.py).

    python manage.py classify_subjects                    show what each unclassified subject would get
    python manage.py classify_subjects --apply            save it
    python manage.py classify_subjects --school DEMO-ARMS one school only (its school ID)
    python manage.py classify_subjects --all              also show subjects that already have a discipline,
                                                          marking those the catalog would put elsewhere (never changed)

New subjects get their discipline when they are saved; this is for the ones added before that.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from academics.models import School, Subject, SubjectFamily
from academics.subject_catalog import explain, family_for


class Command(BaseCommand):
    help = 'Give each subject without a discipline the one its name (or code) says, from the DepEd curriculum.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Save the disciplines (otherwise only show them).')
        parser.add_argument('--school', help='One school only, by its school ID.')
        parser.add_argument('--all', action='store_true', help='Also list subjects that already have a discipline.')

    def handle(self, *args, **options):
        schools = School.objects.all().order_by('school_name')
        if options['school']:
            schools = schools.filter(school_id=options['school'])
        done = unknown = 0
        with transaction.atomic():
            for school in schools:
                subjects = Subject.objects.filter(school=school).select_related('subject_family', 'grade_level').order_by(
                    'grade_level__sort_order', 'subject_code')
                if not options['all']:
                    subjects = subjects.filter(subject_family__isnull=True)
                subjects = list(subjects)
                if not subjects:
                    continue
                self.stdout.write(self.style.MIGRATE_HEADING(f'\n{school.school_name} ({school.school_id})'))
                families = list(SubjectFamily.objects.filter(school=school, is_active=True))
                for subject in subjects:
                    has = subject.subject_family
                    family, match = family_for(school, subject.subject_name, subject.subject_code,
                                               create=options['apply'] and has is None, families=families)
                    if family is not None and family not in families:
                        families.append(family)
                    label = f'  {subject.subject_code:<14} {subject.subject_name[:48]:<48}'
                    if has is not None:
                        same = family is None or family.pk == has.pk
                        self.stdout.write(f'{label} {has.family_name}' + ('' if same else f'   (the catalog says {family.family_name})'))
                        continue
                    if match is None:
                        unknown += 1
                        self.stdout.write(self.style.WARNING(f'{label} ?  {explain(None, None)}'))
                        continue
                    name = family.family_name if family is not None else f'{match.key} (a new discipline)'
                    self.stdout.write(f'{label} -> {name}   {explain(match, family)}')
                    if options['apply'] and family is not None:
                        Subject.objects.filter(pk=subject.pk).update(subject_family=family)
                        done += 1
            if not options['apply']:
                transaction.set_rollback(True)
        if options['apply']:
            self.stdout.write(self.style.SUCCESS(f'\n{done} subject{"" if done == 1 else "s"} classified.'
                                                 + (f' {unknown} need a person to choose.' if unknown else '')))
        else:
            self.stdout.write(self.style.SUCCESS('\nNothing was saved. Run again with --apply to save these disciplines.'
                                                 + (f' {unknown} need a person to choose.' if unknown else '')))
        try:
            from core.caching import bump_data_version
            if options['apply'] and done:
                bump_data_version()
        except Exception:
            pass
