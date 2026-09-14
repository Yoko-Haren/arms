"""
Management command: Simulate ALL subject assessment data and run KPUP classifier.
Covers all 8 core disciplines across all grade levels.
"""
"""
Management command: Simulate ALL subject assessment data and run KPUP classifier.
"""
import sys
import time
import threading
import random
from django.core.management.base import BaseCommand
from django.db import models  # ADD THIS LINE
from django.db.models import Avg
from academics.models import (
    SchoolYear, Quarter, Subject, KPUPMastery, 
    AssessmentItem, StudentAssessmentResult, SubjectKPUPSummary
)
from enrollment.models import Enrollment
from academics.services.kpup_service import (
    BLOOMS_TO_KPUP, KPUP_WEIGHTS, get_proficiency_level,
    classify_student_kpup, populate_math_subject_summaries
)

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


# =============================================================================
# QUESTION TEMPLATES BY DISCIPLINE
# =============================================================================
DISCIPLINE_CONFIG = {
    'Mathematics': {
        'keywords': ['math', 'precalc', 'calculus', 'statistics', 'genmath', 'algebra', 'geometry', 'trigonometry'],
        'topics': {
            'jhs': ['Algebra', 'Linear Equations', 'Polynomials', 'Geometry', 'Trigonometry', 'Statistics', 'Probability', 'Quadratic Equations', 'Coordinate Geometry', 'Rational Expressions'],
            'shs': ['General Math', 'Statistics', 'Pre-Calculus', 'Basic Calculus', 'Limits', 'Derivatives', 'Integrals', 'Probability Distributions', 'Hypothesis Testing', 'Functions'],
        },
        'templates': {
            'REMEMBERING': ['What is the formula for {topic}?', 'Define {topic}.', 'State the rule of {topic}.', 'List the steps in {topic}.', 'Identify the correct definition of {topic}.'],
            'UNDERSTANDING': ['Explain why {topic} works this way.', 'Describe the concept of {topic}.', 'How does {topic} relate to real life?', 'Summarize the key idea behind {topic}.', 'Interpret this {topic} problem.'],
            'APPLYING': ['Solve this {topic} problem.', 'Apply the formula for {topic}.', 'Use {topic} to calculate the result.', 'Demonstrate how to solve {topic}.', 'Execute the procedure for {topic}.'],
            'ANALYZING': ['Compare two approaches to {topic}.', 'Analyze the error in this {topic} solution.', 'Break down this {topic} problem.', 'Differentiate between {topic} methods.', 'Examine relationships in {topic}.'],
            'EVALUATING': ['Justify which method is better for {topic}.', 'Evaluate this {topic} solution.', 'Is this {topic} answer reasonable?', 'Critique this approach to {topic}.', 'Defend your answer for {topic}.'],
            'CREATING': ['Design a real-world problem using {topic}.', 'Create a new method for {topic}.', 'Develop a guide for {topic}.', 'Construct a model demonstrating {topic}.', 'Invent a word problem using {topic}.'],
        },
    },
    'English': {
        'keywords': ['english', 'eng ', 'reading', 'writing', 'eapp', 'literature', 'grammar', 'communication'],
        'topics': {
            'jhs': ['Essay Writing', 'Literary Analysis', 'Poetry', 'Grammar', 'Research Skills', 'Public Speaking', 'Reading Comprehension', 'Vocabulary Building', 'Creative Writing', 'Debate'],
            'shs': ['Academic Writing', 'Research Paper', 'Critical Analysis', 'Argumentation', 'Literature Review', 'Professional Communication', 'Thesis Writing', 'Text Analysis', 'Media Literacy', 'Speech Writing'],
        },
        'templates': {
            'REMEMBERING': ['Define the term: {topic}.', 'List the key elements of {topic}.', 'Identify the correct definition of {topic}.', 'What are the rules of {topic}?', 'State the main components of {topic}.'],
            'UNDERSTANDING': ['Explain the concept of {topic}.', 'Summarize the main idea of {topic}.', 'Describe how {topic} is used in writing.', 'Interpret the meaning of this {topic}.', 'Paraphrase this {topic} statement.'],
            'APPLYING': ['Write a sentence using correct {topic}.', 'Apply {topic} rules to this paragraph.', 'Use {topic} to compose a response.', 'Demonstrate proper {topic} in this exercise.', 'Construct a paragraph using {topic}.'],
            'ANALYZING': ["Analyze the author's use of {topic}.", 'Compare two examples of {topic}.', 'Break down the structure of {topic}.', 'Identify patterns in this {topic}.', 'Examine how {topic} affects meaning.'],
            'EVALUATING': ['Evaluate the effectiveness of {topic}.', 'Justify why this {topic} is better.', "Critique this student's use of {topic}.", 'Assess the quality of {topic} in this essay.', 'Judge which {topic} is most effective.'],
            'CREATING': ['Write an essay demonstrating {topic}.', 'Create a story showcasing {topic}.', 'Design a presentation about {topic}.', 'Compose a poem using {topic}.', 'Develop a creative piece using {topic}.'],
        },
    },
    'Science': {
        'keywords': ['science', 'biology', 'chemistry', 'physics', 'earth', 'environmental', 'anatomy'],
        'topics': {
            'jhs': ['Scientific Method', 'Cells', 'Ecosystems', 'Force and Motion', 'Energy', 'Matter', 'Earth Science', 'Weather', 'Human Body', 'Genetics'],
            'shs': ['Molecular Biology', 'Chemical Reactions', 'Thermodynamics', 'Electromagnetism', 'Geology', 'Astronomy', 'Biotechnology', 'Organic Chemistry', 'Quantum Physics', 'Research Methods'],
        },
        'templates': {
            'REMEMBERING': ['What is {topic}?', 'Define {topic}.', 'List the parts of {topic}.', 'State the law of {topic}.', 'Identify the components of {topic}.'],
            'UNDERSTANDING': ['Explain how {topic} works.', 'Describe the process of {topic}.', 'How does {topic} affect living things?', 'Summarize the theory of {topic}.', 'Interpret this {topic} data.'],
            'APPLYING': ['Apply {topic} to this scenario.', 'Use {topic} to solve this problem.', 'Demonstrate {topic} in an experiment.', 'Execute the {topic} procedure.', 'Calculate using {topic} formula.'],
            'ANALYZING': ['Compare {topic} with related concepts.', 'Analyze the results of this {topic} experiment.', 'Break down the {topic} process.', 'Differentiate types of {topic}.', 'Examine the relationship in {topic}.'],
            'EVALUATING': ['Evaluate this {topic} hypothesis.', 'Justify the use of {topic}.', 'Critique this {topic} conclusion.', 'Assess the validity of {topic}.', 'Judge the effectiveness of {topic}.'],
            'CREATING': ['Design a {topic} experiment.', 'Create a model of {topic}.', 'Develop a theory about {topic}.', 'Construct a {topic} diagram.', 'Invent a solution using {topic}.'],
        },
    },
    'Filipino': {
        'keywords': ['filipino', 'fil ', 'wika', 'panitikan', 'komunikasyon'],
        'topics': {
            'jhs': ['Pangungusap', 'Tula', 'Maikling Kwento', 'Balarila', 'Sanaysay', 'Nobela', 'Dula', 'Talumpati', 'Pagbasa', 'Pananaliksik'],
            'shs': ['Akademikong Pagsulat', 'Pananaliksik', 'Kritikal na Pagsusuri', 'Pagsasalin', 'Diskursong Filipino', 'Panitikang Rehiyonal', 'Malikhaing Pagsulat', 'Retorika', 'Media at Wika', 'Pagsusuring Pampanitikan'],
        },
        'templates': {
            'REMEMBERING': ['Ano ang {topic}?', 'Ibigay ang kahulugan ng {topic}.', 'Isa-isahin ang elemento ng {topic}.', 'Tukuyin ang tamang kahulugan ng {topic}.', 'Ano ang tuntunin ng {topic}?'],
            'UNDERSTANDING': ['Ipaliwanag ang konsepto ng {topic}.', 'Ibuod ang pangunahing ideya ng {topic}.', 'Ilarawan kung paano gamitin ang {topic}.', 'Bigyang-kahulugan ang {topic}.', 'Ipaliwanag ang kahalagahan ng {topic}.'],
            'APPLYING': ['Sumulat gamit ang wastong {topic}.', 'Ilapat ang {topic} sa pangungusap.', 'Gamitin ang {topic} sa pagsulat.', 'Ipakita ang tamang {topic}.', 'Bumuo ng talata gamit ang {topic}.'],
            'ANALYZING': ['Suriin ang paggamit ng {topic}.', 'Ihambing ang dalawang halimbawa ng {topic}.', 'Hatiin ang istruktura ng {topic}.', 'Tukuyin ang pattern sa {topic}.', 'Siyasatin ang epekto ng {topic}.'],
            'EVALUATING': ['Suriin ang bisa ng {topic}.', 'Pangatwiranan kung bakit mas mahusay ang {topic}.', 'Pumuna sa paggamit ng {topic}.', 'Tayahin ang kalidad ng {topic}.', 'Hatulan kung aling {topic} ang pinakaepektibo.'],
            'CREATING': ['Sumulat ng orihinal na {topic}.', 'Lumikha ng kwento gamit ang {topic}.', 'Magdisenyo ng presentasyon tungkol sa {topic}.', 'Bumuo ng tula gamit ang {topic}.', 'Gumawa ng malikhaing akda gamit ang {topic}.'],
        },
    },
    'Araling Panlipunan': {
        'keywords': ['araling', 'ap ', 'panlipunan', 'kasaysayan', 'heograpiya', 'ekonomiks', 'sibika'],
        'topics': {
            'jhs': ['Kasaysayan ng Pilipinas', 'Heograpiya', 'Ekonomiks', 'Pamahalaan', 'Kultura', 'Sibika', 'Karapatang Pantao', 'Globalisasyon', 'Lipunan', 'Kabihasnan'],
            'shs': ['World History', 'Economics', 'Political Science', 'Sociology', 'Anthropology', 'International Relations', 'Development Studies', 'Public Policy', 'Governance', 'Research Methods'],
        },
        'templates': {
            'REMEMBERING': ['Ano ang {topic}?', 'Ibigay ang kahulugan ng {topic}.', 'Isa-isahin ang mga elemento ng {topic}.', 'Tukuyin ang {topic}.', 'Ano ang mga pangyayari sa {topic}?'],
            'UNDERSTANDING': ['Ipaliwanag ang {topic}.', 'Ibuod ang {topic}.', 'Ilarawan ang kahalagahan ng {topic}.', 'Paano nakaapekto ang {topic}?', 'Bigyang-kahulugan ang {topic}.'],
            'APPLYING': ['Ilapat ang {topic} sa kasalukuyan.', 'Gamitin ang kaalaman sa {topic}.', 'Ipakita ang ugnayan ng {topic}.', 'Gamitin ang {topic} sa pagsusuri.', 'Ilarawan ang aplikasyon ng {topic}.'],
            'ANALYZING': ['Suriin ang sanhi ng {topic}.', 'Ihambing ang {topic} noon at ngayon.', 'Hatiin ang mga salik ng {topic}.', 'Tukuyin ang pattern sa {topic}.', 'Siyasatin ang epekto ng {topic}.'],
            'EVALUATING': ['Suriin ang bisa ng {topic}.', 'Pangatwiranan ang {topic}.', 'Pumuna sa {topic}.', 'Tayahin ang kahalagahan ng {topic}.', 'Hatulan ang epekto ng {topic}.'],
            'CREATING': ['Bumuo ng panukala tungkol sa {topic}.', 'Lumikha ng presentasyon sa {topic}.', 'Magdisenyo ng solusyon sa {topic}.', 'Bumuo ng plano para sa {topic}.', 'Gumawa ng advocacy para sa {topic}.'],
        },
    },
    'MAPEH': {
        'keywords': ['mapeh', 'music', 'arts', 'pe ', 'health', 'physical'],
        'topics': {
            'jhs': ['Music Theory', 'Arts and Crafts', 'Physical Fitness', 'Health Education', 'Rhythm', 'Drawing', 'Sports', 'Nutrition', 'Dance', 'First Aid'],
            'shs': ['Music Composition', 'Visual Arts', 'Sports Science', 'Mental Health', 'Performance Arts', 'Digital Arts', 'Fitness Training', 'Disease Prevention', 'Choreography', 'Health Policy'],
        },
        'templates': {
            'REMEMBERING': ['What is {topic}?', 'Define {topic}.', 'List the elements of {topic}.', 'Identify {topic}.', 'State the principles of {topic}.'],
            'UNDERSTANDING': ['Explain {topic}.', 'Describe {topic}.', 'How does {topic} benefit health?', 'Summarize {topic}.', 'Interpret {topic}.'],
            'APPLYING': ['Apply {topic} technique.', 'Demonstrate {topic}.', 'Perform {topic}.', 'Execute {topic} properly.', 'Practice {topic}.'],
            'ANALYZING': ['Analyze {topic} performance.', 'Compare {topic} styles.', 'Break down {topic} elements.', 'Examine {topic} form.', 'Differentiate {topic} types.'],
            'EVALUATING': ['Evaluate {topic} quality.', 'Critique this {topic}.', 'Assess {topic} effectiveness.', 'Judge {topic} performance.', 'Rate {topic} execution.'],
            'CREATING': ['Create a {topic} piece.', 'Design a {topic} routine.', 'Compose a {topic} work.', 'Develop a {topic} program.', 'Choreograph a {topic} performance.'],
        },
    },
    'ESP': {
        'keywords': ['esp', 'edukasyon', 'values', 'ethics', 'moral', 'character'],
        'topics': {
            'jhs': ['Values Education', 'Moral Development', 'Character Building', 'Ethics', 'Responsibility', 'Respect', 'Honesty', 'Citizenship', 'Family Values', 'Decision Making'],
            'shs': ['Ethics', 'Social Responsibility', 'Leadership', 'Community Service', 'Human Dignity', 'Social Justice', 'Environmental Ethics', 'Professional Ethics', 'Peace Education', 'Values Integration'],
        },
        'templates': {
            'REMEMBERING': ['Ano ang {topic}?', 'Ibigay ang kahulugan ng {topic}.', 'Isa-isahin ang {topic}.', 'Tukuyin ang {topic}.', 'Ano ang mga halimbawa ng {topic}?'],
            'UNDERSTANDING': ['Ipaliwanag ang kahalagahan ng {topic}.', 'Ibuod ang {topic}.', 'Ilarawan ang {topic}.', 'Paano naipapakita ang {topic}?', 'Bigyang-kahulugan ang {topic}.'],
            'APPLYING': ['Ilapat ang {topic} sa pang-araw-araw.', 'Ipakita ang {topic} sa sitwasyon.', 'Gamitin ang {topic} sa pagpapasya.', 'Isabuhay ang {topic}.', 'Gawin ang {topic}.'],
            'ANALYZING': ['Suriin ang {topic} sa lipunan.', 'Ihambing ang {topic}.', 'Hatiin ang aspeto ng {topic}.', 'Siyasatin ang {topic}.', 'Tukuyin ang sanhi ng {topic}.'],
            'EVALUATING': ['Tayahin ang kahalagahan ng {topic}.', 'Pangatwiranan ang {topic}.', 'Suriin ang bisa ng {topic}.', 'Hatulan ang {topic}.', 'Pumuna sa {topic}.'],
            'CREATING': ['Bumuo ng programa para sa {topic}.', 'Lumikha ng advocacy para sa {topic}.', 'Magdisenyo ng aktibidad sa {topic}.', 'Bumuo ng plano sa {topic}.', 'Gumawa ng proyekto sa {topic}.'],
        },
    },
    'TLE': {
        'keywords': ['tle', 'technology', 'livelihood', 'ict', 'cookery', 'dressmaking', 'carpentry', 'electronics'],
        'topics': {
            'jhs': ['Basic Cooking', 'Sewing', 'Woodworking', 'Basic Electricity', 'Computer Basics', 'Gardening', 'Handicrafts', 'Food Preservation', 'Simple Repairs', 'Entrepreneurship'],
            'shs': ['Food and Beverage', 'ICT Programming', 'Automotive', 'Electrical Installation', 'Dressmaking', 'Carpentry', 'Welding', 'Business Management', 'Tourism', 'Agri-Fishery'],
        },
        'templates': {
            'REMEMBERING': ['What is {topic}?', 'Define {topic}.', 'List the tools for {topic}.', 'Identify {topic} procedures.', 'State the steps of {topic}.'],
            'UNDERSTANDING': ['Explain the process of {topic}.', 'Describe how {topic} works.', 'Why is {topic} important?', 'Summarize {topic}.', 'Interpret {topic} instructions.'],
            'APPLYING': ['Apply {topic} technique.', 'Demonstrate {topic}.', 'Perform {topic}.', 'Execute {topic} steps.', 'Use {topic} tools properly.'],
            'ANALYZING': ['Analyze {topic} results.', 'Compare {topic} methods.', 'Break down {topic} process.', 'Examine {topic} quality.', 'Differentiate {topic} techniques.'],
            'EVALUATING': ['Evaluate {topic} output.', 'Critique this {topic}.', 'Assess {topic} quality.', 'Judge {topic} effectiveness.', 'Rate {topic} performance.'],
            'CREATING': ['Create a {topic} project.', 'Design a {topic} plan.', 'Develop a {topic} product.', 'Construct a {topic} item.', 'Produce a {topic} output.'],
        },
    },
}


