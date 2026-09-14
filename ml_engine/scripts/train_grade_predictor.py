# ml_engine/scripts/train_grade_predictor.py - ADAPTED FOR Q3→Q4 PREDICTION
"""
ML Training Script for Grade Prediction
Adapted to work with Q3 and Q4 grades (predicts Q4 from Q3)
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

from xgboost import XGBRegressor
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.metrics import mean_absolute_error, r2_score

from enrollment.models import Enrollment
from grades.models import GradeComponent
from academics.models import Subject


def extract_training_data():
    """Extract grade data - uses Q3 to predict Q4"""
    print("[INFO] Extracting training data (Q3 → Q4 prediction)")
    
    # Get all enrollments that have Q3 and Q4 grades
    enrollments = Enrollment.objects.filter(
        status='Enrolled'
    ).select_related('student', 'section')
    
    print(f"[INFO] Total enrollments: {enrollments.count()}")
    
    training_data = []
    
    for enrollment in enrollments:
        # Get all grades for this enrollment
        grades = GradeComponent.objects.filter(
            enrollment=enrollment
        ).select_related('subject', 'quarter')
        
        if not grades.exists():
            continue
        
        # Group by subject
        subject_grades = {}
        for grade in grades:
            subj_id = grade.subject_id
            quarter_num = grade.quarter.quarter_number
            grade_value = grade.initial_grade
            
            if grade_value is None:
                continue
                
            if subj_id not in subject_grades:
                subject_grades[subj_id] = {
                    'subject': grade.subject,
                    'grades': {}
                }
            subject_grades[subj_id]['grades'][quarter_num] = float(grade_value)
        
        # Create training samples
        for subj_id, data in subject_grades.items():
            grades_dict = data['grades']
            subject = data['subject']
            
            # We need Q3 to predict Q4
            q3 = grades_dict.get(3)
            q4 = grades_dict.get(4)
            
            if q3 is None or q4 is None:
                continue
            
            features = {
                'q3_grade': q3,
                'subject_code': subject.subject_code,
                'grade_level': enrollment.section.grade_level.grade_number if enrollment.section and enrollment.section.grade_level else 9,
            }
            
            # Add Q2 if available (better prediction)
            q2 = grades_dict.get(2)
            if q2 is not None:
                features['q2_grade'] = q2
                features['q2_q3_trend'] = q3 - q2
            else:
                features['q2_grade'] = q3
                features['q2_q3_trend'] = 0
            
            # Add Q1 if available (best prediction)
            q1 = grades_dict.get(1)
            if q1 is not None:
                features['q1_grade'] = q1
                features['trend'] = (q3 - q1) / 2
            else:
                features['q1_grade'] = q3
                features['trend'] = 0
            
            features['target_grade'] = q4
            training_data.append(features)
    
    print(f"[INFO] Extracted {len(training_data)} training samples")
    
    if len(training_data) == 0:
        print("[WARNING] No training samples with both Q3 and Q4 grades")
        print("[TIP] Make sure you have grades for Q3 and Q4 in the database")
    
    return pd.DataFrame(training_data)


def train_model(df):
    """Train the ML model"""
    if df.empty:
        return None, None, 0
    
    print(f"[INFO] Training data shape: {df.shape}")
    print(f"[INFO] Columns: {df.columns.tolist()}")
    
    # Encode subject
    encoder = LabelEncoder()
    df['subject_encoded'] = encoder.fit_transform(df['subject_code'].astype(str))
    
    # Features based on what's available
    feature_cols = ['q3_grade', 'subject_encoded', 'grade_level']
    
    # Add optional features if they exist
    if 'q2_grade' in df.columns:
        feature_cols.append('q2_grade')
        feature_cols.append('q2_q3_trend')
    if 'q1_grade' in df.columns:
        feature_cols.append('q1_grade')
        feature_cols.append('trend')
    
    X = df[feature_cols].values
    y = df['target_grade'].values
    
    # Scale
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # Split
    X_train, X_val, y_train, y_val = train_test_split(X_scaled, y, test_size=0.2, random_state=42)
    
    print(f"[INFO] Training samples: {len(X_train)}")
    print(f"[INFO] Validation samples: {len(X_val)}")
    
    # Train
    model = XGBRegressor(n_estimators=100, max_depth=3, learning_rate=0.1, random_state=42)
    model.fit(X_train, y_train)
    
    # Evaluate
    predictions = model.predict(X_val)
    mae = mean_absolute_error(y_val, predictions)
    r2 = r2_score(y_val, predictions)
    accuracy = max(0, min(1, 1 - (mae / 100)))
    
    print(f"[INFO] Validation MAE: {mae:.2f}")
    print(f"[INFO] R² Score: {r2:.4f}")
    print(f"[INFO] Accuracy: {accuracy:.2%}")
    
    # Save
    version = datetime.now().strftime("%Y%m%d_%H%M%S")
    models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'saved_models')
    os.makedirs(models_dir, exist_ok=True)
    
    model_path = os.path.join(models_dir, f'grade_predictor_{version}.pkl')
    joblib.dump({
        'model': model,
        'scaler': scaler,
        'encoder': encoder,
        'feature_names': feature_cols,
        'version': version,
        'accuracy': accuracy
    }, model_path)
    
    print(f"[INFO] Model saved to {model_path}")
    
    return model_path, version, accuracy


def run_training():
    """Main training function"""
    print("=" * 60)
    print("GRADE PREDICTOR TRAINING (Q3 → Q4)")
    print("=" * 60)
    
    df = extract_training_data()
    
    if len(df) < 5:
        print(f"\n[WARNING] Only {len(df)} samples. Need at least 5.")
        print("\n[DEBUG] Here's what we found:")
        print(f"  - Total GradeComponent records: {GradeComponent.objects.count()}")
        print(f"  - Enrollments with grades: {Enrollment.objects.filter(grade_components__isnull=False).distinct().count()}")
        print("\n[TIP] Make sure you have both Q3 and Q4 grades for the same subject.")
        return {'success': False, 'error': f'Insufficient data: {len(df)} samples'}
    
    model_path, version, accuracy = train_model(df)
    
    print("=" * 60)
    print(f"✅ TRAINING COMPLETE!")
    print(f"Model Version: {version}")
    print(f"Accuracy: {accuracy:.2%}")
    print("=" * 60)
    
    return {'success': True, 'model_version': version, 'accuracy': accuracy, 'samples': len(df)}


if __name__ == "__main__":
    result = run_training()
    print(result)