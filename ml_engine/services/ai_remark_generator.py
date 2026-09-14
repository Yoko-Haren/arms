"""
AI-Powered Report Card Remark Generator
Uses local LLM (Qwen 2.5 1.5B) via Ollama
"""

import ollama


# =============================================================================
# DEPED PROFICIENCY LEVELS
# =============================================================================

PROFICIENCY_LEVELS = {
    'BEGINNING': {
        'label': 'Beginning',
        'abbreviation': 'B',
        'range': '74% and below',
        'description': 'Struggles with understanding; prerequisite knowledge not yet acquired.',
    },
    'DEVELOPING': {
        'label': 'Developing',
        'abbreviation': 'D',
        'range': '75-79%',
        'description': 'Possesses minimum knowledge but needs help with authentic tasks.',
    },
    'APPROACHING PROFICIENCY': {
        'label': 'Approaching Proficiency',
        'abbreviation': 'AP',
        'range': '80-84%',
        'description': 'Has developed fundamental skills; needs little guidance from teacher or peers.',
    },
    'PROFICIENT': {
        'label': 'Proficient',
        'abbreviation': 'P',
        'range': '85-89%',
        'description': 'Has mastered fundamentals; can transfer learning independently.',
    },
    'ADVANCED': {
        'label': 'Advanced',
        'abbreviation': 'A',
        'range': '90% and above',
        'description': 'Exceeds core requirements; transfers learning automatically and flexibly.',
    },
}


def get_proficiency_level(grade):
    """Convert numerical grade to DepEd proficiency level"""
    if grade is None:
        return None, None
    grade = float(grade)
    if grade <= 74:
        return 'BEGINNING', 'B'
    elif grade <= 79:
        return 'DEVELOPING', 'D'
    elif grade <= 84:
        return 'APPROACHING PROFICIENCY', 'AP'
    elif grade <= 89:
        return 'PROFICIENT', 'P'
    else:
        return 'ADVANCED', 'A'


# =============================================================================
# AI REMARK GENERATOR
# =============================================================================

class AIRemarkGenerator:
    """AI-powered remark generator using local Ollama model"""
    
    def __init__(self, model="qwen2.5:1.5b"):
        self.model = model
        self.available = self._check_ollama()
    
    def _check_ollama(self):
        try:
            ollama.list()
            print(f"[AI] Ollama connected. Model: {self.model}")
            return True
        except Exception:
            print("[AI] Ollama not available. Using built-in templates.")
            return False
    
    def generate_remark(self, student_data):
        """Generate a personalized report card remark"""
        
        first_name = student_data.get('first_name', 'Student')
        subject = student_data.get('subject_name', 'this subject')
        grade = student_data.get('grade', 75)
        trend = student_data.get('trend', 'stable')
        attendance = student_data.get('attendance_rate', 85)
        grade_level = student_data.get('grade_level', 10)
        quarter = student_data.get('quarter', 'current quarter')
        
        # Get proficiency level
        level_key, abbrev = get_proficiency_level(grade)
        level_info = PROFICIENCY_LEVELS.get(level_key, {})
        
        if self.available:
            remark = self._ai_remark(first_name, subject, grade, level_key, trend, attendance, grade_level, quarter)
            model_used = f"Ollama ({self.model})"
        else:
            remark = self._template_remark(first_name, subject, grade, level_key, trend)
            model_used = "Built-in templates (offline)"
        
        return {
            'proficiency_level': level_info.get('label', 'N/A'),
            'proficiency_abbreviation': abbrev,
            'proficiency_description': level_info.get('description', ''),
            'numeric_grade': round(float(grade), 2),
            'personalized_remark': remark,
            'ai_model': model_used,
        }
    
    def _ai_remark(self, name, subject, grade, level, trend, attendance, grade_level, quarter):
        """Generate remark using Ollama AI"""
        
        # Proficiency descriptions for the prompt
        prof_desc = "\n".join([
            f"- {v['label']} ({v['abbreviation']}): {v['description']}"
            for v in PROFICIENCY_LEVELS.values()
        ])
        
        # Language
        lang = "Tagalog/Filipino" if subject == 'Filipino' else "English"
        
        prompt = f"""You are a caring teacher in the Philippines writing a report card remark.
Write in {lang}.

Student: {name} (Grade {grade_level})
Subject: {subject}
Grade: {grade}%
Proficiency Level: {level}
Trend: {trend}
Attendance: {attendance}%
Quarter: {quarter}

DepEd Proficiency Guide:
{prof_desc}

Write a short, warm, professional remark (2-3 sentences only).
- Mention their proficiency level
- If improving, encourage them
- If below Proficient, suggest one specific improvement
- If attendance is below 80%, gently mention it
- End positively

Remark:"""
        
        try:
            response = ollama.generate(
                model=self.model,
                prompt=prompt,
                options={"temperature": 0.7, "max_tokens": 150}
            )
            return response['response'].strip()
        except Exception as e:
            print(f"[AI] Generation error: {e}")
            return self._template_remark(name, subject, grade, level, trend)
    
    def _template_remark(self, name, subject, grade, level, trend):
        """Fallback template-based remark"""
        
        templates = {
            'BEGINNING': f"{name} is struggling with core concepts in {subject} and needs intensive support. Regular practice and one-on-one guidance are strongly recommended.",
            'DEVELOPING': f"{name} has acquired minimum competencies in {subject} but requires consistent assistance. With continued effort, improvement is expected.",
            'APPROACHING PROFICIENCY': f"{name} has developed fundamental skills in {subject} and needs only occasional guidance. Keep working toward full independence.",
            'PROFICIENT': f"{name} demonstrates solid understanding of {subject} and works independently. Consistent effort is producing good results.",
            'ADVANCED': f"{name} exceeds expectations in {subject}, showing exceptional mastery and flexible application of concepts.",
        }
        
        remark = templates.get(level, f"{name} is making progress in {subject}.")
        
        # Add trend context
        if trend == 'improving':
            remark += f" {name} shows encouraging improvement this quarter."
        elif trend == 'declining':
            remark += f" However, a slight decline was noted. Let's work together to get back on track."
        
        return remark


# =============================================================================
# SINGLETON
# =============================================================================

ai_remark_generator = AIRemarkGenerator()