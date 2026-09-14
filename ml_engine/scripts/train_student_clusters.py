"""
K-Means Student Clustering
Groups students into performance segments for targeted interventions.
"""

import os, sys, django
import pandas as pd
import numpy as np
import joblib
from datetime import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
django.setup()

from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

from enrollment.models import Enrollment
from grades.models import GradeComponent
from attendance.models import AttendanceSummary
from academics.models import SchoolYear


def extract_student_features():
    """Extract features for student clustering"""
    print("[INFO] Extracting student features for clustering...")
    
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    if not current_sy:
        print("[ERROR] No current school year found")
        return pd.DataFrame()
    
    enrollments = Enrollment.objects.filter(
        school_year=current_sy,
        status='Enrolled'
    ).select_related('student', 'section', 'section__grade_level')
    
    student_data = []
    
    for enrollment in enrollments:
        # Get all grade components for this enrollment
        grades = GradeComponent.objects.filter(
            enrollment=enrollment,
            transmuted_grade__isnull=False
        )
        
        if not grades.exists():
            continue
        
        grade_values = [float(g.transmuted_grade) for g in grades]
        
        # Grade features
        avg_grade = np.mean(grade_values)
        min_grade = np.min(grade_values)
        max_grade = np.max(grade_values)
        std_grade = np.std(grade_values) if len(grade_values) > 1 else 0
        grade_range = max_grade - min_grade
        subjects_below_75 = sum(1 for g in grade_values if g < 75)
        subjects_above_90 = sum(1 for g in grade_values if g >= 90)
        
        # Attendance
        attendance_rate = 85  # default
        attendance_summaries = AttendanceSummary.objects.filter(enrollment=enrollment)
        if attendance_summaries.exists():
            rates = [float(s.absence_rate_percent) for s in attendance_summaries if s.absence_rate_percent]
            if rates:
                attendance_rate = 100 - (sum(rates) / len(rates))
        
        # Grade level
        grade_level = 7
        if enrollment.section and enrollment.section.grade_level:
            grade_level = enrollment.section.grade_level.grade_number
        
        features = {
            'student_id': enrollment.student_id,
            'enrollment_id': enrollment.id,
            'student_name': enrollment.student.full_name,
            'avg_grade': round(avg_grade, 2),
            'min_grade': round(min_grade, 2),
            'max_grade': round(max_grade, 2),
            'std_grade': round(std_grade, 2),
            'grade_range': round(grade_range, 2),
            'subjects_below_75': subjects_below_75,
            'subjects_above_90': subjects_above_90,
            'attendance_rate': round(attendance_rate, 2),
            'grade_level': grade_level,
            'total_subjects': len(grade_values),
        }
        
        student_data.append(features)
    
    print(f"[INFO] Extracted features for {len(student_data)} students")
    return pd.DataFrame(student_data)


def find_optimal_clusters(X_scaled, max_k=10):
    """Find optimal number of clusters using elbow + silhouette"""
    n_samples = len(X_scaled)
    max_k = min(max_k, n_samples - 1)
    
    inertias = []
    silhouette_scores = []
    K_range = range(2, max_k + 1)
    
    for k in K_range:
        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = kmeans.fit_predict(X_scaled)
        inertias.append(kmeans.inertia_)
        silhouette_scores.append(silhouette_score(X_scaled, labels))
    
    # Best K = highest silhouette score
    best_k = K_range[np.argmax(silhouette_scores)]
    
    print(f"[INFO] Optimal clusters (silhouette): {best_k}")
    print(f"[INFO] Silhouette scores: {dict(zip(K_range, [round(s, 3) for s in silhouette_scores]))}")
    
    return best_k


