# assessments/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db import transaction
import json
import random

from academics.models import Assessment, AssessmentQuestion, AssessmentResponse, AssessmentAnswer
from academics.models import Subject, Section, SchoolYear, Quarter


@login_required
def assessment_list(request):
    """Teacher's list of assessments."""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'teacher':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    teacher_school = request.user.profile.school
    
    assessments = Assessment.objects.filter(
        teacher=request.user
    ).select_related('subject', 'section').order_by('-created_at')
    
    context = {
        'assessments': assessments,
        'subjects': Subject.objects.filter(school=teacher_school, is_active=True),
        'sections': Section.objects.filter(school=teacher_school, is_active=True),
        'school_years': SchoolYear.objects.filter(school=teacher_school, is_current=True),
        'quarters': Quarter.objects.filter(school_year__school=teacher_school, school_year__is_current=True),
    }
    return render(request, 'teachers/assessments/list.html', context)


@login_required
def assessment_create_page(request):
    """Page where teacher creates a quiz."""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'teacher':
        return redirect('signin')
    
    teacher_school = request.user.profile.school
    
    context = {
        'subjects': Subject.objects.filter(school=teacher_school, is_active=True),
        'sections': Section.objects.filter(school=teacher_school, is_active=True),
        'school_years': SchoolYear.objects.filter(school=teacher_school, is_current=True),
        'quarters': Quarter.objects.filter(school_year__school=teacher_school, school_year__is_current=True),
    }
    return render(request, 'teachers/assessments/create.html', context)


@login_required
@csrf_exempt
def assessment_create_api(request):
    """API endpoint to save assessment."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)
    
    try:
        data = json.loads(request.body)
        
        with transaction.atomic():
            assessment = Assessment.objects.create(
                teacher=request.user,
                subject_id=data['subject_id'],
                section_id=data['section_id'],
                school_year_id=data['school_year_id'],
                quarter_id=data.get('quarter_id'),
                title=data['title'],
                description=data.get('description', ''),
                total_items=data['total_items'],
                points_per_item=data.get('points_per_item', 1),
                passing_score=data.get('passing_score', 60),
                time_limit_minutes=data.get('time_limit_minutes'),
                status='published',
            )
            
            for i, q_data in enumerate(data['questions']):
                choices = q_data['choices']
                random.shuffle(choices)
                
                AssessmentQuestion.objects.create(
                    assessment=assessment,
                    question_text=q_data['question_text'],
                    order_number=i + 1,
                    num_choices=len(choices),
                    correct_answer_index=q_data['correct_index'],
                    choices=choices,
                )
            
            assessment.shuffle_questions()
        
        return JsonResponse({
            'success': True,
            'assessment_id': assessment.id,
            'access_code': assessment.access_code,
            'share_url': assessment.get_share_url(),
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def assessment_detail(request, assessment_id):
    assessment = get_object_or_404(Assessment, id=assessment_id, teacher=request.user)
    
    questions = assessment.questions.all().order_by('order_number')
    responses = assessment.responses.all().order_by('-submitted_at')
    
    total_responses = responses.count()
    passed_count = responses.filter(passed=True).count()
    failed_count = total_responses - passed_count
    passing_rate = round((passed_count / total_responses * 100), 1) if total_responses > 0 else 0
    
    context = {
        'assessment': assessment,
        'questions': questions,
        'responses': responses,
        'total_responses': total_responses,
        'passed_count': passed_count,
        'failed_count': failed_count,
        'passing_rate': passing_rate,
    }
    return render(request, 'assessments/detail.html', context)
