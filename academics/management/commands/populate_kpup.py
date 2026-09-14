"""
Management command to populate KPUPMastery and SubjectKPUPSummary
from existing GradeComponent data.
"""
from django.core.management.base import BaseCommand
from academics.models import SchoolYear, Quarter
from academics.services.kpup_service import populate_kpup_mastery


class Command(BaseCommand):
    help = 'Populate KPUP Mastery data from existing grades'

    def add_arguments(self, parser):
        parser.add_argument(
            '--school-year',
            type=str,
            help='School year label (e.g., "2025-2026"). Uses current if not specified.',
        )
        parser.add_argument(
            '--quarter',
            type=str,
            help='Quarter label (e.g., "Q1", "Q2", "Q3", "Q4"). Uses current if not specified.',
        )

    def handle(self, *args, **options):
        school_year = None
        quarter = None
        
        if options['school_year']:
            school_year = SchoolYear.objects.filter(year_label=options['school_year']).first()
            if not school_year:
                self.stderr.write(self.style.ERROR(f'School year "{options["school_year"]}" not found.'))
                return
        
        if options['quarter']:
            if not school_year:
                school_year = SchoolYear.objects.filter(is_current=True).first()
            if school_year:
                quarter = Quarter.objects.filter(
                    school_year=school_year,
                    quarter_label=options['quarter']
                ).first()
            if not quarter:
                self.stderr.write(self.style.ERROR(f'Quarter "{options["quarter"]}" not found.'))
                return
        
        self.stdout.write(self.style.WARNING('Populating KPUP Mastery data...'))
        
        result = populate_kpup_mastery(school_year, quarter)
        
        if result['success']:
            self.stdout.write(self.style.SUCCESS(
                f'Done! Created: {result["created"]}, Updated: {result["updated"]}'
            ))
        else:
            self.stderr.write(self.style.ERROR(f'Error: {result["error"]}'))