def label_clusters(df, feature_cols):
    """Auto-label clusters based on centroid characteristics"""
    cluster_labels = {}
    
    for cluster_id in sorted(df['cluster'].unique()):
        cluster_data = df[df['cluster'] == cluster_id]
        avg = cluster_data['avg_grade'].mean()
        att = cluster_data['attendance_rate'].mean()
        failing = cluster_data['subjects_below_75'].mean()
        std = cluster_data['std_grade'].mean()
        
        if avg >= 90 and failing < 1:
            label = "High Performers"
            emoji = "🌟"
        elif avg >= 85 and failing < 1:
            label = "Consistent Achievers"
            emoji = "✅"
        elif avg >= 80 and failing < 2 and att >= 85:
            label = "Steady Performers"
            emoji = "👍"
        elif avg >= 75 and att >= 80:
            label = "Borderline Students"
            emoji = "⚠️"
        elif failing >= 3:
            label = "At-Risk (Multiple Failures)"
            emoji = "🚨"
        elif att < 75:
            label = "Attendance Issues"
            emoji = "🏃"
        elif std > 8:
            label = "Inconsistent Performers"
            emoji = "📊"
        else:
            label = "Needs Support"
            emoji = "💡"
        
        cluster_labels[cluster_id] = f"{emoji} {label}"
    
    return cluster_labels


def train_model(df):
    """Train K-Means clustering model"""
    if df.empty:
        return None, None, 0, {}
    
    feature_cols = [
        'avg_grade', 'min_grade', 'max_grade', 'std_grade',
        'grade_range', 'subjects_below_75', 'subjects_above_90',
        'attendance_rate', 'grade_level', 'total_subjects'
    ]
    
    X = df[feature_cols].values
    
    # Scale
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # Find optimal K
    optimal_k = find_optimal_clusters(X_scaled)
    
    # Train
    kmeans = KMeans(n_clusters=optimal_k, random_state=42, n_init=10)
    df['cluster'] = kmeans.fit_predict(X_scaled)
    
    # Label clusters
    cluster_labels = label_clusters(df, feature_cols)
    df['cluster_label'] = df['cluster'].map(cluster_labels)
    
    # Print cluster profiles
    print("\n" + "=" * 60)
    print("CLUSTER PROFILES")
    print("=" * 60)
    
    for cluster_id in sorted(df['cluster'].unique()):
        cluster_data = df[df['cluster'] == cluster_id]
        count = len(cluster_data)
        pct = (count / len(df)) * 100
        
        print(f"\n  {cluster_labels[cluster_id]}")
        print(f"  Students: {count} ({pct:.1f}%)")
        print(f"  Average Grade: {cluster_data['avg_grade'].mean():.1f}%")
        print(f"  Min Grade: {cluster_data['min_grade'].mean():.1f}%")
        print(f"  Attendance: {cluster_data['attendance_rate'].mean():.1f}%")
        print(f"  Subjects Below 75: {cluster_data['subjects_below_75'].mean():.1f}")
        print(f"  Grade Volatility (std): {cluster_data['std_grade'].mean():.1f}")
    
    # Save model
    version = datetime.now().strftime("%Y%m%d_%H%M%S")
    models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'saved_models')
    os.makedirs(models_dir, exist_ok=True)
    
    model_path = os.path.join(models_dir, f'student_clusters_{version}.pkl')
    joblib.dump({
        'model': kmeans,
        'scaler': scaler,
        'feature_names': feature_cols,
        'cluster_labels': cluster_labels,
        'n_clusters': optimal_k,
        'version': version,
    }, model_path)
    
    print(f"\n[INFO] Model saved to {model_path}")
    
    return model_path, optimal_k, cluster_labels


def run_training():
    """Main training function"""
    print("=" * 60)
    print("K-MEANS STUDENT CLUSTERING")
    print("=" * 60)
    
    df = extract_student_features()
    
    if len(df) < 10:
        print(f"[ERROR] Only {len(df)} students. Need at least 10.")
        return {'success': False, 'error': f'Insufficient data: {len(df)} students'}
    
    model_path, n_clusters, cluster_labels = train_model(df)
    
    print("\n" + "=" * 60)
    print("✅ CLUSTERING COMPLETE!")
    print(f"   Clusters: {n_clusters}")
    print(f"   Students analyzed: {len(df)}")
    print("=" * 60)
    
    return {
        'success': True,
        'n_clusters': n_clusters,
        'samples': len(df),
        'clusters': cluster_labels
    }


if __name__ == "__main__":
    result = run_training()
    print(f"\nFinal Result: {result}")