"""
Management command: Simulate English assessment data and run KPUP classifier.
"""
import sys
import time
import threading
from django.core.management.base import BaseCommand
from django.db.models import Avg
from academics.models import KPUPMastery
from academics.services.kpup_service import simulate_english_assessments, classify_all_english_students


class Spinner:
    def __init__(self, message="Processing"):
        self.message = message
        self.running = False
        self.spinner_chars = ['|', '/', '-', '\\']
        self.thread = None

    def spin(self):
        i = 0
        while self.running:
            sys.stdout.write(f'\r  [{self.spinner_chars[i]}] {self.message}...')
            sys.stdout.flush()
            i = (i + 1) % len(self.spinner_chars)
            time.sleep(0.15)

    def start(self, message=None):
        if message: self.message = message
        self.running = True
        self.thread = threading.Thread(target=self.spin, daemon=True)
        self.thread.start()

    def stop(self, success=True, result_msg=""):
        self.running = False
        if self.thread: self.thread.join(timeout=0.3)
        sys.stdout.write('\r' + ' ' * 80 + '\r')
        sys.stdout.flush()
        if result_msg:
            tag = '[OK]' if success else '[FAIL]'
            sys.stdout.write(f'  {tag} {result_msg}\n')
            sys.stdout.flush()


class Command(BaseCommand):
    help = 'Simulate English assessment data and classify using KPUP'

    def handle(self, *args, **options):
        spinner = Spinner()

        self.stdout.write('')
        self.stdout.write('=' * 70)
        self.stdout.write('  KPUP ENGLISH DISCIPLINE CLASSIFICATION')
        self.stdout.write('=' * 70)

        spinner.start('Simulating English assessment data')
        sim_result = simulate_english_assessments()

        if not sim_result['success']:
            spinner.stop(success=False, result_msg=sim_result['error'])
            return

        spinner.stop(success=True, result_msg=f'{sim_result["items_created"]} items, {sim_result["results_created"]} answers across {sim_result["english_subjects"]} subjects')

        spinner.start('Classifying all English students')
        classify_result = classify_all_english_students()

        if not classify_result['success']:
            spinner.stop(success=False, result_msg=classify_result['error'])
            return

        total = classify_result['created'] + classify_result['updated']
        spinner.stop(success=True, result_msg=f'{total} students classified')

        # Aggregate result
        all_eng = KPUPMastery.objects.filter(subject__subject_name__icontains='english') | KPUPMastery.objects.filter(subject__subject_code__icontains='eng')
        
        if all_eng.exists():
            agg = all_eng.aggregate(
                avg_k=Avg('knowledge_score'), avg_p=Avg('process_score'),
                avg_u=Avg('understanding_score'), avg_prod=Avg('product_score'),
                avg_overall=Avg('overall_grade'),
            )
            self.stdout.write('')
            self.stdout.write(f'  ENGLISH DISCIPLINE — {all_eng.count()} students')
            self.stdout.write(f'  K: {round(agg["avg_k"] or 0, 1)}%  P: {round(agg["avg_p"] or 0, 1)}%  U: {round(agg["avg_u"] or 0, 1)}%  Prod: {round(agg["avg_prod"] or 0, 1)}%')
            self.stdout.write(f'  Overall: {round(agg["avg_overall"] or 0, 1)}%')

        self.stdout.write('')
        self.stdout.write('  ENGLISH CLASSIFICATION COMPLETE')
        self.stdout.write('')