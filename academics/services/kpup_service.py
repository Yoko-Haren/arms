"""
KPUP Classification Service - The Data Mining Classifier
Maps assessment items tagged with Bloom's cognitive level → DepEd KPUP dimensions,
then classifies students into proficiency levels.
"""

from django.db.models import Avg, Count, Q
from academics.models import (
    Subject, Quarter, SchoolYear, Section,
    KPUPMastery, SubjectKPUPSummary, AssessmentItem, StudentAssessmentResult
)
from enrollment.models import Enrollment
import random


# =============================================================================
# BLOOM'S → KPUP MAPPING (The Classifier)
# =============================================================================
BLOOMS_TO_KPUP = {
    'REMEMBERING': 'knowledge',
    'UNDERSTANDING': 'knowledge',
    'APPLYING': 'process',
    'ANALYZING': 'process',
    'EVALUATING': 'understanding',
    'CREATING': 'product',
}

KPUP_WEIGHTS = {
    'knowledge': 0.15,
    'process': 0.25,
    'understanding': 0.30,
    'product': 0.30,
}


# =============================================================================
# PROFICIENCY LEVEL CLASSIFICATION (DepEd Table 5)
# =============================================================================
def get_proficiency_level(score):
    """Classify score using DepEd Order No. 31, s. 2012"""
    if score >= 90:
        return 'ADVANCED', 'A'
    elif score >= 85:
        return 'PROFICIENT', 'P'
    elif score >= 80:
        return 'APPROACHING PROFICIENCY', 'AP'
    elif score >= 75:
        return 'DEVELOPING', 'D'
    else:
        return 'BEGINNING', 'B'

def get_proficiency_label(level, letter):
    return f"{level} ({letter})"


# =============================================================================
# CLASSIFY SINGLE STUDENT
# =============================================================================
def classify_student_kpup(student, subject, quarter, school_year):
    """
    THE CLASSIFIER:
    Reads all assessment results for a student, maps each item's cognitive level
    to KPUP dimension, calculates weighted scores, and assigns proficiency level.
    """
    results = StudentAssessmentResult.objects.filter(
        student=student,
        assessment_item__subject=subject,
        quarter=quarter,
        school_year=school_year
    ).select_related('assessment_item')
    
    if not results.exists():
        return None
    
    # Group scores by KPUP dimension
    kpup_scores = {
        'knowledge': {'total': 0, 'max': 0},
        'process': {'total': 0, 'max': 0},
        'understanding': {'total': 0, 'max': 0},
        'product': {'total': 0, 'max': 0},
    }
    
    for result in results:
        cognitive_level = result.assessment_item.cognitive_level
        kpup_dim = BLOOMS_TO_KPUP.get(cognitive_level, 'knowledge')
        
        kpup_scores[kpup_dim]['total'] += float(result.score)
        kpup_scores[kpup_dim]['max'] += float(result.assessment_item.max_score)
    
    # Calculate percentages per dimension
    k_percent = (kpup_scores['knowledge']['total'] / kpup_scores['knowledge']['max'] * 100) if kpup_scores['knowledge']['max'] > 0 else 0
    p_percent = (kpup_scores['process']['total'] / kpup_scores['process']['max'] * 100) if kpup_scores['process']['max'] > 0 else 0
    u_percent = (kpup_scores['understanding']['total'] / kpup_scores['understanding']['max'] * 100) if kpup_scores['understanding']['max'] > 0 else 0
    prod_percent = (kpup_scores['product']['total'] / kpup_scores['product']['max'] * 100) if kpup_scores['product']['max'] > 0 else 0
    
    # Overall weighted grade
    overall = (
        k_percent * KPUP_WEIGHTS['knowledge'] +
        p_percent * KPUP_WEIGHTS['process'] +
        u_percent * KPUP_WEIGHTS['understanding'] +
        prod_percent * KPUP_WEIGHTS['product']
    )
    
    # Classify each dimension
    k_level, k_letter = get_proficiency_level(k_percent)
    p_level, p_letter = get_proficiency_level(p_percent)
    u_level, u_letter = get_proficiency_level(u_percent)
    prod_level, prod_letter = get_proficiency_level(prod_percent)
    overall_level, overall_letter = get_proficiency_level(overall)
    
    return {
        'knowledge_score': round(k_percent, 2),
        'process_score': round(p_percent, 2),
        'understanding_score': round(u_percent, 2),
        'product_score': round(prod_percent, 2),
        'overall_grade': round(overall, 2),
        'knowledge_mastery': k_level,
        'knowledge_letter': k_letter,
        'process_mastery': p_level,
        'process_letter': p_letter,
        'understanding_mastery': u_level,
        'understanding_letter': u_letter,
        'product_mastery': prod_level,
        'product_letter': prod_letter,
        'overall_mastery': overall_level,
        'overall_letter': overall_letter,
        'items_count': results.count(),
    }


