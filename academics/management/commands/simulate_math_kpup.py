"""
Management command: Simulate Math assessment data and run KPUP classifier.
Outputs a single KPUP category result for the entire Math discipline.
"""
import sys
import time
import threading
from django.core.management.base import BaseCommand
from django.db.models import Avg, Sum, Count
from academics.models import SchoolYear, Quarter, SubjectKPUPSummary, KPUPMastery
from academics.services.kpup_service import simulate_math_assessments, classify_all_math_students


class Spinner:
    """A simple spinning loader animation."""
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
        if message:
            self.message = message
        self.running = True
        self.thread = threading.Thread(target=self.spin, daemon=True)
        self.thread.start()

    def stop(self, success=True, result_msg=""):
        self.running = False
        if self.thread:
            self.thread.join(timeout=0.3)
        sys.stdout.write('\r' + ' ' * 80 + '\r')
        sys.stdout.flush()
        if result_msg:
            tag = '[OK]' if success else '[FAIL]'
            sys.stdout.write(f'  {tag} {result_msg}\n')
            sys.stdout.flush()


class Command(BaseCommand):
    help = 'Simulate Math assessment data (Grade 1-12) and classify using KPUP'

    def handle(self, *args, **options):
        spinner = Spinner()

        # =====================================================================
        # HEADER
        # =====================================================================
        self.stdout.write('')
        self.stdout.write('=' * 70)
        self.stdout.write('  KPUP MATH DISCIPLINE CLASSIFICATION')
        self.stdout.write('  DepEd Order No. 8, s. 2015')
        self.stdout.write('=' * 70)
        self.stdout.write('')
        self.stdout.write('  Discipline      : Mathematics')
        self.stdout.write('  Grade Levels     : Grade 1 through Grade 12')
        self.stdout.write('  Classifier       : Bloom\'s Taxonomy -> KPUP Mapping')
        self.stdout.write('')

        # =====================================================================
        # STEP 1: SIMULATE
        # =====================================================================
        self.stdout.write('-' * 70)
        self.stdout.write('  STEP 1/2: Generating Assessment Data')
        self.stdout.write('  Creating 30 items per Math subject (6 cognitive levels each)')
        self.stdout.write('  Generating realistic student performance data')
        self.stdout.write('-' * 70)

        spinner.start('Simulating Math assessment data for all grade levels')

        try:
            sim_result = simulate_math_assessments()
        except Exception as e:
            spinner.stop(success=False, result_msg=str(e))
            return

        if not sim_result['success']:
            spinner.stop(success=False, result_msg=sim_result['error'])
            return

        spinner.stop(
            success=True,
            result_msg=f'{sim_result["items_created"]} items, {sim_result["results_created"]} answers across {sim_result["math_subjects"]} subjects'
        )

        # =====================================================================
        # STEP 2: CLASSIFY
        # =====================================================================
        self.stdout.write('')
        self.stdout.write('-' * 70)
        self.stdout.write('  STEP 2/2: Running KPUP Classifier')
        self.stdout.write('')
        self.stdout.write('  Bloom\'s Cognitive Level       -> KPUP Dimension')
        self.stdout.write('  -------------------------------------------------')
        self.stdout.write('  Remembering / Understanding   -> Knowledge (K)   15% weight')
        self.stdout.write('  Applying / Analyzing           -> Process (P)     25% weight')
        self.stdout.write('  Evaluating                     -> Understanding (U) 30% weight')
        self.stdout.write('  Creating                       -> Product (P)     30% weight')
        self.stdout.write('-' * 70)

        spinner.start('Classifying all Math students across all grade levels')

        try:
            classify_result = classify_all_math_students()
        except Exception as e:
            spinner.stop(success=False, result_msg=str(e))
            return

        if not classify_result['success']:
            spinner.stop(success=False, result_msg=classify_result['error'])
            return

        total = classify_result['created'] + classify_result['updated']
        spinner.stop(success=True, result_msg=f'{total} students classified')

        # =====================================================================
        # AGGREGATE ALL MATH SUBJECTS INTO ONE DISCIPLINE RESULT
        # =====================================================================
        self.stdout.write('')
        self.stdout.write('')
        self.stdout.write('=' * 70)
        self.stdout.write('  MATH DISCIPLINE - KPUP CLASSIFICATION RESULT')
        self.stdout.write('  (Grades 1-12 Aggregated)')
        self.stdout.write('=' * 70)
        self.stdout.write('')

        # Get all KPUP mastery records for Math subjects
        all_math_mastery = KPUPMastery.objects.filter(
            subject__subject_name__icontains='math'
        ) | KPUPMastery.objects.filter(
            subject__subject_code__icontains='math'
        ) | KPUPMastery.objects.filter(
            subject__subject_code__in=['CORE-GENMATH-G11', 'CORE-STATS-G11', 'SP-STEM-PRECALC', 'SP-STEM-BASCALC']
        )

        total_students = all_math_mastery.count()

        if total_students == 0:
            self.stdout.write('  No Math KPUP data found.')
            return

        # Aggregate averages
        agg = all_math_mastery.aggregate(
            avg_k=Avg('knowledge_score'),
            avg_p=Avg('process_score'),
            avg_u=Avg('understanding_score'),
            avg_prod=Avg('product_score'),
            avg_overall=Avg('overall_grade'),
        )

        avg_k = round(agg['avg_k'] or 0, 1)
        avg_p = round(agg['avg_p'] or 0, 1)
        avg_u = round(agg['avg_u'] or 0, 1)
        avg_prod = round(agg['avg_prod'] or 0, 1)
        avg_overall = round(agg['avg_overall'] or 0, 1)

        # Proficiency distribution
        advanced = all_math_mastery.filter(overall_mastery='ADVANCED').count()
        proficient = all_math_mastery.filter(overall_mastery='PROFICIENT').count()
        developing = all_math_mastery.filter(overall_mastery='DEVELOPING').count()
        beginning = all_math_mastery.filter(overall_mastery='BEGINNING').count()

        # Overall category
        if avg_overall >= 93:
            overall_category = 'ADVANCED'
        elif avg_overall >= 84:
            overall_category = 'PROFICIENT'
        elif avg_overall >= 75:
            overall_category = 'DEVELOPING'
        else:
            overall_category = 'BEGINNING'

        # =====================================================================
        # THE MAIN RESULT - Single view for the Dean
        # =====================================================================
        self.stdout.write('  +--------------------------------------------------------+')
        self.stdout.write('  |  DISCIPLINE: MATHEMATICS (Grades 1-12)                 |')
        self.stdout.write('  +--------------------------------------------------------+')
        self.stdout.write('  |                                                        |')
        self.stdout.write(f'  |  Total Students Classified: {total_students:<28} |')
        self.stdout.write('  |                                                        |')
        self.stdout.write('  |  KPUP DIMENSION BREAKDOWN:                             |')
        self.stdout.write(f'  |    Knowledge (K)       : {avg_k:>6.1f}%  (Weight: 15%)          |')
        self.stdout.write(f'  |    Process (P)         : {avg_p:>6.1f}%  (Weight: 25%)          |')
        self.stdout.write(f'  |    Understanding (U)   : {avg_u:>6.1f}%  (Weight: 30%)          |')
        self.stdout.write(f'  |    Product (P)         : {avg_prod:>6.1f}%  (Weight: 30%)          |')
        self.stdout.write('  |                                                        |')
        self.stdout.write(f'  |  OVERALL AVERAGE       : {avg_overall:>6.1f}%                         |')
        self.stdout.write(f'  |  OVERALL CATEGORY      : {overall_category:<28} |')
        self.stdout.write('  |                                                        |')
        self.stdout.write('  +--------------------------------------------------------+')
        self.stdout.write('')
        self.stdout.write('  PROFICIENCY DISTRIBUTION:')
        self.stdout.write(f'    Advanced    (93-100%): {advanced:>5} students ({round(advanced/total_students*100,1)}%)')
        self.stdout.write(f'    Proficient  (84-92%) : {proficient:>5} students ({round(proficient/total_students*100,1)}%)')
        self.stdout.write(f'    Developing  (75-83%) : {developing:>5} students ({round(developing/total_students*100,1)}%)')
        self.stdout.write(f'    Beginning   (Below 75): {beginning:>5} students ({round(beginning/total_students*100,1)}%)')
        self.stdout.write('')

        # =====================================================================
        # RECOMMENDATION FOR THE DEAN
        # =====================================================================
        self.stdout.write('=' * 70)
        self.stdout.write('  AI-GENERATED INSIGHT FOR SCHOOL HEAD')
        self.stdout.write('=' * 70)
        self.stdout.write('')

        # Find weakest and strongest dimensions
        scores = {'Knowledge (K)': avg_k, 'Process (P)': avg_p, 'Understanding (U)': avg_u, 'Product (P)': avg_prod}
        weakest = min(scores, key=scores.get)
        strongest = max(scores, key=scores.get)
        weakest_score = scores[weakest]
        strongest_score = scores[strongest]

        self.stdout.write(f'  Strongest Dimension : {strongest} ({strongest_score}%)')
        self.stdout.write(f'  Weakest Dimension   : {weakest} ({weakest_score}%)')
        self.stdout.write('')

        if overall_category == 'ADVANCED':
            self.stdout.write('  Students demonstrate mastery across all cognitive')
            self.stdout.write('  dimensions. Math instruction is highly effective.')
        elif overall_category == 'PROFICIENT':
            self.stdout.write(f'  Students perform well overall but need improvement')
            self.stdout.write(f'  in {weakest}. Consider strengthening {weakest.lower()}-based')
            self.stdout.write('  activities across all grade levels.')
        elif overall_category == 'DEVELOPING':
            self.stdout.write(f'  Students show adequate recall but struggle with')
            self.stdout.write(f'  {weakest}. Intervention needed: increase')
            self.stdout.write(f'  {weakest.lower()}-focused assessments and scaffolded')
            self.stdout.write('  activities that build higher-order thinking skills.')
        else:
            self.stdout.write(f'  CRITICAL: Students are significantly behind in')
            self.stdout.write(f'  {weakest} ({weakest_score}%). Immediate intervention')
            self.stdout.write('  required. Recommend:')
            self.stdout.write('    1. Review Math curriculum alignment')
            self.stdout.write('    2. Provide teacher training on cognitive skill development')
            self.stdout.write('    3. Implement remedial programs for struggling students')

        self.stdout.write('')

        # =====================================================================
        # PROFICIENCY SCALE REFERENCE
        # =====================================================================
        self.stdout.write('=' * 70)
        self.stdout.write('  PROFICIENCY LEVEL REFERENCE (DepEd Table 5)')
        self.stdout.write('=' * 70)
        self.stdout.write('')
        self.stdout.write('  Percentage Range    Letter Grade    Level')
        self.stdout.write('  -------------------------------------------------')
        self.stdout.write('  99% - 100%          A+              Advanced')
        self.stdout.write('  96% -  98%          A               Advanced')
        self.stdout.write('  93% -  95%          A-              Advanced')
        self.stdout.write('  90% -  92%          B+              Proficient')
        self.stdout.write('  87% -  89%          B               Proficient')
        self.stdout.write('  84% -  86%          B-              Proficient')
        self.stdout.write('  81% -  83%          C+              Developing')
        self.stdout.write('  78% -  80%          C               Developing')
        self.stdout.write('  75% -  77%          C-              Developing')
        self.stdout.write('  73% -  74%          D               Beginning')
        self.stdout.write('  65% -  72%          D-              Beginning')
        self.stdout.write('  Below 65%           F               Beginning')
        self.stdout.write('')

        # =====================================================================
        # FOOTER
        # =====================================================================
        self.stdout.write('=' * 70)
        self.stdout.write(f'  MATH DISCIPLINE CLASSIFICATION COMPLETE')
        self.stdout.write(f'  {total_students} students | Grades 1-12 | 4 KPUP Dimensions')
        self.stdout.write('=' * 70)
        self.stdout.write('')