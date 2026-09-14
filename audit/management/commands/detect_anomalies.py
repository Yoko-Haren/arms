"""
Management command to run Poro AI anomaly detection.
Usage: python manage.py detect_anomalies
"""

from django.core.management.base import BaseCommand
from audit.detector import PoroDetector


class Command(BaseCommand):
    help = 'Run Poro AI anomaly detection engine on all data'

    def handle(self, *args, **options):
        self.stdout.write('Poro AI v1.0.0 — Starting anomaly detection...')
        count = PoroDetector.run_all_checks()
        if count > 0:
            self.stdout.write(self.style.WARNING(f'Detected {count} new anomal{"y" if count == 1 else "ies"}!'))
        else:
            self.stdout.write(self.style.SUCCESS('No new anomalies detected. System is clean.'))