# =============================================================================
# SIMULATE MATH ASSESSMENT DATA (Grade 1-12)
# =============================================================================
def simulate_math_assessments(school_year=None, quarter=None):
    """Creates realistic Math assessment items and student results for all grade levels."""
    # Clear old data first
    KPUPMastery.objects.all().delete()
    StudentAssessmentResult.objects.all().delete()
    AssessmentItem.objects.all().delete()
    
    if not school_year:
        school_year = SchoolYear.objects.filter(is_current=True).first()
    if not quarter:
        quarter = Quarter.objects.filter(school_year=school_year, is_current_quarter=True).first()
    
    if not school_year or not quarter:
        return {'success': False, 'error': 'No active school year or quarter found'}
    
    # Find Math subjects
    math_subjects = Subject.objects.filter(
        is_active=True,
        subject_name__icontains='math'
    ) | Subject.objects.filter(
        is_active=True,
        subject_code__icontains='math'
    ) | Subject.objects.filter(
        is_active=True,
        subject_code__in=['CORE-GENMATH-G11', 'CORE-STATS-G11', 'SP-STEM-PRECALC', 'SP-STEM-BASCALC']
    )
    
    if not math_subjects.exists():
        return {'success': False, 'error': 'No Math subjects found. Seed subjects first.'}
    
    # Clear existing math assessment data for this quarter
    AssessmentItem.objects.filter(subject__in=math_subjects).delete()
    
    math_topics = {
        'elementary': ['Addition', 'Subtraction', 'Multiplication', 'Division', 'Fractions', 'Decimals', 'Geometry Basics', 'Measurement', 'Word Problems', 'Number Sense'],
        'jhs': ['Algebra', 'Linear Equations', 'Polynomials', 'Geometry', 'Trigonometry', 'Statistics', 'Probability', 'Quadratic Equations', 'Coordinate Geometry', 'Rational Expressions'],
        'shs': ['General Math', 'Statistics', 'Pre-Calculus', 'Basic Calculus', 'Limits', 'Derivatives', 'Integrals', 'Probability Distributions', 'Hypothesis Testing', 'Functions'],
    }
    
    items_created = 0
    results_created = 0
    
    for subject in math_subjects:
        grade_num = subject.grade_level.grade_number if subject.grade_level else 7
        if grade_num <= 6:
            cluster = 'elementary'
        elif grade_num <= 10:
            cluster = 'jhs'
        else:
            cluster = 'shs'
        
        topics = math_topics[cluster]
        assessment_items = []
        
        item_distribution = [
            ('REMEMBERING', 5),
            ('UNDERSTANDING', 5),
            ('APPLYING', 5),
            ('ANALYZING', 5),
            ('EVALUATING', 5),
            ('CREATING', 5),
        ]
        
        for cognitive_level, count in item_distribution:
            for i in range(count):
                topic = random.choice(topics)
                
                templates = {
                    'REMEMBERING': [
                        f"What is the formula for {topic}?",
                        f"Define {topic}.",
                        f"State the rule of {topic}.",
                        f"List the steps in {topic}.",
                        f"Identify the correct definition of {topic}.",
                    ],
                    'UNDERSTANDING': [
                        f"Explain why {topic} works this way.",
                        f"Describe the concept of {topic} in your own words.",
                        f"How does {topic} relate to real life?",
                        f"Summarize the key idea behind {topic}.",
                        f"Interpret this {topic} problem.",
                    ],
                    'APPLYING': [
                        f"Solve this {topic} problem.",
                        f"Apply the formula to find the answer for {topic}.",
                        f"Use {topic} to calculate the result.",
                        f"Demonstrate how to solve {topic} step by step.",
                        f"Execute the procedure for {topic}.",
                    ],
                    'ANALYZING': [
                        f"Compare these two approaches to {topic}.",
                        f"Analyze the error in this {topic} solution.",
                        f"Break down this {topic} problem into parts.",
                        f"Differentiate between correct and incorrect {topic} methods.",
                        f"Examine the relationship between {topic} concepts.",
                    ],
                    'EVALUATING': [
                        f"Justify which method is better for {topic}.",
                        f"Evaluate the solution to this {topic} problem.",
                        f"Is this {topic} answer reasonable? Explain why.",
                        f"Critique this approach to solving {topic}.",
                        f"Defend your answer for this {topic} problem.",
                    ],
                    'CREATING': [
                        f"Design a real-world problem using {topic}.",
                        f"Create a new method to explain {topic}.",
                        f"Develop a step-by-step guide for {topic}.",
                        f"Construct a model that demonstrates {topic}.",
                        f"Invent a word problem that uses {topic}.",
                    ],
                }
                
                question_text = random.choice(templates[cognitive_level])
                max_score = random.choice([5, 10, 15, 20])
                
                item = AssessmentItem.objects.create(
                    subject=subject,
                    question_text=question_text,
                    cognitive_level=cognitive_level,
                    max_score=max_score,
                    topic=topic,
                )
                assessment_items.append(item)
                items_created += 1
        
        # Get students enrolled in this subject's sections
        enrollments = Enrollment.objects.filter(
            school_year=school_year,
            status__in=['Enrolled', 'Transferred_In'],
            section__grade_level=subject.grade_level,
        ).select_related('student', 'section')
        
        for enrollment in enrollments:
            # Base ability: normal distribution centered at 88
            base_ability = random.gauss(80, 6)
            base_ability = max(60, min(98, base_ability))            
            
            # COGNITIVE DECLINE FACTOR
            cognitive_difficulty = {
                'REMEMBERING':   1.00,
                'UNDERSTANDING': 0.95,
                'APPLYING':      0.90,
                'ANALYZING':     0.85,
                'EVALUATING':    0.80,
                'CREATING':      0.75,
            }
                        
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
                results_created += 1
    
    return {
        'success': True,
        'items_created': items_created,
        'results_created': results_created,
        'math_subjects': math_subjects.count(),
    }


