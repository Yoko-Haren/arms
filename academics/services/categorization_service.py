# academics/services/categorization_service.py
"""
Section categorization service - Classifies sections by performance level
"""

def calculate_category_score(section_data):
    """
    Calculate score for section categorization
    
    section_data should contain:
    - average_grade (required)
    - passing_rate (required)
    - excellent_rate (required)
    - at_risk_count (required)
    - total_students (required)
    
    Returns:
        int: Score from 0-100
    """
    score = 0
    total_students = section_data.get('total_students', 1)
    at_risk_count = section_data.get('at_risk_count', 0)
    risk_percent = (at_risk_count / total_students) * 100 if total_students > 0 else 0
    
    # Criteria 1: Average grade (40% weight)
    avg_grade = section_data.get('average_grade', 0)
    if avg_grade >= 90:
        score += 40
    elif avg_grade >= 75:
        score += 20
    else:
        score += 0
    
    # Criteria 2: Passing rate (30% weight)
    passing_rate = section_data.get('passing_rate', 0)
    if passing_rate >= 90:
        score += 30
    elif passing_rate >= 75:
        score += 15
    else:
        score += 0
    
    # Criteria 3: Excellent rate (students with >90%) (20% weight)
    excellent_rate = section_data.get('excellent_rate', 0)
    if excellent_rate >= 50:
        score += 20
    elif excellent_rate >= 25:
        score += 10
    else:
        score += 0
    
    # Criteria 4: Risk percentage (10% weight)
    if risk_percent == 0:
        score += 10
    elif risk_percent <= 10:
        score += 7
    elif risk_percent <= 20:
        score += 4
    elif risk_percent <= 30:
        score += 2
    else:
        score += 0
    
    return score


def categorize_section(section_data):
    """
    Categorize section based on score
    
    Args:
        section_data: dict with keys:
            - average_grade
            - passing_rate  
            - excellent_rate
            - at_risk_count
            - total_students
    
    Returns:
        dict: {
            'category': 'EXCELLENCE' | 'STANDARD' | 'INTERVENTION',
            'label': 'Excellence Track' | 'Standard Track' | 'Intervention Track',
            'score': float,
            'needs_intervention': bool
        }
    """
    score = calculate_category_score(section_data)
    
    if score >= 80:
        return {
            'category': 'EXCELLENCE',
            'label': 'Excellence Track',
            'score': score,
            'needs_intervention': False,
            'color': 'success',
            'badge_class': 'bg-success',
            'icon': 'fas fa-trophy'
        }
    elif score >= 50:
        return {
            'category': 'STANDARD',
            'label': 'Standard Track',
            'score': score,
            'needs_intervention': False,
            'color': 'info',
            'badge_class': 'bg-info',
            'icon': 'fas fa-chart-line'
        }
    else:
        return {
            'category': 'INTERVENTION',
            'label': 'Intervention Track',
            'score': score,
            'needs_intervention': True,
            'color': 'danger',
            'badge_class': 'bg-danger',
            'icon': 'fas fa-exclamation-triangle'
        }


def get_category_badge(category):
    """Return badge HTML class for a category"""
    badges = {
        'EXCELLENCE': 'bg-success',
        'STANDARD': 'bg-info',
        'INTERVENTION': 'bg-danger',
        'UNKNOWN': 'bg-secondary'
    }
    return badges.get(category, 'bg-secondary')