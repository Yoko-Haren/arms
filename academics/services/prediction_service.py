# academics/services/prediction_service.py
"""
Grade prediction service - Uses simple ML models to predict future grades
"""

import math
from .trend_detection import detect_trend, predict_next_grade


class GradePredictorService:
    """
    Service for predicting student and section grades
    
    This is a simplified version that uses statistical methods.
    Can be enhanced with actual ML models (XGBoost, etc.) later.
    """
    
    def __init__(self):
        self.is_trained = False
        self.model_version = "1.0.0-statistical"
    
    def predict_student_grade(self, historical_grades, attendance_rate=85, subject_difficulty=1.0):
        """
        Predict a student's next grade based on historical performance
        
        Args:
            historical_grades: List of past grades [Q1, Q2, Q3]
            attendance_rate: Student's attendance percentage (0-100)
            subject_difficulty: Subject difficulty multiplier (0.8-1.2)
        
        Returns:
            dict: {
                'predicted_grade': float,
                'confidence': float,
                'risk_factors': list
            }
        """
        if not historical_grades or len(historical_grades) < 1:
            return {
                'predicted_grade': None,
                'confidence': 0,
                'risk_factors': ['Insufficient historical data for prediction']
            }
        
        # Filter out None values
        valid_grades = [g for g in historical_grades if g is not None]
        
        if len(valid_grades) < 2:
            # Use simple average for single data point
            predicted = valid_grades[0] if valid_grades else 75
            confidence = 0.5
        else:
            # Use linear regression for trend-based prediction
            predicted = predict_next_grade(valid_grades)
            trend = detect_trend(valid_grades)
            confidence = trend['confidence']
        
        # Adjust for attendance
        if attendance_rate < 80:
            predicted -= (80 - attendance_rate) * 0.3
            predicted = max(0, min(100, predicted))
        
        # Adjust for subject difficulty
        predicted = predicted * subject_difficulty
        predicted = max(0, min(100, predicted))
        
        # Determine risk factors
        risk_factors = []
        if valid_grades and valid_grades[-1] < 75:
            risk_factors.append("Currently below passing threshold")
        if attendance_rate < 85:
            risk_factors.append(f"Low attendance ({attendance_rate}%)")
        
        trend = detect_trend(valid_grades) if len(valid_grades) >= 2 else {'direction': 'insufficient_data'}
        if trend['direction'] == 'declining':
            risk_factors.append("Grades are consistently declining")
        
        if not risk_factors and predicted < 75:
            risk_factors.append("Predicted grade below passing threshold")
        
        return {
            'predicted_grade': round(predicted, 2),
            'confidence': round(confidence, 2),
            'risk_factors': risk_factors,
            'is_at_risk': predicted < 75 or len(risk_factors) > 0
        }
    
    def predict_section_grade(self, section_name, student_grades_list, attendance_rates=None):
        """
        Predict a section's average grade
        
        Args:
            section_name: Name of the section
            student_grades_list: List of each student's historical grades
            attendance_rates: Optional list of attendance rates per student
        
        Returns:
            dict: {
                'predicted_average': float,
                'passing_rate': float,
                'excellent_rate': float,
                'at_risk_count': int,
                'confidence': float
            }
        """
        if not student_grades_list:
            return {
                'predicted_average': None,
                'passing_rate': 0,
                'excellent_rate': 0,
                'at_risk_count': 0,
                'confidence': 0
            }
        
        predictions = []
        at_risk_count = 0
        
        for i, student_grades in enumerate(student_grades_list):
            attendance = attendance_rates[i] if attendance_rates and i < len(attendance_rates) else 85
            result = self.predict_student_grade(student_grades, attendance)
            
            if result['predicted_grade']:
                predictions.append(result['predicted_grade'])
                if result['is_at_risk']:
                    at_risk_count += 1
        
        if not predictions:
            return {
                'predicted_average': None,
                'passing_rate': 0,
                'excellent_rate': 0,
                'at_risk_count': 0,
                'confidence': 0
            }
        
        predicted_average = sum(predictions) / len(predictions)
        passing_count = sum(1 for g in predictions if g >= 75)
        excellent_count = sum(1 for g in predictions if g >= 90)
        
        return {
            'predicted_average': round(predicted_average, 2),
            'passing_rate': round((passing_count / len(predictions)) * 100, 1),
            'excellent_rate': round((excellent_count / len(predictions)) * 100, 1),
            'at_risk_count': at_risk_count,
            'confidence': 0.75  # Statistical confidence
        }
    
    def predict_risk_level(self, current_grade, trend_direction, attendance_rate, days_until_exam=30):
        """
        Calculate risk score for a student
        
        Returns:
            dict: {
                'risk_score': int (0-100),
                'risk_level': 'Low' | 'Medium' | 'High' | 'Critical',
                'factors': list
            }
        """
        risk_score = 0
        factors = []
        
        # Current grade factor (max 40 points)
        if current_grade < 60:
            risk_score += 40
            factors.append(f"Very low grade ({current_grade}%)")
        elif current_grade < 70:
            risk_score += 30
            factors.append(f"Low grade ({current_grade}%)")
        elif current_grade < 75:
            risk_score += 20
            factors.append(f"Near failing ({current_grade}%)")
        elif current_grade < 80:
            risk_score += 10
            factors.append(f"Below average ({current_grade}%)")
        
        # Trend factor (max 30 points)
        if trend_direction == 'declining':
            risk_score += 30
            factors.append("Grades are declining")
        elif trend_direction == 'erratic':
            risk_score += 15
            factors.append("Inconsistent performance")
        elif trend_direction == 'stable' and current_grade < 75:
            risk_score += 20
            factors.append("Stuck below passing threshold")
        
        # Attendance factor (max 20 points)
        if attendance_rate < 70:
            risk_score += 20
            factors.append(f"Poor attendance ({attendance_rate}%)")
        elif attendance_rate < 85:
            risk_score += 10
            factors.append(f"Below target attendance ({attendance_rate}%)")
        
        # Time factor (max 10 points)
        if days_until_exam < 7:
            risk_score += 10
            factors.append(f"Exam in {days_until_exam} days, little time to improve")
        elif days_until_exam < 14:
            risk_score += 5
            factors.append(f"Limited time before exam ({days_until_exam} days)")
        
        # Determine risk level
        if risk_score >= 70:
            risk_level = 'Critical'
        elif risk_score >= 50:
            risk_level = 'High'
        elif risk_score >= 25:
            risk_level = 'Medium'
        else:
            risk_level = 'Low'
        
        return {
            'risk_score': risk_score,
            'risk_level': risk_level,
            'factors': factors
        }