class Command(BaseCommand):
    help = 'Simulate ALL subject KPUP data across all disciplines'

    def handle(self, *args, **options):
        spinner = Spinner()

        # Clear ALL old data
        self.stdout.write('')
        self.stdout.write('=' * 70)
        self.stdout.write('  KPUP ALL-DISCIPLINE SIMULATION')
        self.stdout.write('=' * 70)
        self.stdout.write('')
        
        spinner.start('Clearing old data')
        KPUPMastery.objects.all().delete()
        StudentAssessmentResult.objects.all().delete()
        AssessmentItem.objects.all().delete()
        spinner.stop(success=True, result_msg='Old data cleared')

        school_year = SchoolYear.objects.filter(is_current=True).first()
        quarter = Quarter.objects.filter(school_year=school_year, is_current_quarter=True).first()
        
        if not school_year or not quarter:
            self.stdout.write('  [FAIL] No active school year or quarter')
            return

        total_items = 0
        total_results = 0
        total_classified = 0

        for discipline_name, config in DISCIPLINE_CONFIG.items():
            self.stdout.write(f'\n{"-"*50}')
            self.stdout.write(f'  {discipline_name}...')

            # Find subjects for this discipline
            subjects = Subject.objects.filter(is_active=True)
            query = None
            for kw in config['keywords']:
                q = Subject.objects.filter(is_active=True).filter(
                    models.Q(subject_name__icontains=kw) | models.Q(subject_code__icontains=kw)
                )
                if query is None:
                    query = q
                else:
                    query = query | q
            
            subjects = subjects.filter(id__in=query.values('id'))
            
            if not subjects.exists():
                self.stdout.write(f'    No {discipline_name} subjects found — skipping')
                continue

            disc_items = 0
            disc_results = 0
            disc_classified = 0

            for subject in subjects:
                grade_num = subject.grade_level.grade_number if subject.grade_level else 7
                cluster = 'jhs' if grade_num <= 10 else 'shs'
                topics = config['topics'].get(cluster, config['topics']['jhs'])
                templates = config['templates']
                assessment_items = []

                # Create 30 items (5 per cognitive level)
                for cognitive_level in ['REMEMBERING', 'UNDERSTANDING', 'APPLYING', 'ANALYZING', 'EVALUATING', 'CREATING']:
                    for i in range(5):
                        topic = random.choice(topics)
                        question_text = random.choice(templates[cognitive_level]).format(topic=topic)
                        max_score = random.choice([5, 10, 15, 20])

                        item = AssessmentItem.objects.create(
                            subject=subject,
                            question_text=question_text,
                            cognitive_level=cognitive_level,
                            max_score=max_score,
                            topic=topic,
                        )
                        assessment_items.append(item)
                        disc_items += 1

                # Get enrolled students
                enrollments = Enrollment.objects.filter(
                    school_year=school_year,
                    status__in=['Enrolled', 'Transferred_In'],
                    section__grade_level=subject.grade_level,
                ).select_related('student')

                if not enrollments.exists():
                    continue

                cognitive_difficulty = {
                    'REMEMBERING': 1.00, 
                    'UNDERSTANDING': 0.95,
                    'APPLYING': 0.90,       
                    'ANALYZING': 0.85,   
                    'EVALUATING': 0.80,    
                    'CREATING': 0.75,    
                }

                for enrollment in enrollments:
                    base_ability = random.gauss(80, 6)
                    base_ability = max(60, min(98, base_ability))

                    for item in assessment_items:
                        difficulty = cognitive_difficulty.get(item.cognitive_level, 0.80)
                        score_pct = (base_ability * difficulty) / 100
                        noise = random.uniform(-0.08, 0.08)
                        score_pct = max(0.03, min(0.99, score_pct + noise))
                        raw_score = round(score_pct * float(item.max_score), 2)

                        StudentAssessmentResult.objects.create(
                            student=enrollment.student,
                            assessment_item=item,
                            score=raw_score,
                            quarter=quarter,
                            school_year=school_year,
                        )
                        disc_results += 1

                # Classify students for this subject
                student_ids = StudentAssessmentResult.objects.filter(
                    assessment_item__subject=subject,
                    quarter=quarter, school_year=school_year
                ).values_list('student_id', flat=True).distinct()

                for student_id in student_ids:
                    from students.models import Student
                    student = Student.objects.get(id=student_id)
                    kpup_data = classify_student_kpup(student, subject, quarter, school_year)
                    
                    if not kpup_data: continue
                    
                    KPUPMastery.objects.update_or_create(
                        student=student, subject=subject, quarter=quarter, school_year=school_year,
                        defaults={
                            'knowledge_score': kpup_data['knowledge_score'],
                            'process_score': kpup_data['process_score'],
                            'understanding_score': kpup_data['understanding_score'],
                            'product_score': kpup_data['product_score'],
                            'overall_grade': kpup_data['overall_grade'],
                            'knowledge_mastery': kpup_data['knowledge_mastery'],
                            'process_mastery': kpup_data['process_mastery'],
                            'understanding_mastery': kpup_data['understanding_mastery'],
                            'product_mastery': kpup_data['product_mastery'],
                            'overall_mastery': kpup_data['overall_mastery'],
                        }
                    )
                    disc_classified += 1

            total_items += disc_items
            total_results += disc_results
            total_classified += disc_classified
            
            # Show discipline summary
            disc_masteries = KPUPMastery.objects.filter(
                subject__in=subjects, quarter=quarter, school_year=school_year
            )
            if disc_masteries.exists():
                agg = disc_masteries.aggregate(
                    avg_k=Avg('knowledge_score'), avg_p=Avg('process_score'),
                    avg_u=Avg('understanding_score'), avg_prod=Avg('product_score'),
                    avg_overall=Avg('overall_grade'),
                )
                adv = disc_masteries.filter(overall_mastery='ADVANCED').count()
                prof = disc_masteries.filter(overall_mastery='PROFICIENT').count()
                app = disc_masteries.filter(overall_mastery='APPROACHING PROFICIENCY').count()
                dev = disc_masteries.filter(overall_mastery='DEVELOPING').count()
                beg = disc_masteries.filter(overall_mastery='BEGINNING').count()
                
                self.stdout.write(f'    {disc_masteries.count()} students | '
                                  f'K:{round(agg["avg_k"] or 0,1)}% Pr:{round(agg["avg_p"] or 0,1)}% '
                                  f'U:{round(agg["avg_u"] or 0,1)}% Prod:{round(agg["avg_prod"] or 0,1)}% | '
                                  f'A:{adv} P:{prof} AP:{app} D:{dev} B:{beg}')
                                  
        # FINAL SUMMARY
        self.stdout.write(f'\n{"="*70}')
        self.stdout.write(f'  ALL DONE!')
        self.stdout.write(f'  {total_items} assessment items created')
        self.stdout.write(f'  {total_results} student answers generated')
        self.stdout.write(f'  {total_classified} students classified')
        self.stdout.write(f'{"="*70}')
        self.stdout.write('')