# =============================================================================
# RUN THE CLASSIFIER ON MATH DATA
# =============================================================================
def classify_all_math_students(school_year=None, quarter=None):
    """Classify all Math students using KPUP"""
    if not school_year:
        school_year = SchoolYear.objects.filter(is_current=True).first()
    if not quarter:
        quarter = Quarter.objects.filter(school_year=school_year, is_current_quarter=True).first()
    
    if not school_year or not quarter:
        return {'success': False, 'error': 'No active school year or quarter found'}
    
    # Find Math subjects
    math_subjects = Subject.objects.filter(
        is_active=True,
        subject_name__icontains='math'
    ) | Subject.objects.filter(
        is_active=True,
        subject_code__icontains='math'
    ) | Subject.objects.filter(
        is_active=True,
        subject_code__in=['CORE-GENMATH-G11', 'CORE-STATS-G11', 'SP-STEM-PRECALC', 'SP-STEM-BASCALC']
    )
    
    if not math_subjects.exists():
        return {'success': False, 'error': 'No Math subjects found'}
    
    created = 0
    updated = 0
    
    for subject in math_subjects:
        student_ids = StudentAssessmentResult.objects.filter(
            assessment_item__subject=subject,
            quarter=quarter,
            school_year=school_year
        ).values_list('student_id', flat=True).distinct()
        
        for student_id in student_ids:
            from students.models import Student
            student = Student.objects.get(id=student_id)
            
            kpup_data = classify_student_kpup(student, subject, quarter, school_year)
            
            if not kpup_data:
                continue
            
            mastery, was_created = KPUPMastery.objects.update_or_create(
                student=student,
                subject=subject,
                quarter=quarter,
                school_year=school_year,
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
            
            if was_created:
                created += 1
            else:
                updated += 1
    
    # Aggregate subject summaries
    populate_math_subject_summaries(school_year, quarter)
    
    return {
        'success': True,
        'created': created,
        'updated': updated,
        'math_subjects': math_subjects.count(),
    }


def populate_math_subject_summaries(school_year, quarter):
    """Aggregate KPUP data for Math subjects only"""
    math_subjects = Subject.objects.filter(is_active=True).filter(
        Q(subject_name__icontains='math') |
        Q(subject_code__icontains='math') |
        Q(subject_code__in=['CORE-GENMATH-G11', 'CORE-STATS-G11', 'SP-STEM-PRECALC', 'SP-STEM-BASCALC'])
    )
    
    for subject in math_subjects:
        masteries = KPUPMastery.objects.filter(
            subject=subject, quarter=quarter, school_year=school_year
        )
        
        if not masteries.exists():
            continue
        
        total = masteries.count()
        
        SubjectKPUPSummary.objects.update_or_create(
            subject=subject, quarter=quarter, school_year=school_year,
            defaults={
                'avg_knowledge': round(masteries.aggregate(Avg('knowledge_score'))['knowledge_score__avg'] or 0, 2),
                'avg_process': round(masteries.aggregate(Avg('process_score'))['process_score__avg'] or 0, 2),
                'avg_understanding': round(masteries.aggregate(Avg('understanding_score'))['understanding_score__avg'] or 0, 2),
                'avg_product': round(masteries.aggregate(Avg('product_score'))['product_score__avg'] or 0, 2),
                'advanced_count': masteries.filter(overall_mastery='ADVANCED').count(),
                'proficient_count': masteries.filter(overall_mastery='PROFICIENT').count(),
                'developing_count': masteries.filter(overall_mastery='DEVELOPING').count(),
                'beginning_count': masteries.filter(overall_mastery='BEGINNING').count(),
                'total_students': total,
            }
        )


def get_subject_kpup_dashboard(school_year, quarter, subject_filter=None):
    """Get KPUP data for principal dashboard"""
    summaries = SubjectKPUPSummary.objects.filter(
        school_year=school_year, quarter=quarter
    ).select_related('subject')
    
    if subject_filter:
        summaries = summaries.filter(subject__in=subject_filter)
    
    dashboard_data = []
    for summary in summaries:
        if summary.avg_understanding >= 85 and summary.avg_product >= 80:
            status, status_label = 'strong', 'Strong'
        elif summary.avg_knowledge >= 70 and summary.avg_process >= 65:
            status, status_label = 'adequate', 'Adequate'
        else:
            status, status_label = 'needs_attention', 'Needs Attention'
        
        overall = round((summary.avg_knowledge + summary.avg_process + 
                        summary.avg_understanding + summary.avg_product) / 4, 2)
        _, overall_letter = get_proficiency_level(overall)
        
        dashboard_data.append({
            'subject_id': summary.subject.id,
            'subject_code': summary.subject.subject_code,
            'subject_name': summary.subject.subject_name,
            'grade_level': summary.subject.grade_level.grade_name if summary.subject.grade_level else 'N/A',
            'avg_knowledge': summary.avg_knowledge,
            'avg_process': summary.avg_process,
            'avg_understanding': summary.avg_understanding,
            'avg_product': summary.avg_product,
            'overall_avg': overall,
            'overall_letter': overall_letter,
            'total_students': summary.total_students,
            'advanced_count': summary.advanced_count,
            'proficient_count': summary.proficient_count,
            'developing_count': summary.developing_count,
            'beginning_count': summary.beginning_count,
            'radar_data': [summary.avg_knowledge, summary.avg_process, summary.avg_understanding, summary.avg_product],
            'distribution': [summary.advanced_count, summary.proficient_count, summary.developing_count, summary.beginning_count],
            'status': status, 'status_label': status_label,
        })
    
    status_order = {'needs_attention': 0, 'adequate': 1, 'strong': 2}
    dashboard_data.sort(key=lambda x: (status_order.get(x['status'], 99), x['grade_level']))
    
    return dashboard_data


# =============================================================================
# SIMULATE ENGLISH ASSESSMENT DATA (Grade 1-12)
# =============================================================================
def simulate_english_assessments(school_year=None, quarter=None):
    """Creates realistic English assessment items and student results for all grade levels."""
    if not school_year:
        school_year = SchoolYear.objects.filter(is_current=True).first()
    if not quarter:
        quarter = Quarter.objects.filter(school_year=school_year, is_current_quarter=True).first()
    
    if not school_year or not quarter:
        return {'success': False, 'error': 'No active school year or quarter found'}
    
    # Find English subjects
    english_subjects = Subject.objects.filter(
        is_active=True,
        subject_name__icontains='english'
    ) | Subject.objects.filter(
        is_active=True,
        subject_code__icontains='eng'
    ) | Subject.objects.filter(
        is_active=True,
        subject_code__in=['CORE-EAPP-G11', 'CORE-EAPP-G12']
    )
    
    if not english_subjects.exists():
        return {'success': False, 'error': 'No English subjects found. Seed subjects first.'}
    
    # Clear existing English assessment data for this quarter
    AssessmentItem.objects.filter(subject__in=english_subjects).delete()
    
    english_topics = {
        'elementary': ['Phonics', 'Vocabulary', 'Reading Comprehension', 'Grammar Basics', 'Spelling', 'Sentence Writing', 'Parts of Speech', 'Punctuation', 'Story Elements', 'Listening Skills'],
        'jhs': ['Essay Writing', 'Literary Analysis', 'Poetry', 'Grammar', 'Research Skills', 'Public Speaking', 'Debate', 'Reading Comprehension', 'Vocabulary Building', 'Creative Writing'],
        'shs': ['Academic Writing', 'Research Paper', 'Critical Analysis', 'Argumentation', 'Literature Review', 'Professional Communication', 'Thesis Writing', 'Text Analysis', 'Media Literacy', 'Speech Writing'],
    }
    
    items_created = 0
    results_created = 0
    
    for subject in english_subjects:
        grade_num = subject.grade_level.grade_number if subject.grade_level else 7
        if grade_num <= 6:
            cluster = 'elementary'
        elif grade_num <= 10:
            cluster = 'jhs'
        else:
            cluster = 'shs'
        
        topics = english_topics[cluster]
        assessment_items = []
        
        item_distribution = [
            ('REMEMBERING', 5),
            ('UNDERSTANDING', 5),
            ('APPLYING', 5),
            ('ANALYZING', 5),
            ('EVALUATING', 5),
            ('CREATING', 5),
        ]
        
        for cognitive_level, count in item_distribution:
            for i in range(count):
                topic = random.choice(topics)
                
                templates = {
                    'REMEMBERING': [
                        f"Define the term: {topic}.",
                        f"List the key elements of {topic}.",
                        f"Identify the correct definition of {topic}.",
                        f"What are the rules of {topic}?",
                        f"State the main components of {topic}.",
                    ],
                    'UNDERSTANDING': [
                        f"Explain the concept of {topic} in your own words.",
                        f"Summarize the main idea of this {topic} passage.",
                        f"Describe how {topic} is used in writing.",
                        f"Interpret the meaning of this {topic} example.",
                        f"Paraphrase the following {topic} statement.",
                    ],
                    'APPLYING': [
                        f"Write a sentence using correct {topic}.",
                        f"Apply {topic} rules to correct this paragraph.",
                        f"Use {topic} to compose a short response.",
                        f"Demonstrate proper {topic} in this exercise.",
                        f"Construct a paragraph that follows {topic} guidelines.",
                    ],
                    'ANALYZING': [
                        f"Analyze the author's use of {topic} in this text.",
                        f"Compare these two examples of {topic}.",
                        f"Break down the structure of this {topic}.",
                        f"Identify the patterns in this {topic} passage.",
                        f"Examine how {topic} affects the meaning of the text.",
                    ],
                    'EVALUATING': [
                        f"Evaluate the effectiveness of this {topic}.",
                        f"Justify why this {topic} approach is better.",
                        f"Critique this student's use of {topic}.",
                        f"Assess the quality of {topic} in this essay.",
                        f"Judge which {topic} technique is most effective and why.",
                    ],
                    'CREATING': [
                        f"Write an original essay demonstrating {topic}.",
                        f"Create a story that showcases proper {topic}.",
                        f"Design a presentation about {topic}.",
                        f"Compose a poem using {topic} techniques.",
                        f"Develop a creative piece that applies {topic}.",
                    ],
                }
                
                question_text = random.choice(templates[cognitive_level])
                max_score = random.choice([5, 10, 15, 20])
                
                item = AssessmentItem.objects.create(
                    subject=subject,
                    question_text=question_text,
                    cognitive_level=cognitive_level,
                    max_score=max_score,
                    topic=topic,
                )
                assessment_items.append(item)
                items_created += 1
        
        # Get students and create results
        enrollments = Enrollment.objects.filter(
            school_year=school_year,
            status__in=['Enrolled', 'Transferred_In'],
            section__grade_level=subject.grade_level,
        ).select_related('student', 'section')
        
        for enrollment in enrollments:
            base_ability = random.gauss(80, 6)
            base_ability = max(60, min(98, base_ability))

            cognitive_difficulty = {
                'REMEMBERING':   1.00,
                'UNDERSTANDING': 0.95,
                'APPLYING':      0.90,
                'ANALYZING':     0.85,
                'EVALUATING':    0.80,
                'CREATING':      0.75,
            }

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
                results_created += 1
    
    return {
        'success': True,
        'items_created': items_created,
        'results_created': results_created,
        'english_subjects': english_subjects.count(),
    }


def classify_all_english_students(school_year=None, quarter=None):
    """Run the KPUP classifier on all English students."""
    if not school_year:
        school_year = SchoolYear.objects.filter(is_current=True).first()
    if not quarter:
        quarter = Quarter.objects.filter(school_year=school_year, is_current_quarter=True).first()
    
    if not school_year or not quarter:
        return {'success': False, 'error': 'No active school year or quarter found'}
    
    english_subjects = Subject.objects.filter(
        is_active=True,
        subject_name__icontains='english'
    ) | Subject.objects.filter(
        is_active=True,
        subject_code__icontains='eng'
    ) | Subject.objects.filter(
        is_active=True,
        subject_code__in=['CORE-EAPP-G11', 'CORE-EAPP-G12']
    )
    
    if not english_subjects.exists():
        return {'success': False, 'error': 'No English subjects found'}
    
    created = 0
    updated = 0
    
    for subject in english_subjects:
        student_ids = StudentAssessmentResult.objects.filter(
            assessment_item__subject=subject,
            quarter=quarter,
            school_year=school_year
        ).values_list('student_id', flat=True).distinct()
        
        for student_id in student_ids:
            from students.models import Student
            student = Student.objects.get(id=student_id)
            
            kpup_data = classify_student_kpup(student, subject, quarter, school_year)
            
            if not kpup_data:
                continue
            
            mastery, was_created = KPUPMastery.objects.update_or_create(
                student=student,
                subject=subject,
                quarter=quarter,
                school_year=school_year,
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
            
            if was_created:
                created += 1
            else:
                updated += 1
    
    # Aggregate subject summaries
    english_summary_subjects = Subject.objects.filter(is_active=True).filter(
        Q(subject_name__icontains='english') |
        Q(subject_code__icontains='eng') |
        Q(subject_code__in=['CORE-EAPP-G11', 'CORE-EAPP-G12'])
    )
    
    for subject in english_summary_subjects:
        masteries = KPUPMastery.objects.filter(
            subject=subject, quarter=quarter, school_year=school_year
        )
        if masteries.exists():
            total = masteries.count()
            SubjectKPUPSummary.objects.update_or_create(
                subject=subject, quarter=quarter, school_year=school_year,
                defaults={
                    'avg_knowledge': round(masteries.aggregate(Avg('knowledge_score'))['knowledge_score__avg'] or 0, 2),
                    'avg_process': round(masteries.aggregate(Avg('process_score'))['process_score__avg'] or 0, 2),
                    'avg_understanding': round(masteries.aggregate(Avg('understanding_score'))['understanding_score__avg'] or 0, 2),
                    'avg_product': round(masteries.aggregate(Avg('product_score'))['product_score__avg'] or 0, 2),
                    'advanced_count': masteries.filter(overall_mastery='ADVANCED').count(),
                    'proficient_count': masteries.filter(overall_mastery='PROFICIENT').count(),
                    'developing_count': masteries.filter(overall_mastery='DEVELOPING').count(),
                    'beginning_count': masteries.filter(overall_mastery='BEGINNING').count(),
                    'total_students': total,
                }
            )
    
    return {
        'success': True,
        'created': created,
        'updated': updated,
        'english_subjects': english_subjects.count(),
    }