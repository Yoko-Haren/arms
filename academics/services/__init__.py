# academics/services/__init__.py
"""
AI Services for Academic Intelligence
"""

from .normalization_service import normalize_grade, denormalize_grade
from .trend_detection import detect_trend, calculate_momentum, predict_next_grade
from .categorization_service import categorize_section, calculate_category_score
from .prediction_service import GradePredictorService
from .recommendation_service import generate_section_recommendation

__all__ = [
    'normalize_grade',
    'denormalize_grade',
    'detect_trend',
    'calculate_momentum',
    'predict_next_grade',
    'categorize_section',
    'calculate_category_score',
    'GradePredictorService',
    'generate_section_recommendation',
]