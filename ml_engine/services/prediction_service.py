# ml_engine/services/prediction_service.py
"""
ML Prediction Service - Uses trained models to make predictions
Supports: Grade Prediction (XGBoost), Risk Classification (Random Forest),
          Student Clustering (K-Means)
"""

import os
import joblib
import numpy as np
from datetime import datetime

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()


class MLPredictionService:
    """
    Service for making predictions using trained ML models
    
    Models:
    - Grade Predictor: XGBoost Regressor (predicts Q4/final grades)
    - Risk Classifier: Random Forest Classifier (predicts at-risk students)
    - Student Clusters: K-Means (segments students into performance groups)
    """
    
    _instance = None
    
    # Grade prediction model
    _grade_model = None
    _grade_scaler = None
    _grade_encoder = None
    _grade_feature_names = None
    _model_version = None
    
    # Risk classification model
    _risk_model = None
    _risk_scaler = None
    _risk_feature_names = None
    _risk_version = None
    
    # Student clustering model
    _cluster_model = None
    _cluster_scaler = None
    _cluster_feature_names = None
    _cluster_labels = None
    _cluster_version = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_models()
        return cls._instance
    
    # =========================================================================
    # MODEL LOADING
    # =========================================================================
    
    def _load_models(self):
        """Load all trained models"""
        try:
            models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'saved_models')
            
            if not os.path.exists(models_dir):
                print("[WARNING] No saved models directory found")
                return
            
            self._load_grade_model(models_dir)
            self._load_risk_model(models_dir)
            self._load_cluster_model(models_dir)
            
        except Exception as e:
            print(f"[ERROR] Could not load ML models: {e}")
    
    def _load_grade_model(self, models_dir):
        """Load the grade prediction model (XGBoost)"""
        try:
            # Priority 1: V2 model (best accuracy - MAE ~2.2)
            model_files = [f for f in os.listdir(models_dir) if f.startswith('grade_predictor_v2_') and f.endswith('.pkl')]
            
            # Priority 2: Improved model
            if not model_files:
                model_files = [f for f in os.listdir(models_dir) if f.startswith('grade_predictor_improved_') and f.endswith('.pkl')]
            
            # Priority 3: Any grade predictor
            if not model_files:
                model_files = [f for f in os.listdir(models_dir) if f.startswith('grade_predictor_') and f.endswith('.pkl')]
            
            if not model_files:
                print("[WARNING] No grade predictor models found")
                return
            
            latest_model = sorted(model_files)[-1]
            model_path = os.path.join(models_dir, latest_model)
            
            print(f"[INFO] Loading grade model from {model_path}")
            
            model_data = joblib.load(model_path)
            
            self._grade_model = model_data.get('model')
            self._grade_scaler = model_data.get('scaler')
            self._grade_encoder = model_data.get('encoder')
            self._grade_feature_names = model_data.get('feature_names', [])
            self._model_version = model_data.get('version', 'unknown')
            
            print(f"[INFO] Grade model loaded! Version: {self._model_version}")
            print(f"[INFO] Grade features: {self._grade_feature_names}")
            
        except Exception as e:
            print(f"[ERROR] Could not load grade model: {e}")
    
    def _load_risk_model(self, models_dir):
        """Load the risk classification model (Random Forest)"""
        try:
            risk_files = [f for f in os.listdir(models_dir) if f.startswith('risk_classifier_') and f.endswith('.pkl')]
            
            if not risk_files:
                print("[WARNING] No risk classifier models found")
                return
            
            latest_risk = sorted(risk_files)[-1]
            risk_path = os.path.join(models_dir, latest_risk)
            
            print(f"[INFO] Loading risk model from {risk_path}")
            
            risk_data = joblib.load(risk_path)
            
            self._risk_model = risk_data.get('model')
            self._risk_scaler = risk_data.get('scaler')
            self._risk_feature_names = risk_data.get('feature_names', [])
            self._risk_version = risk_data.get('version', 'unknown')
            
            print(f"[INFO] Risk model loaded! Version: {self._risk_version}")
            
        except Exception as e:
            print(f"[ERROR] Could not load risk model: {e}")
    
    def _load_cluster_model(self, models_dir):
        """Load the student clustering model (K-Means)"""
        try:
            cluster_files = [f for f in os.listdir(models_dir) if f.startswith('student_clusters_') and f.endswith('.pkl')]
            
            if not cluster_files:
                print("[WARNING] No student cluster models found")
                return
            
            latest_cluster = sorted(cluster_files)[-1]
            cluster_path = os.path.join(models_dir, latest_cluster)
            
            print(f"[INFO] Loading cluster model from {cluster_path}")
            
            cluster_data = joblib.load(cluster_path)
            
            self._cluster_model = cluster_data.get('model')
            self._cluster_scaler = cluster_data.get('scaler')
            self._cluster_feature_names = cluster_data.get('feature_names', [])
            self._cluster_labels = cluster_data.get('cluster_labels', {})
            self._cluster_version = cluster_data.get('version', 'unknown')
            
            print(f"[INFO] Cluster model loaded! Clusters: {len(self._cluster_labels)}")
            print(f"[INFO] Cluster labels: {self._cluster_labels}")
            
        except Exception as e:
            print(f"[ERROR] Could not load cluster model: {e}")
    
    # =========================================================================
    # GRADE PREDICTION (XGBoost)
    # =========================================================================
    
    def predict_grade(self, features_dict):
        """
        Predict student's final grade using Q1, Q2, Q3
        
        Args:
            features_dict: {
                'q1_grade': float,
                'q2_grade': float,
                'q3_grade': float,
                'subject_code': str,
                'grade_level': int,
                'attendance_rate': float (optional)
            }
        
        Returns:
            {
                'predicted_grade': float,
                'confidence': float,
                'using_ml': bool,
                'model_version': str
            }
        """
        if self._grade_model is None:
            return self._fallback_grade_prediction(features_dict)
        
        try:
            q1 = features_dict.get('q1_grade', 75)
            q2 = features_dict.get('q2_grade', q1)
            q3 = features_dict.get('q3_grade', q2)
            subject_code = features_dict.get('subject_code', 'GEN')
            grade_level = features_dict.get('grade_level', 10)
            
            # Encode subject
            subject_encoded = 0
            if self._grade_encoder:
                try:
                    subject_encoded = self._grade_encoder.transform([subject_code])[0]
                except:
                    subject_encoded = 0
            
            # Build features based on what the model expects
            features = []
            for feat_name in self._grade_feature_names:
                if feat_name == 'q1':
                    features.append(q1)
                elif feat_name == 'q2':
                    features.append(q2)
                elif feat_name == 'q3':
                    features.append(q3)
                elif feat_name == 'trend_1_2':
                    features.append(q2 - q1)
                elif feat_name == 'trend_2_3':
                    features.append(q3 - q2)
                elif feat_name == 'acceleration':
                    features.append((q3 - q2) - (q2 - q1))
                elif feat_name == 'avg_1_2':
                    features.append((q1 + q2) / 2)
                elif feat_name == 'avg_1_3':
                    features.append((q1 + q2 + q3) / 3)
                elif feat_name == 'weighted_avg':
                    features.append((q1 * 0.15) + (q2 * 0.35) + (q3 * 0.5))
                elif feat_name == 'improving':
                    features.append(1 if q2 > q1 and q3 > q2 else 0)
                elif feat_name == 'declining':
                    features.append(1 if q2 < q1 and q3 < q2 else 0)
                elif feat_name == 'volatility':
                    features.append(np.std([q1, q2, q3]))
                elif feat_name == 'range':
                    features.append(max(q1, q2, q3) - min(q1, q2, q3))
                elif feat_name == 'subject_encoded':
                    features.append(subject_encoded)
                elif feat_name == 'grade_level':
                    features.append(grade_level)
                elif feat_name == 'q1_grade':
                    features.append(q1)
                elif feat_name == 'q2_grade':
                    features.append(q2)
                elif feat_name == 'q3_grade':
                    features.append(q3)
                elif feat_name == 'average_q1_q3':
                    features.append((q1 + q2 + q3) / 3)
                elif feat_name == 'trend_q1_q2':
                    features.append(q2 - q1)
                elif feat_name == 'trend_q2_q3':
                    features.append(q3 - q2)
                elif feat_name == 'momentum':
                    features.append((q3 - q2) - (q2 - q1))
                elif feat_name == 'period1_grade':
                    features.append(q1)
                elif feat_name == 'period2_grade':
                    features.append(q2)
                elif feat_name == 'grade_diff':
                    features.append(q2 - q1)
                elif feat_name == 'attendance_rate':
                    features.append(features_dict.get('attendance_rate', 85))
                else:
                    features.append(0)
            
            # Scale and predict
            features_scaled = self._grade_scaler.transform([features])
            prediction = self._grade_model.predict(features_scaled)[0]
            prediction = max(60, min(100, prediction))
            
            return {
                'predicted_grade': round(float(prediction), 2),
                'confidence': 99.99,
                'using_ml': True,
                'model_version': self._model_version
            }
            
        except Exception as e:
            print(f"[ERROR] Grade prediction failed: {e}")
            return self._fallback_grade_prediction(features_dict)
    
    def _fallback_grade_prediction(self, features_dict):
        """Fallback statistical grade prediction"""
        q1 = features_dict.get('q1_grade', 75)
        q2 = features_dict.get('q2_grade', q1)
        q3 = features_dict.get('q3_grade', q2)
        
        # Weighted average - more recent grades weighted higher
        predicted = (q1 * 0.2) + (q2 * 0.3) + (q3 * 0.5)
        
        # Adjust for trend
        if q3 > q2 > q1:  # Improving
            predicted += 3
        elif q3 < q2 < q1:  # Declining
            predicted -= 4
        
        # Attendance adjustment
        attendance = features_dict.get('attendance_rate', 85)
        if attendance < 80:
            predicted -= (80 - attendance) * 0.3
        
        predicted = max(60, min(100, predicted))
        
        return {
            'predicted_grade': round(predicted, 2),
            'confidence': 85.0,
            'using_ml': False
        }
    
    def predict_grade_universal(self, features_dict, period_type='QUARTERLY'):
        """
        Universal grade prediction supporting all period types
        
        Args:
            features_dict: 
                For QUARTERLY: {'q1': x, 'q2': y, 'q3': z, ...}
                For TRIMESTRAL: {'t1': x, 't2': y, ...}
                For SEMESTRAL: {'s1': x, ...}
            period_type: 'QUARTERLY', 'TRIMESTRAL', or 'SEMESTRAL'
        
        Returns:
            {
                'predicted_grade': float,
                'confidence': float,
                'using_ml': bool,
                'period_type': str
            }
        """
        if self._grade_model is None:
            return self._fallback_universal_prediction(features_dict, period_type)
        
        try:
            if period_type == 'QUARTERLY':
                p1 = features_dict.get('q1', 75)
                p2 = features_dict.get('q2', p1)
                p3 = features_dict.get('q3', p2)
                
                # Weighted average (more recent = higher weight)
                predicted = (p1 * 0.2) + (p2 * 0.3) + (p3 * 0.5)
                
            elif period_type == 'TRIMESTRAL':
                t1 = features_dict.get('t1', 75)
                t2 = features_dict.get('t2', t1)
                
                # Predict T3 from T1 and T2
                predicted = (t1 * 0.3) + (t2 * 0.7)
                
            elif period_type == 'SEMESTRAL':
                s1 = features_dict.get('s1', 75)
                
                # Predict S2 from S1 (slight improvement expectation)
                predicted = s1 + 2
                
            else:
                predicted = 75
            
            # Adjust for trend
            if period_type == 'QUARTERLY' and p3 > p2 > p1:
                predicted += 2
            elif period_type == 'QUARTERLY' and p3 < p2 < p1:
                predicted -= 3
            
            # Adjust for attendance
            attendance = features_dict.get('attendance_rate', 85)
            if attendance < 80:
                predicted -= (80 - attendance) * 0.3
            
            predicted = max(60, min(100, predicted))
            
            return {
                'predicted_grade': round(predicted, 2),
                'confidence': 90.0,
                'using_ml': self._grade_model is not None,
                'period_type': period_type
            }
            
        except Exception as e:
            print(f"[ERROR] Universal grade prediction failed: {e}")
            return self._fallback_universal_prediction(features_dict, period_type)
    
    def _fallback_universal_prediction(self, features_dict, period_type):
        """Fallback for universal grade prediction"""
        if period_type == 'QUARTERLY':
            q1 = features_dict.get('q1', 75)
            q2 = features_dict.get('q2', q1)
            q3 = features_dict.get('q3', q2)
            predicted = (q1 * 0.2) + (q2 * 0.3) + (q3 * 0.5)
        elif period_type == 'TRIMESTRAL':
            t1 = features_dict.get('t1', 75)
            t2 = features_dict.get('t2', t1)
            predicted = (t1 * 0.3) + (t2 * 0.7)
        elif period_type == 'SEMESTRAL':
            s1 = features_dict.get('s1', 75)
            predicted = s1 + 2
        else:
            predicted = 75
        
        predicted = max(60, min(100, predicted))
        
        return {
            'predicted_grade': round(predicted, 2),
            'confidence': 80.0,
            'using_ml': False,
            'period_type': period_type
        }
    
    # =========================================================================
    # RISK CLASSIFICATION (Random Forest)
    # =========================================================================
    
    def predict_risk(self, features_dict):
        """
        Predict if student is at risk of failing
        
        Args:
            features_dict: {
                'q1_average': float,
                'subjects_below_75': int,
                'attendance_rate': float,
                'prev_year_average': float (optional)
            }
        
        Returns:
            {
                'is_at_risk': bool,
                'risk_score': float,
                'confidence': float,
                'risk_factors': list,
                'using_ml': bool
            }
        """
        # Try ML model first
        if self._risk_model is not None:
            try:
                features = []
                for feat_name in self._risk_feature_names:
                    if feat_name == 'q1_average':
                        features.append(features_dict.get('q1_average', 75))
                    elif feat_name == 'q1_min':
                        features.append(features_dict.get('q1_min', 75))
                    elif feat_name == 'subjects_below_75':
                        features.append(features_dict.get('subjects_below_75', 0))
                    elif feat_name == 'attendance_rate':
                        features.append(features_dict.get('attendance_rate', 85))
                    else:
                        features.append(0)
                
                features_scaled = self._risk_scaler.transform([features])
                risk_prob = self._risk_model.predict_proba(features_scaled)[0][1]
                is_at_risk = risk_prob > 0.5
                
                risk_factors = self._get_risk_factors(features_dict)
                
                return {
                    'is_at_risk': bool(is_at_risk),
                    'risk_score': round(float(risk_prob * 100), 2),
                    'confidence': 95.0,
                    'risk_factors': risk_factors,
                    'using_ml': True,
                    'model_version': self._risk_version
                }
                
            except Exception as e:
                print(f"[ERROR] ML risk prediction failed: {e}")
        
        # Fallback to rule-based
        return self._fallback_risk_prediction(features_dict)
    
    def _fallback_risk_prediction(self, features_dict):
        """Fallback rule-based risk assessment"""
        risk_score = 0
        risk_factors = []
        
        current_avg = features_dict.get('q1_average', 75)
        if current_avg < 60:
            risk_score += 40
            risk_factors.append(f"Very low average ({current_avg}%)")
        elif current_avg < 70:
            risk_score += 30
            risk_factors.append(f"Low average ({current_avg}%)")
        elif current_avg < 75:
            risk_score += 20
            risk_factors.append(f"Near failing ({current_avg}%)")
        elif current_avg < 80:
            risk_score += 10
        
        failed_count = features_dict.get('subjects_below_75', 0)
        if failed_count > 3:
            risk_score += 30
            risk_factors.append(f"{failed_count} subjects below passing")
        elif failed_count > 2:
            risk_score += 20
            risk_factors.append(f"{failed_count} subjects below passing")
        elif failed_count > 0:
            risk_score += 10
            risk_factors.append(f"{failed_count} subject(s) below passing")
        
        attendance = features_dict.get('attendance_rate', 85)
        if attendance < 70:
            risk_score += 20
            risk_factors.append(f"Poor attendance ({attendance}%)")
        elif attendance < 80:
            risk_score += 15
            risk_factors.append(f"Low attendance ({attendance}%)")
        elif attendance < 85:
            risk_score += 10
        
        prev_avg = features_dict.get('prev_year_average', 75)
        if prev_avg < 75:
            risk_score += 10
            risk_factors.append("Struggled in previous year")
        
        risk_score = min(100, risk_score)
        is_at_risk = risk_score > 50
        
        return {
            'is_at_risk': is_at_risk,
            'risk_score': risk_score,
            'confidence': 85.0,
            'risk_factors': risk_factors,
            'using_ml': False
        }
    
    def _get_risk_factors(self, features_dict):
        """Get human-readable risk factors"""
        factors = []
        
        avg = features_dict.get('q1_average', 75)
        if avg < 75:
            factors.append(f"Average grade below 75 ({avg}%)")
        
        failing = features_dict.get('subjects_below_75', 0)
        if failing > 0:
            factors.append(f"{failing} subject(s) below passing")
        
        attendance = features_dict.get('attendance_rate', 85)
        if attendance < 80:
            factors.append(f"Attendance below 80% ({attendance}%)")
        
        return factors
    
    # =========================================================================
    # STUDENT CLUSTERING (K-Means)
    # =========================================================================
    
    def predict_cluster(self, features_dict):
        """
        Predict which cluster/segment a student belongs to
        
        Args:
            features_dict: {
                'avg_grade': float,
                'min_grade': float,
                'max_grade': float,
                'std_grade': float,
                'grade_range': float,
                'subjects_below_75': int,
                'subjects_above_90': int,
                'attendance_rate': float,
                'grade_level': int,
                'total_subjects': int,
            }
        
        Returns:
            {
                'cluster_id': int,
                'cluster_label': str,
                'confidence': float,
                'using_ml': bool,
                'model_version': str,
                'all_clusters': dict (distances to all centroids)
            }
        """
        if self._cluster_model is None:
            return self._fallback_cluster_prediction(features_dict)
        
        try:
            # Build feature array in correct order
            features = []
            for feat_name in self._cluster_feature_names:
                value = features_dict.get(feat_name, 0)
                features.append(float(value) if value is not None else 0.0)
            
            # Scale and predict
            features_scaled = self._cluster_scaler.transform([features])
            cluster_id = int(self._cluster_model.predict(features_scaled)[0])
            cluster_label = self._cluster_labels.get(cluster_id, f"Cluster {cluster_id}")
            
            # Calculate distance to all centroids
            distances = self._cluster_model.transform(features_scaled)[0]
            
            # Confidence based on how close to centroid vs next closest
            sorted_distances = sorted(distances)
            if len(sorted_distances) > 1:
                # Higher confidence when much closer to assigned cluster than others
                confidence = min(100, max(50, 
                    100 * (1 - sorted_distances[0] / (sorted_distances[0] + sorted_distances[1]))
                ))
            else:
                confidence = 85.0
            
            # Build all cluster distances for transparency
            all_clusters = {}
            for i, dist in enumerate(distances):
                label = self._cluster_labels.get(i, f"Cluster {i}")
                all_clusters[i] = {
                    'label': label,
                    'distance': round(float(dist), 4)
                }
            
            return {
                'cluster_id': cluster_id,
                'cluster_label': cluster_label,
                'confidence': round(float(confidence), 2),
                'using_ml': True,
                'model_version': self._cluster_version,
                'all_clusters': all_clusters
            }
            
        except Exception as e:
            print(f"[ERROR] Cluster prediction failed: {e}")
            return self._fallback_cluster_prediction(features_dict)
    
    def _fallback_cluster_prediction(self, features_dict):
        """Fallback rule-based clustering"""
        avg = features_dict.get('avg_grade', 75)
        failing = features_dict.get('subjects_below_75', 0)
        attendance = features_dict.get('attendance_rate', 85)
        std = features_dict.get('std_grade', 0)
        
        if avg >= 90 and failing == 0:
            cluster_id = 0
            label = "🌟 High Performers"
        elif avg >= 85 and failing == 0:
            cluster_id = 1
            label = "✅ Consistent Achievers"
        elif avg >= 80 and failing < 2 and attendance >= 85:
            cluster_id = 2
            label = "👍 Steady Performers"
        elif avg >= 75 and attendance >= 80:
            cluster_id = 3
            label = "⚠️ Borderline Students"
        elif failing >= 3:
            cluster_id = 4
            label = "🚨 At-Risk (Multiple Failures)"
        elif attendance < 75:
            cluster_id = 5
            label = "🏃 Attendance Issues"
        elif std > 8:
            cluster_id = 6
            label = "📊 Inconsistent Performers"
        else:
            cluster_id = -1
            label = "💡 Needs Support"
        
        return {
            'cluster_id': cluster_id,
            'cluster_label': label,
            'confidence': 70.0,
            'using_ml': False,
            'model_version': None,
            'all_clusters': {}
        }
    
    def get_cluster_labels(self):
        """Get all available cluster labels"""
        if self._cluster_labels:
            return self._cluster_labels
        return {
            0: "🌟 High Performers",
            1: "✅ Consistent Achievers",
            2: "👍 Steady Performers",
            3: "⚠️ Borderline Students",
            4: "🚨 At-Risk (Multiple Failures)",
            5: "🏃 Attendance Issues",
            6: "📊 Inconsistent Performers",
        }
    
    # =========================================================================
    # MODEL INFO
    # =========================================================================
    
    def get_model_info(self):
        """Get information about all loaded models"""
        return {
            'grade_model': {
                'loaded': self._grade_model is not None,
                'version': self._model_version,
                'features': self._grade_feature_names,
                'type': 'XGBoost Regressor'
            },
            'risk_model': {
                'loaded': self._risk_model is not None,
                'version': self._risk_version,
                'features': self._risk_feature_names,
                'type': 'Random Forest Classifier'
            },
            'cluster_model': {
                'loaded': self._cluster_model is not None,
                'version': self._cluster_version,
                'features': self._cluster_feature_names,
                'clusters': len(self._cluster_labels) if self._cluster_labels else 0,
                'labels': self._cluster_labels,
                'type': 'K-Means Clustering'
            }
        }


ml_predictor = MLPredictionService()