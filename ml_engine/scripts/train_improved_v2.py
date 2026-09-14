# ml_engine/scripts/train_improved_v2.py
"""
IMPROVED V2 - Better feature engineering for grade prediction
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
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from academics.models import Subject, Quarter, SchoolYear
from enrollment.models import Enrollment
from grades.models import GradeComponent


def extract_training_data():
    """Extract training data with better features"""
    print("[INFO] Extracting improved training data...")
    
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    if not current_sy:
        print("[ERROR] No current school year")
        return pd.DataFrame()
    
    # Get quarters
    quarters = {q.quarter_number: q for q in Quarter.objects.filter(school_year=current_sy)}
    q1, q2, q3, q4 = quarters[1], quarters[2], quarters[3], quarters[4]
    
    # Get all grade components
    grades_q1 = { (g.enrollment_id, g.subject_id): float(g.initial_grade) for g in GradeComponent.objects.filter(quarter=q1, initial_grade__isnull=False) }
    grades_q2 = { (g.enrollment_id, g.subject_id): float(g.initial_grade) for g in GradeComponent.objects.filter(quarter=q2, initial_grade__isnull=False) }
    grades_q3 = { (g.enrollment_id, g.subject_id): float(g.initial_grade) for g in GradeComponent.objects.filter(quarter=q3, initial_grade__isnull=False) }
    grades_q4 = { (g.enrollment_id, g.subject_id): float(g.initial_grade) for g in GradeComponent.objects.filter(quarter=q4, initial_grade__isnull=False) }
    
    # Get all keys
    all_keys = set(grades_q1.keys()) | set(grades_q2.keys()) | set(grades_q3.keys()) | set(grades_q4.keys())
    
    training_data = []
    
    for enrollment_id, subject_id in all_keys:
        g1 = grades_q1.get((enrollment_id, subject_id))
        g2 = grades_q2.get((enrollment_id, subject_id))
        g3 = grades_q3.get((enrollment_id, subject_id))
        g4 = grades_q4.get((enrollment_id, subject_id))
        
        # Need all three quarters to predict Q4
        if g1 is None or g2 is None or g3 is None or g4 is None:
            continue
        
        # Get subject and enrollment info
        try:
            subject = Subject.objects.get(id=subject_id)
            enrollment = Enrollment.objects.get(id=enrollment_id)
            grade_level = enrollment.section.grade_level.grade_number if enrollment.section and enrollment.section.grade_level else 0
        except:
            continue
        
        # Calculate features - MORE SOPHISTICATED
        features = {
            # Raw grades
            'q1': g1,
            'q2': g2,
            'q3': g3,
            
            # Trends
            'trend_1_2': g2 - g1,
            'trend_2_3': g3 - g2,
            'acceleration': (g3 - g2) - (g2 - g1),
            
            # Averages
            'avg_1_2': (g1 + g2) / 2,
            'avg_1_3': (g1 + g2 + g3) / 3,
            
            # Weighted average (more weight on recent)
            'weighted_avg': (g1 * 0.15) + (g2 * 0.35) + (g3 * 0.5),
            
            # Momentum indicators
            'improving': 1 if g2 > g1 and g3 > g2 else 0,
            'declining': 1 if g2 < g1 and g3 < g2 else 0,
            
            # Volatility (standard deviation)
            'volatility': np.std([g1, g2, g3]),
            
            # Range (max - min)
            'range': max(g1, g2, g3) - min(g1, g2, g3),
            
            # Subject and grade level
            'subject_encoded': subject.subject_code,
            'grade_level': grade_level,
            
            # Target
            'target': g4
        }
        
        training_data.append(features)
    
    print(f"[INFO] Extracted {len(training_data)} training samples")
    return pd.DataFrame(training_data)


def train_model(df):
    """Train improved model"""
    if df.empty:
        return None, None, 0
    
    print(f"[INFO] Training data shape: {df.shape}")
    
    # Encode subject
    encoder = LabelEncoder()
    df['subject_encoded'] = encoder.fit_transform(df['subject_encoded'].astype(str))
    
    # Feature columns
    feature_cols = ['q1', 'q2', 'q3', 'trend_1_2', 'trend_2_3', 'acceleration',
                    'avg_1_2', 'avg_1_3', 'weighted_avg', 'improving', 'declining',
                    'volatility', 'range', 'subject_encoded', 'grade_level']
    
    X = df[feature_cols].values
    y = df['target'].values
    
    # Scale
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # Split
    X_train, X_val, y_train, y_val = train_test_split(X_scaled, y, test_size=0.2, random_state=42)
    
    print(f"[INFO] Training samples: {len(X_train)}")
    print(f"[INFO] Validation samples: {len(X_val)}")
    
    # Try Random Forest first (often better for this type of data)
    print("[INFO] Training Random Forest...")
    rf_model = RandomForestRegressor(
        n_estimators=200,
        max_depth=10,
        min_samples_split=5,
        random_state=42,
        n_jobs=-1
    )
    rf_model.fit(X_train, y_train)
    rf_pred = rf_model.predict(X_val)
    rf_mae = mean_absolute_error(y_val, rf_pred)
    rf_r2 = r2_score(y_val, rf_pred)
    print(f"  Random Forest - MAE: {rf_mae:.2f}, R²: {rf_r2:.4f}")
    
    # Try XGBoost
    print("[INFO] Training XGBoost...")
    xgb_model = XGBRegressor(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.05,
        random_state=42
    )
    xgb_model.fit(X_train, y_train)
    xgb_pred = xgb_model.predict(X_val)
    xgb_mae = mean_absolute_error(y_val, xgb_pred)
    xgb_r2 = r2_score(y_val, xgb_pred)
    print(f"  XGBoost - MAE: {xgb_mae:.2f}, R²: {xgb_r2:.4f}")
    
    # Use the better model
    if rf_mae < xgb_mae:
        best_model = rf_model
        best_mae = rf_mae
        best_r2 = rf_r2
        model_type = "RandomForest"
    else:
        best_model = xgb_model
        best_mae = xgb_mae
        best_r2 = xgb_r2
        model_type = "XGBoost"
    
    print(f"\n[INFO] Best model: {model_type}")
    print(f"  MAE: {best_mae:.2f} points")
    print(f"  R² Score: {best_r2:.4f}")
    
    # Calculate accuracy
    accuracy = max(0, min(1, 1 - (best_mae / 100)))
    
    # Save model
    version = datetime.now().strftime("%Y%m%d_%H%M%S")
    models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'saved_models')
    os.makedirs(models_dir, exist_ok=True)
    
    model_path = os.path.join(models_dir, f'grade_predictor_v2_{version}.pkl')
    joblib.dump({
        'model': best_model,
        'scaler': scaler,
        'encoder': encoder,
        'feature_names': feature_cols,
        'version': version,
        'accuracy': accuracy,
        'model_type': model_type
    }, model_path)
    
    print(f"\n[INFO] Model saved to {model_path}")
    
    return model_path, version, accuracy, best_mae


def run_training():
    print("=" * 60)
    print("IMPROVED GRADE PREDICTOR V2")
    print("Better feature engineering for grade prediction")
    print("=" * 60)
    
    df = extract_training_data()
    
    if len(df) < 100:
        print(f"[WARNING] Only {len(df)} samples. Need at least 100.")
        return {'success': False, 'error': 'Insufficient data'}
    
    model_path, version, accuracy, mae = train_model(df)
    
    print("\n" + "=" * 60)
    print(f"✅ TRAINING COMPLETE!")
    print(f"Model Version: {version}")
    print(f"Accuracy: {accuracy:.2%}")
    print(f"MAE: {mae:.2f} points")
    print("=" * 60)
    
    return {'success': True, 'model_version': version, 'accuracy': accuracy, 'mae': mae}


if __name__ == "__main__":
    result = run_training()
    print(result)