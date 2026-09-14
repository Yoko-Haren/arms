from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
import json

from academics.models import Assessment, AssessmentQuestion, AssessmentResponse, AssessmentAnswer


def quiz_login(request, access_code):
    assessment = get_object_or_404(Assessment, access_code=access_code, status='published')
    
    if request.method == 'POST':
        login_type = request.POST.get('login_type')
        student_name = request.POST.get('student_name', '').strip()
        student_email = request.POST.get('student_email', '').strip()
        
        if login_type == 'google' and student_email:
            request.session['quiz_student_email'] = student_email
            request.session['quiz_student_name'] = student_email.split('@')[0]
            return redirect('take_quiz', access_code=access_code)
        elif login_type == 'name' and student_name:
            request.session['quiz_student_name'] = student_name
            request.session['quiz_student_email'] = ''
            return redirect('take_quiz', access_code=access_code)
        else:
            return render(request, 'assessments/quiz_login.html', {
                'assessment': assessment,
                'error': 'Please fill in the required fields.',
            })
    
    return render(request, 'assessments/quiz_login.html', {'assessment': assessment})


def take_quiz(request, access_code):
    assessment = get_object_or_404(Assessment, access_code=access_code, status='published')
    student_name = request.session.get('quiz_student_name', 'Guest')
    
    if not request.session.get('quiz_student_name'):
        return redirect('quiz_login', access_code=access_code)
    
    questions = []
    if assessment.question_order:
        q_map = {q.id: q for q in assessment.questions.all()}
        for q_id in assessment.question_order:
            if q_id in q_map:
                q = q_map[q_id]
                questions.append({
                    'id': q.id,
                    'question_text': q.question_text,
                    'choices': q.get_display_choices(),
                })
    
    context = {
        'assessment': assessment,
        'questions': json.dumps(questions),
        'student_name': student_name,
        'time_limit': assessment.time_limit_minutes,
    }
    return render(request, 'assessments/take_quiz.html', context)


@csrf_exempt
def submit_quiz(request, access_code):
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=405)
    
    assessment = get_object_or_404(Assessment, access_code=access_code, status='published')
    
    try:
        data = json.loads(request.body)
        answers = data.get('answers', {})
        
        student_name = request.session.get('quiz_student_name', 'Anonymous')
        student_email = request.session.get('quiz_student_email', '')
        
        earned = 0
        total = 0
        
        with transaction.atomic():
            response = AssessmentResponse.objects.create(
                assessment=assessment,
                student_name=student_name,
                student_email=student_email,
                total_points=0,
                submitted_at=timezone.now(),
            )
            
            for q_id, selected in answers.items():
                question = AssessmentQuestion.objects.get(id=int(q_id), assessment=assessment)
                is_correct = (int(selected) == question.correct_answer_index)
                points = float(assessment.points_per_item) if is_correct else 0
                
                AssessmentAnswer.objects.create(
                    response=response,
                    question=question,
                    selected_index=int(selected),
                    is_correct=is_correct,
                    points_earned=points,
                )
                earned += points
                total += float(assessment.points_per_item)
            
            response.score = earned
            response.total_points = total
            response.passed = earned >= float(assessment.passing_score)
            response.save()
        
        return JsonResponse({
            'success': True,
            'score': float(earned),
            'total': float(total),
            'passed': response.passed,
            'percentage': round((earned / total * 100), 1) if total > 0 else 0,
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)