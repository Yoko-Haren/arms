# ml_engine/scripts/train_ultimate_fixed.py
"""
ULTIMATE FLEXIBLE ML TRAINING - FIXED VERSION
Uses configuration.GradingPeriod model
Supports: Quarterly (JHS) and Semestral (SHS)
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
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.metrics import mean_absolute_error, r2_score

from academics.models import Subject, Quarter, SchoolYear
from configuration.models import GradingPeriod
from enrollment.models import Enrollment
from grades.models import GradeComponent
from attendance.models import AttendanceSummary


def get_grading_config():
    """Get grading configuration for current school year"""
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    if not current_sy:
        print("[ERROR] No current school year found")
        return None, None
    
    # Get active grading periods
    grading_periods = GradingPeriod.objects.filter(
        school_year=current_sy,
        is_active=True
    ).select_related('quarter', 'semester').order_by('order')
    
    config = []
    for gp in grading_periods:
        if gp.period_type == 'Quarter' and gp.quarter:
            config.append({
                'type': 'quarter',
                'number': gp.quarter.quarter_number,
                'label': gp.quarter.quarter_label,
                'weight': float(gp.weight_in_final_grade) if gp.weight_in_final_grade else 0.25,
                'is_open': gp.is_grade_encoding_open,
                'is_locked': gp.is_grades_locked
            })
        elif gp.period_type == 'Semester' and gp.semester:
            config.append({
                'type': 'semester',
                'number': gp.semester.semester_number,
                'label': gp.semester.semester_label,
                'weight': float(gp.weight_in_final_grade) if gp.weight_in_final_grade else 0.5,
                'is_open': gp.is_grade_encoding_open,
                'is_locked': gp.is_grades_locked
            })
    
    return current_sy, config


def analyze_available_data():
    """Analyze what grade data is actually available"""
    print("\n[ANALYSIS] Checking available grade data:")
    
    current_sy, config = get_grading_config()
    print(f"  School Year: {current_sy}")
    print(f"  Grading Periods configured: {len(config)}")
    
    for cfg in config:
        print(f"    {cfg['label']} ({cfg['type']} {cfg['number']}) - weight: {cfg['weight']}")
    
    # Check each quarter
    quarters = Quarter.objects.filter(school_year=current_sy).order_by('quarter_number')
    
    quarter_data = {}
    for q in quarters:
        grade_count = GradeComponent.objects.filter(quarter=q, initial_grade__isnull=False).count()
        subject_count = GradeComponent.objects.filter(quarter=q, initial_grade__isnull=False).values('subject_id').distinct().count()
        student_count = GradeComponent.objects.filter(quarter=q, initial_grade__isnull=False).values('enrollment_id').distinct().count()
        
        quarter_data[q.quarter_number] = {
            'label': q.quarter_label,
            'grade_count': grade_count,
            'subject_count': subject_count,
            'student_count': student_count
        }
        print(f"  Q{q.quarter_number}: {grade_count} grades, {subject_count} subjects, {student_count} students")
    
    # Determine which prediction strategies are possible
    strategies = []
    
    if quarter_data.get(1, {}).get('grade_count', 0) > 0 and quarter_data.get(2, {}).get('grade_count', 0) > 0:
        strategies.append("predict_q3_from_q1_q2")
    if quarter_data.get(2, {}).get('grade_count', 0) > 0 and quarter_data.get(3, {}).get('grade_count', 0) > 0:
        strategies.append("predict_q4_from_q2_q3")
    if quarter_data.get(1, {}).get('grade_count', 0) > 0:
        strategies.append("predict_q2_from_q1")
    if quarter_data.get(3, {}).get('grade_count', 0) > 0 and quarter_data.get(4, {}).get('grade_count', 0) > 0:
        strategies.append("predict_final_from_q3_q4")
    # For semestral: if only Q3 and Q4 exist (second semester)
    if quarter_data.get(3, {}).get('grade_count', 0) > 0:
        strategies.append("use_q3_as_baseline")
    
    print(f"\n[STRATEGIES] Possible prediction strategies: {strategies}")
    
    return quarter_data, strategies, config


def extract_training_data_intelligent(quarter_data, strategies, config):
    """Intelligently extract training data based on available periods"""
    print("\n[INFO] Extracting training data using intelligent strategy...")
    
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    if not current_sy:
        return pd.DataFrame()
    
    # Get enrollments that have grades
    enrollments_with_grades = Enrollment.objects.filter(
        grade_components__isnull=False,
        school_year=current_sy,
        status='Enrolled'
    ).distinct()
    
    print(f"[INFO] Enrollments with grades: {enrollments_with_grades.count()}")
    
    training_data = []
    strategy_used = defaultdict(int)
    
    for enrollment in enrollments_with_grades:
        # Get all grades for this enrollment
        grades = GradeComponent.objects.filter(
            enrollment=enrollment,
            initial_grade__isnull=False
        ).select_related('subject', 'quarter').order_by('quarter__quarter_number')
        
        if not grades:
            continue
        
        # Group by subject
        subject_grades = defaultdict(dict)
        for grade in grades:
            quarter_num = grade.quarter.quarter_number
            subject_grades[grade.subject_id][quarter_num] = float(grade.initial_grade)
        
        # Get attendance
        attendance = AttendanceSummary.objects.filter(enrollment=enrollment).first()
        attendance_rate = 85
        if attendance:
            if attendance.absence_rate_percent:
                attendance_rate = 100 - attendance.absence_rate_percent
            elif attendance.days_present and attendance.total_school_days:
                attendance_rate = (attendance.days_present / attendance.total_school_days) * 100
        
        # For each subject
        for subject_id, grade_dict in subject_grades.items():
            subject = Subject.objects.get(id=subject_id)
            available = sorted(grade_dict.keys())
            
            # Try different prediction strategies based on available data
            
            # Strategy 1: Predict Q3 from Q1+Q2
            if 1 in grade_dict and 2 in grade_dict and 'predict_q3_from_q1_q2' in strategies:
                features = {
                    'period1_grade': grade_dict[1],
                    'period2_grade': grade_dict[2],
                    'grade_diff': grade_dict[2] - grade_dict[1],
                    'subject_code': subject.subject_code,
                    'attendance_rate': attendance_rate,
                    'grade_level': enrollment.section.grade_level.grade_number if enrollment.section and enrollment.section.grade_level else 7,
                    'strategy': 'q1q2_to_q3'
                }
                
                if 3 in grade_dict:
                    features['target_grade'] = grade_dict[3]
                elif 4 in grade_dict:
                    features['target_grade'] = grade_dict[4]
                else:
                    features['target_grade'] = (grade_dict[1] + grade_dict[2]) / 2
                
                training_data.append(features)
                strategy_used['q1_q2_to_q3'] += 1
            
            # Strategy 2: Predict Q4 from Q2+Q3
            if 2 in grade_dict and 3 in grade_dict and 'predict_q4_from_q2_q3' in strategies:
                features = {
                    'period1_grade': grade_dict[2],
                    'period2_grade': grade_dict[3],
                    'grade_diff': grade_dict[3] - grade_dict[2],
                    'subject_code': subject.subject_code,
                    'attendance_rate': attendance_rate,
                    'grade_level': enrollment.section.grade_level.grade_number if enrollment.section and enrollment.section.grade_level else 7,
                    'strategy': 'q2q3_to_q4'
                }
                
                if 4 in grade_dict:
                    features['target_grade'] = grade_dict[4]
                else:
                    features['target_grade'] = (grade_dict[2] + grade_dict[3]) / 2
                
                training_data.append(features)
                strategy_used['q2_q3_to_q4'] += 1
            
            # Strategy 3: Predict Q2 from Q1
            if 1 in grade_dict and 'predict_q2_from_q1' in strategies:
                features = {
                    'period1_grade': grade_dict[1],
                    'subject_code': subject.subject_code,
                    'attendance_rate': attendance_rate,
                    'grade_level': enrollment.section.grade_level.grade_number if enrollment.section and enrollment.section.grade_level else 7,
                    'strategy': 'q1_to_q2'
                }
                
                if 2 in grade_dict:
                    features['target_grade'] = grade_dict[2]
                else:
                    features['target_grade'] = grade_dict[1]
                
                training_data.append(features)
                strategy_used['q1_to_q2'] += 1
            
            # Strategy 4: Use Q3 as baseline (for semestral/second semester)
            if 3 in grade_dict and 'use_q3_as_baseline' in strategies:
                features = {
                    'period1_grade': grade_dict[3],
                    'subject_code': subject.subject_code,
                    'attendance_rate': attendance_rate,
                    'grade_level': enrollment.section.grade_level.grade_number if enrollment.section and enrollment.section.grade_level else 7,
                    'strategy': 'q3_baseline'
                }
                
                if 4 in grade_dict:
                    features['target_grade'] = grade_dict[4]
                else:
                    features['target_grade'] = grade_dict[3]
                
                training_data.append(features)
                strategy_used['q3_baseline'] += 1
    
    print(f"\n[STRATEGY USAGE]")
    for strategy, count in strategy_used.items():
        print(f"  {strategy}: {count} samples")
    
    print(f"\n[INFO] Total training samples: {len(training_data)}")
    
    if not training_data:
        print("[WARNING] No training samples created")
        return pd.DataFrame()
    
    return pd.DataFrame(training_data)


def train_model(df):
    """Train the ML model"""
    if df.empty:
        return None, None, 0
    
    print(f"\n[INFO] Training data shape: {df.shape}")
    print(f"[INFO] Columns: {df.columns.tolist()}")
    
    # Encode subject
    encoder = LabelEncoder()
    df['subject_encoded'] = encoder.fit_transform(df['subject_code'].astype(str))
    
    # Feature columns based on what's available
    feature_cols = ['period1_grade', 'attendance_rate', 'subject_encoded', 'grade_level']
    
    if 'period2_grade' in df.columns:
        feature_cols.append('period2_grade')
    if 'grade_diff' in df.columns:
        feature_cols.append('grade_diff')
    
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
    
    model_path = os.path.join(models_dir, f'grade_predictor_{version}.pkl')
    joblib.dump({
        'model': model,
        'scaler': scaler,
        'encoder': encoder,
        'feature_names': feature_cols,
        'version': version,
        'accuracy': accuracy
    }, model_path)
    
    print(f"\n[INFO] Model saved to {model_path}")
    
    return model_path, version, accuracy


def run_training():
    """Main training function"""
    print("=" * 70)
    print("ULTIMATE FLEXIBLE GRADE PREDICTOR")
    print("Using configuration.GradingPeriod model")
    print("Supports: JHS (Quarterly) and SHS (Semestral)")
    print("=" * 70)
    
    # Get grading config
    current_sy, config = get_grading_config()
    if not current_sy:
        print("[ERROR] No current school year found")
        return {'success': False, 'error': 'No current school year'}
    
    print(f"\n[CONFIG] School Year: {current_sy}")
    print(f"[CONFIG] Active grading periods: {len(config)}")
    
    # Analyze available data
    quarter_data, strategies, config = analyze_available_data()
    
    if not strategies:
        print("\n[ERROR] No viable prediction strategies with current data.")
        print("        Need at least one of:")
        print("        - Q1 + Q2 grades to predict Q3")
        print("        - Q2 + Q3 grades to predict Q4")
        print("        - Q1 grades to predict Q2")
        print("        - Q3 grades as baseline (for semestral)")
        return {'success': False, 'error': 'No viable prediction strategies'}
    
    # Extract training data
    df = extract_training_data_intelligent(quarter_data, strategies, config)
    
    if len(df) < 5:
        print(f"\n[ERROR] Only {len(df)} training samples. Need at least 5.")
        return {'success': False, 'error': f'Insufficient data: {len(df)} samples'}
    
    # Train model
    model_path, version, accuracy = train_model(df)
    
    print("\n" + "=" * 70)
    print("✅ TRAINING COMPLETE!")
    print(f"   Model Version: {version}")
    print(f"   Accuracy: {accuracy:.2%}")
    print(f"   Training Samples: {len(df)}")
    print("=" * 70)
    
    return {'success': True, 'model_version': version, 'accuracy': accuracy, 'samples': len(df)}


if __name__ == "__main__":
    result = run_training()
    print(f"\nFinal Result: {result}")