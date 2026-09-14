# ml_engine/scripts/train_risk_classifier.py
"""
ML Training Script for Risk Classification
"""

import os
import sys
import django
import pandas as pd
import numpy as np
import joblib
from datetime import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
django.setup()

from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

from enrollment.models import Enrollment
from grades.models import GradeComponent, FinalGrade
from attendance.models import AttendanceSummary


def extract_training_data():
    """Extract historical data for risk classification"""
    print("[INFO] Extracting risk training data...")
    
    enrollments = Enrollment.objects.filter(
        status='Enrolled'
    ).select_related('student', 'section')[:500]
    
    training_data = []
    
    for enrollment in enrollments:
        # Get Q1 grades
        q1_grades = GradeComponent.objects.filter(
            enrollment=enrollment,
            quarter__quarter_number=1
        )
        
        grade_values = [float(g.initial_grade) for g in q1_grades if g.initial_grade]
        if not grade_values:
            continue
        
        features = {}
        features['q1_average'] = np.mean(grade_values)
        features['q1_min'] = np.min(grade_values)
        features['subjects_below_75'] = sum(1 for g in grade_values if g < 75)
        
        # Attendance
        attendance = AttendanceSummary.objects.filter(
            enrollment=enrollment
        ).first()
        features['attendance_rate'] = 85
        if attendance and attendance.absence_rate_percent:
            features['attendance_rate'] = 100 - attendance.absence_rate_percent
        
        # Target: Did the student fail?
        final_grades = FinalGrade.objects.filter(enrollment=enrollment)
        features['target_at_risk'] = 1 if any(fg.final_grade and fg.final_grade < 75 for fg in final_grades) else 0
        
        training_data.append(features)
    
    print(f"[INFO] Extracted {len(training_data)} samples")
    return pd.DataFrame(training_data)


def train_model(df):
    """Train the risk classifier"""
    if df.empty:
        return None, None, 0
    
    feature_cols = ['q1_average', 'q1_min', 'subjects_below_75', 'attendance_rate']
    X = df[feature_cols].values
    y = df['target_at_risk'].values
    
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    X_train, X_val, y_train, y_val = train_test_split(X_scaled, y, test_size=0.2, random_state=42)
    
    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)
    
    predictions = model.predict(X_val)
    accuracy = accuracy_score(y_val, predictions)
    
    print(f"[INFO] Validation Accuracy: {accuracy:.2%}")
    
    version = datetime.now().strftime("%Y%m%d_%H%M%S")
    models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'saved_models')
    os.makedirs(models_dir, exist_ok=True)
    
    model_path = os.path.join(models_dir, f'risk_classifier_{version}.pkl')
    joblib.dump({'model': model, 'scaler': scaler, 'version': version}, model_path)
    
    return model_path, version, accuracy


def run_training():
    print("=" * 60)
    print("RISK CLASSIFIER TRAINING")
    print("=" * 60)
    
    df = extract_training_data()
    
    if len(df) < 10:
        print(f"[WARNING] Only {len(df)} samples. Need at least 10.")
        return {'success': False, 'error': 'Insufficient data'}
    
    model_path, version, accuracy = train_model(df)
    
    print("=" * 60)
    print(f"✅ TRAINING COMPLETE! Version: {version}, Accuracy: {accuracy:.2%}")
    print("=" * 60)
    
    return {'success': True, 'model_version': version, 'accuracy': accuracy}


if __name__ == "__main__":
    result = run_training()
    print(result)