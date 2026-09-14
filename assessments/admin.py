from django.contrib import admin
from .models import Assessment, AssessmentQuestion, AssessmentResponse, AssessmentAnswer

admin.site.register(Assessment)
admin.site.register(AssessmentQuestion)
admin.site.register(AssessmentResponse)
admin.site.register(AssessmentAnswer)