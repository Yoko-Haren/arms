# ml_engine/scripts/train_universal.py
"""
Universal Grade Predictor - Supports Quarterly, Trimestral, Semestral
"""

import os
import sys
import django
import pandas as pd
import numpy as np
import joblib
from datetime import datetime
from collections import defaultdict

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
django.setup()

from xgboost import XGBRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.metrics import mean_absolute_error, r2_score

from academics.models import Subject, Quarter, SchoolYear, GradingPeriod
from enrollment.models import Enrollment
from grades.models import GradeComponent


def get_period_config():
    """Get active grading period configuration"""
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    if not current_sy:
        return None, None, None
    
    grading_period = GradingPeriod.objects.filter(
        school_year=current_sy,
        is_active=True
    ).first()
    
    return current_sy, grading_period


def extract_training_data_universal():
    """Extract training data based on grading period"""
    current_sy, grading_period = get_period_config()
    
    if not current_sy:
        print("[ERROR] No current school year")
        return pd.DataFrame()
    
    period_type = grading_period.period_type if grading_period else 'QUARTERLY'
    num_periods = grading_period.number_of_periods if grading_period else 4
    
    print(f"[INFO] Period Type: {period_type}")
    print(f"[INFO] Number of Periods: {num_periods}")
    
    # Get quarters (our internal quarter system)
    quarters = list(Quarter.objects.filter(school_year=current_sy).order_by('quarter_number'))
    
    training_data = []
    
    if period_type == 'QUARTERLY':
        # Use Q1, Q2, Q3 to predict Q4
        q1 = quarters[0] if len(quarters) > 0 else None
        q2 = quarters[1] if len(quarters) > 1 else None
        q3 = quarters[2] if len(quarters) > 2 else None
        q4 = quarters[3] if len(quarters) > 3 else None
        
        if q1 and q2 and q3 and q4:
            grades_q1 = {(g.enrollment_id, g.subject_id): float(g.initial_grade) for g in GradeComponent.objects.filter(quarter=q1, initial_grade__isnull=False)}
            grades_q2 = {(g.enrollment_id, g.subject_id): float(g.initial_grade) for g in GradeComponent.objects.filter(quarter=q2, initial_grade__isnull=False)}
            grades_q3 = {(g.enrollment_id, g.subject_id): float(g.initial_grade) for g in GradeComponent.objects.filter(quarter=q3, initial_grade__isnull=False)}
            grades_q4 = {(g.enrollment_id, g.subject_id): float(g.initial_grade) for g in GradeComponent.objects.filter(quarter=q4, initial_grade__isnull=False)}
            
            all_keys = set(grades_q1.keys()) | set(grades_q2.keys()) | set(grades_q3.keys()) | set(grades_q4.keys())
            
            for enrollment_id, subject_id in all_keys:
                g1 = grades_q1.get((enrollment_id, subject_id))
                g2 = grades_q2.get((enrollment_id, subject_id))
                g3 = grades_q3.get((enrollment_id, subject_id))
                g4 = grades_q4.get((enrollment_id, subject_id))
                
                if g1 and g2 and g3 and g4:
                    training_data.append({
                        'period1': g1, 'period2': g2, 'period3': g3, 'target': g4,
                        'subject_id': subject_id, 'enrollment_id': enrollment_id,
                        'period_type': 'QUARTERLY'
                    })
    
    elif period_type == 'TRIMESTRAL':
        # Map Trimesters to quarters: T1=Q1+Q2, T2=Q3, T3=Q4
        # For prediction: Use T1 and T2 to predict T3
        if len(quarters) >= 3:
            # Calculate trimester averages
            trimester_data = defaultdict(dict)
            
            for g in GradeComponent.objects.filter(quarter__in=quarters[:3], initial_grade__isnull=False):
                key = (g.enrollment_id, g.subject_id)
                if g.quarter.quarter_number in [1, 2]:  # T1
                    if 't1' not in trimester_data[key]:
                        trimester_data[key]['t1'] = []
                    trimester_data[key]['t1'].append(float(g.initial_grade))
                elif g.quarter.quarter_number == 3:  # T2
                    if 't2' not in trimester_data[key]:
                        trimester_data[key]['t2'] = []
                    trimester_data[key]['t2'].append(float(g.initial_grade))
            
            # Get Q4 for T3
            q4 = quarters[3] if len(quarters) > 3 else None
            if q4:
                for g in GradeComponent.objects.filter(quarter=q4, initial_grade__isnull=False):
                    key = (g.enrollment_id, g.subject_id)
                    trimester_data[key]['t3'] = float(g.initial_grade)
            
            for key, data in trimester_data.items():
                if 't1' in data and 't2' in data and 't3' in data:
                    t1_avg = sum(data['t1']) / len(data['t1'])
                    t2_avg = sum(data['t2']) / len(data['t2'])
                    t3 = data['t3']
                    
                    training_data.append({
                        'period1': t1_avg, 'period2': t2_avg, 'target': t3,
                        'subject_id': key[1], 'enrollment_id': key[0],
                        'period_type': 'TRIMESTRAL'
                    })
    
    elif period_type == 'SEMESTRAL':
        # Map Semesters: S1=Q1+Q2, S2=Q3+Q4
        # For prediction: Use S1 to predict S2
        semester_data = defaultdict(dict)
        
        for g in GradeComponent.objects.filter(quarter__in=quarters, initial_grade__isnull=False):
            key = (g.enrollment_id, g.subject_id)
            if g.quarter.quarter_number in [1, 2]:  # S1
                if 's1' not in semester_data[key]:
                    semester_data[key]['s1'] = []
                semester_data[key]['s1'].append(float(g.initial_grade))
            elif g.quarter.quarter_number in [3, 4]:  # S2
                if 's2' not in semester_data[key]:
                    semester_data[key]['s2'] = []
                semester_data[key]['s2'].append(float(g.initial_grade))
        
        for key, data in semester_data.items():
            if 's1' in data and 's2' in data:
                s1_avg = sum(data['s1']) / len(data['s1'])
                s2_avg = sum(data['s2']) / len(data['s2'])
                
                training_data.append({
                    'period1': s1_avg, 'target': s2_avg,
                    'subject_id': key[1], 'enrollment_id': key[0],
                    'period_type': 'SEMESTRAL'
                })
    
    print(f"[INFO] Extracted {len(training_data)} training samples for {period_type}")
    return pd.DataFrame(training_data)


