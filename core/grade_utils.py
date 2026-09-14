import json
from academics.models import GradingSchema


def get_grade_info(score, school, schema_type=None):
    """
    Convert a numerical score to letter grade.
    
    Args:
        score: Numerical score
        school: School object
        schema_type: 'PERCENTAGE', 'GPA_4POINT', etc. (None = default)
    
    Returns:
        dict with letter, label, gpa, passing, schema info
    """
    if schema_type:
        schema = GradingSchema.objects.filter(
            school=school, scale_type=schema_type
        ).first()
    else:
        schema = GradingSchema.objects.filter(school=school).first()

    if not schema or not schema.letter_grade_mapping:
        return {
            'letter': 'N/A', 'label': 'No Schema',
            'gpa': 0, 'passing': False,
            'schema_type': 'N/A', 'description': 'N/A', 'period_type': 'N/A',
        }

    try:
        mapping = json.loads(schema.letter_grade_mapping)
        for r in mapping.get('ranges', []):
            if r['min'] <= score <= r['max']:
                return {
                    'letter': r['letter'],
                    'label': r['label'],
                    'gpa': r.get('gpa', 0),
                    'passing': r.get('passing', True),
                    'schema_type': schema.scale_type,
                    'description': mapping.get('description', ''),
                    'period_type': mapping.get('period_type', 'QUARTERLY'),
                }
    except (json.JSONDecodeError, KeyError):
        pass

    return {
        'letter': 'N/A', 'label': 'No Match',
        'gpa': 0, 'passing': False,
        'schema_type': schema.scale_type if schema else 'N/A',
        'description': 'Score out of range', 'period_type': 'N/A',
    }


def is_passing(score, school, schema_type=None):
    """Quick check if a score is passing."""
    return get_grade_info(score, school, schema_type)['passing']


def get_all_schemas(school):
    """Get all grading schemas for a school."""
    schemas = GradingSchema.objects.filter(school=school)
    result = []
    for s in schemas:
        mapping = json.loads(s.letter_grade_mapping) if s.letter_grade_mapping else {}
        result.append({
            'id': s.id,
            'scale_type': s.scale_type,
            'description': mapping.get('description', ''),
            'period_type': mapping.get('period_type', 'QUARTERLY'),
            'passing_threshold': s.passing_threshold,
            'ranges': mapping.get('ranges', []),
        })
    return result