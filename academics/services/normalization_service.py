# academics/services/normalization_service.py
"""
Grade normalization service - Converts ANY grade format to 0-100 scale
"""

def normalize_grade(raw_grade, schema=None):
    """
    Convert ANY grade format to 0-100 scale
    
    Args:
        raw_grade: The raw grade from database (float or string for letters)
        schema: GradingSchema object (optional, uses defaults if None)
    
    Returns:
        float: Normalized grade between 0-100
    """
    if raw_grade is None:
        return None
    
    # Default schema values
    scale_type = getattr(schema, 'scale_type', 'PERCENTAGE') if schema else 'PERCENTAGE'
    
    # Percentage scale (0-100)
    if scale_type == 'PERCENTAGE':
        normalized = float(raw_grade)
    
    # DNSC style: 1.0 is best, 5.0 is worst
    elif scale_type == 'NUMERIC_1_5':
        # 1.0 → 100, 5.0 → 0
        normalized = (5.0 - float(raw_grade)) / 4.0 * 100
    
    # Reverse numeric: 5.0 is best, 1.0 is worst
    elif scale_type == 'NUMERIC_5_1':
        # 5.0 → 100, 1.0 → 0
        normalized = (float(raw_grade) - 1.0) / 4.0 * 100
    
    # GPA 4.0 scale
    elif scale_type == 'GPA_4':
        # 4.0 → 100, 0.0 → 0
        normalized = float(raw_grade) / 4.0 * 100
    
    # GPA 5.0 scale
    elif scale_type == 'GPA_5':
        # 5.0 → 100, 0.0 → 0
        normalized = float(raw_grade) / 5.0 * 100
    
    # Letter grades (A, B, C, D, F)
    elif scale_type == 'LETTER':
        mapping = {
            'A+': 4.0, 'A': 4.0, 'A-': 3.7,
            'B+': 3.3, 'B': 3.0, 'B-': 2.7,
            'C+': 2.3, 'C': 2.0, 'C-': 1.7,
            'D+': 1.3, 'D': 1.0,
            'F': 0.0
        }
        if schema and hasattr(schema, 'letter_grade_mapping') and schema.letter_grade_mapping:
            mapping.update(schema.letter_grade_mapping)
        
        gpa = mapping.get(str(raw_grade).upper(), 0)
        normalized = gpa / 4.0 * 100
    
    else:
        normalized = float(raw_grade)
    
    # Apply rounding
    rounding_rule = getattr(schema, 'rounding_rule', 'NEAREST_INT') if schema else 'NEAREST_INT'
    
    if rounding_rule == 'NEAREST_INT':
        normalized = round(normalized)
    elif rounding_rule == 'ONE_DECIMAL':
        normalized = round(normalized, 1)
    elif rounding_rule == 'TWO_DECIMAL':
        normalized = round(normalized, 2)
    
    # Clamp to valid range (0-100)
    normalized = max(0, min(100, normalized))
    
    return normalized


def denormalize_grade(normalized_grade, schema=None):
    """
    Convert 0-100 grade BACK to school's native format
    
    Args:
        normalized_grade: Grade in 0-100 scale
        schema: GradingSchema object (optional, uses defaults if None)
    
    Returns:
        float or str: Grade in school's native format
    """
    if normalized_grade is None:
        return None
    
    scale_type = getattr(schema, 'scale_type', 'PERCENTAGE') if schema else 'PERCENTAGE'
    
    if scale_type == 'PERCENTAGE':
        result = normalized_grade
    
    elif scale_type == 'NUMERIC_1_5':
        # 100 → 1.0, 0 → 5.0
        result = 5.0 - (normalized_grade / 100 * 4.0)
        result = round(result, 2)
    
    elif scale_type == 'NUMERIC_5_1':
        # 100 → 5.0, 0 → 1.0
        result = 1.0 + (normalized_grade / 100 * 4.0)
        result = round(result, 2)
    
    elif scale_type in ['GPA_4', 'GPA_5']:
        max_gpa = 4.0 if scale_type == 'GPA_4' else 5.0
        result = normalized_grade / 100 * max_gpa
        result = round(result, 2)
    
    elif scale_type == 'LETTER':
        # Convert back to letter grade approximation
        if normalized_grade >= 93:
            result = 'A'
        elif normalized_grade >= 90:
            result = 'A-'
        elif normalized_grade >= 87:
            result = 'B+'
        elif normalized_grade >= 83:
            result = 'B'
        elif normalized_grade >= 80:
            result = 'B-'
        elif normalized_grade >= 77:
            result = 'C+'
        elif normalized_grade >= 73:
            result = 'C'
        elif normalized_grade >= 70:
            result = 'C-'
        elif normalized_grade >= 67:
            result = 'D+'
        elif normalized_grade >= 60:
            result = 'D'
        else:
            result = 'F'
    
    else:
        result = normalized_grade
    
    # Apply rounding
    rounding_rule = getattr(schema, 'rounding_rule', 'NEAREST_INT') if schema else 'NEAREST_INT'
    
    if rounding_rule == 'NEAREST_INT':
        result = round(result)
    elif rounding_rule == 'ONE_DECIMAL':
        result = round(result, 1)
    elif rounding_rule == 'TWO_DECIMAL':
        result = round(result, 2)
    
    return result