def train_model(df, period_type):
    """Train the model"""
    if df.empty:
        return None, None, 0
    
    print(f"[INFO] Training data shape: {df.shape}")
    
    # Encode subject
    encoder = LabelEncoder()
    df['subject_encoded'] = encoder.fit_transform(df['subject_id'].astype(str))
    
    # Features based on period type
    if period_type == 'SEMESTRAL':
        feature_cols = ['period1', 'subject_encoded']
    else:  # QUARTERLY or TRIMESTRAL
        feature_cols = ['period1', 'period2', 'subject_encoded']
        # Add derived features
        df['trend'] = df['period2'] - df['period1'] if 'period2' in df else 0
    
    X = df[feature_cols].values
    y = df['target'].values
    
    # Scale
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # Split
    X_train, X_val, y_train, y_val = train_test_split(X_scaled, y, test_size=0.2, random_state=42)
    
    print(f"[INFO] Training samples: {len(X_train)}")
    print(f"[INFO] Validation samples: {len(X_val)}")
    
    # Train XGBoost
    model = XGBRegressor(
        n_estimators=100,
        max_depth=4,
        learning_rate=0.1,
        random_state=42
    )
    model.fit(X_train, y_train)
    
    # Evaluate
    predictions = model.predict(X_val)
    mae = mean_absolute_error(y_val, predictions)
    r2 = r2_score(y_val, predictions)
    accuracy = max(0, min(1, 1 - (mae / 100)))
    
    print(f"\n[RESULTS]")
    print(f"  MAE: {mae:.2f} points")
    print(f"  R² Score: {r2:.4f}")
    print(f"  Accuracy: {accuracy:.2%}")
    
    # Save
    version = datetime.now().strftime("%Y%m%d_%H%M%S")
    models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'saved_models')
    os.makedirs(models_dir, exist_ok=True)
    
    model_path = os.path.join(models_dir, f'grade_predictor_{period_type}_{version}.pkl')
    joblib.dump({
        'model': model,
        'scaler': scaler,
        'encoder': encoder,
        'feature_names': feature_cols,
        'period_type': period_type,
        'version': version,
        'accuracy': accuracy
    }, model_path)
    
    print(f"\n[INFO] Model saved to {model_path}")
    
    return model_path, version, accuracy


def run_training():
    print("=" * 60)
    print("UNIVERSAL GRADE PREDICTOR")
    print("Supports: Quarterly | Trimestral | Semestral")
    print("=" * 60)
    
    _, grading_period = get_period_config()
    period_type = grading_period.period_type if grading_period else 'QUARTERLY'
    
    print(f"\n[CONFIG] Active Period Type: {period_type}")
    
    df = extract_training_data_universal()
    
    if len(df) < 100:
        print(f"[WARNING] Only {len(df)} samples. Need at least 100.")
        return {'success': False, 'error': 'Insufficient data'}
    
    model_path, version, accuracy = train_model(df, period_type)
    
    print("\n" + "=" * 60)
    print(f"✅ TRAINING COMPLETE!")
    print(f"Period Type: {period_type}")
    print(f"Model Version: {version}")
    print(f"Accuracy: {accuracy:.2%}")
    print("=" * 60)
    
    return {'success': True, 'model_version': version, 'accuracy': accuracy}


if __name__ == "__main__":
    result = run_training()
    print(result)