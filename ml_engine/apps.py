from django.apps import AppConfig
import os
import logging

logger = logging.getLogger(__name__)

class MlEngineConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ml_engine'
    
    # Class-level variables to hold loaded models
    grade_model = None
    risk_model = None
    cluster_model = None
    models_loaded = False
    
    def ready(self):
        """
        Load ML models ONCE when Django starts.
        This prevents reloading on every request.
        """
        # Prevent double-loading in development with auto-reload
        if os.environ.get('RUN_MAIN') == 'true' or not os.environ.get('RUN_MAIN'):
            self.load_models()
    
    @classmethod
    def load_models(cls):
        """Load all ML models into memory once."""
        if cls.models_loaded:
            logger.info("[ML] Models already loaded, skipping.")
            return
        
        import joblib
        from pathlib import Path
        
        base_path = Path(__file__).resolve().parent / 'saved_models'
        
        try:
            # Load Grade Predictor
            grade_path = base_path / 'grade_predictor_v2_20260604_023347.pkl'
            if grade_path.exists():
                cls.grade_model = joblib.load(grade_path)
                logger.info(f"[ML] Grade model loaded! Version: 20260604_023347")
            else:
                logger.warning(f"[ML] Grade model not found at: {grade_path}")
            
            # Load Risk Classifier
            risk_path = base_path / 'risk_classifier_20260607_204647.pkl'
            if risk_path.exists():
                cls.risk_model = joblib.load(risk_path)
                logger.info(f"[ML] Risk model loaded! Version: 20260607_204647")
            else:
                logger.warning(f"[ML] Risk model not found at: {risk_path}")
            
            # Load Cluster Model
            cluster_path = base_path / 'student_clusters_20260607_204652.pkl'
            if cluster_path.exists():
                cls.cluster_model = joblib.load(cluster_path)
                logger.info(f"[ML] Cluster model loaded! Clusters: {cls.cluster_model.n_clusters if hasattr(cls.cluster_model, 'n_clusters') else 'N/A'}")
            else:
                logger.warning(f"[ML] Cluster model not found at: {cluster_path}")
            
            cls.models_loaded = True
            logger.info("[ML] ✅ All models loaded successfully!")
            
        except Exception as e:
            logger.error(f"[ML] ❌ Failed to load models: {e}")
            cls.models_loaded = False
    
    @classmethod
    def get_grade_model(cls):
        """Safe getter for grade model."""
        if not cls.models_loaded:
            cls.load_models()
        return cls.grade_model
    
    @classmethod
    def get_risk_model(cls):
        """Safe getter for risk model."""
        if not cls.models_loaded:
            cls.load_models()
        return cls.risk_model
    
    @classmethod
    def get_cluster_model(cls):
        """Safe getter for cluster model."""
        if not cls.models_loaded:
            cls.load_models()
        return cls.cluster_model