# academics/services/trend_detection.py
"""
Trend detection service - Analyzes grade patterns over time
"""

import math


def detect_trend(grades):
    """
    Detect trend pattern from quarterly grades
    
    Args:
        grades: List of grades [Q1, Q2, Q3, Q4] (may have None for missing)
    
    Returns:
        dict: {
            'direction': 'improving' | 'declining' | 'stable' | 'erratic' | 'insufficient_data',
            'slope': float,
            'confidence': float,
            'volatility': float
        }
    """
    # Filter out None values
    valid_grades = [g for g in grades if g is not None]
    
    if len(valid_grades) < 2:
        return {
            'direction': 'insufficient_data',
            'slope': 0,
            'confidence': 0,
            'volatility': 0
        }
    
    # Simple linear regression
    n = len(valid_grades)
    x = list(range(1, n + 1))
    
    x_mean = sum(x) / n
    y_mean = sum(valid_grades) / n
    
    # Calculate slope
    numerator = sum((x[i] - x_mean) * (valid_grades[i] - y_mean) for i in range(n))
    denominator = sum((x[i] - x_mean) ** 2 for i in range(n))
    
    slope = numerator / denominator if denominator != 0 else 0
    intercept = y_mean - slope * x_mean
    
    # Calculate R-squared (confidence)
    ss_res = sum((valid_grades[i] - (slope * x[i] + intercept)) ** 2 for i in range(n))
    ss_tot = sum((valid_grades[i] - y_mean) ** 2 for i in range(n))
    r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
    
    # Calculate volatility (standard deviation)
    variance = sum((g - y_mean) ** 2 for g in valid_grades) / n
    volatility = math.sqrt(variance)
    
    # Determine direction
    if abs(slope) < 0.3:
        direction = 'stable'
    elif slope > 0.3 and r_squared > 0.6:
        direction = 'improving'
    elif slope < -0.3 and r_squared > 0.6:
        direction = 'declining'
    else:
        direction = 'erratic'
    
    return {
        'direction': direction,
        'slope': round(slope, 2),
        'confidence': round(r_squared, 2),
        'volatility': round(volatility, 2)
    }


def calculate_momentum(grades):
    """
    Calculate grade momentum (acceleration/deceleration)
    
    Returns:
        float: Positive = accelerating improvement, Negative = accelerating decline
    """
    if not grades or len(grades) < 3:
        return 0
    
    # Remove None values
    valid = [g for g in grades if g is not None]
    
    if len(valid) < 3:
        return 0
    
    # First derivative (rate of change)
    first_derivative = [valid[i] - valid[i-1] for i in range(1, len(valid))]
    
    # Second derivative (change in rate of change)
    if len(first_derivative) >= 2:
        momentum = first_derivative[-1] - first_derivative[0]
    else:
        momentum = 0
    
    return round(momentum, 2)


def predict_next_grade(grades):
    """
    Predict next quarter grade using linear regression
    
    Returns:
        float: Predicted grade (0-100)
    """
    valid_grades = [g for g in grades if g is not None]
    
    if len(valid_grades) < 2:
        return None
    
    n = len(valid_grades)
    x = list(range(1, n + 1))
    next_x = n + 1
    
    x_mean = sum(x) / n
    y_mean = sum(valid_grades) / n
    
    numerator = sum((x[i] - x_mean) * (valid_grades[i] - y_mean) for i in range(n))
    denominator = sum((x[i] - x_mean) ** 2 for i in range(n))
    
    slope = numerator / denominator if denominator != 0 else 0
    intercept = y_mean - slope * x_mean
    
    predicted = slope * next_x + intercept
    
    # Clamp to 0-100
    predicted = max(0, min(100, predicted))
    
    return round(predicted, 2)