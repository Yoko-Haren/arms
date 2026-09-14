# ml_engine/management/commands/train_models.py
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Train ML models for grade prediction, risk classification, and student clustering'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--model',
            type=str,
            choices=['grade', 'risk', 'cluster', 'both', 'all'],
            default='both',
            help='Which model to train (both = grade + risk, all = grade + risk + cluster)'
        )
    
    def handle(self, *args, **options):
        model_type = options['model']
        
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('STARTING ML TRAINING'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        
        results = {}
        
        # Grade Predictor (XGBoost)
        if model_type in ['grade', 'both', 'all']:
            self.stdout.write('\nTraining Grade Predictor (XGBoost)...')
            try:
                from ml_engine.scripts.train_grade_predictor import run_training as train_grade
                result = train_grade()
                results['grade'] = result
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  Grade training failed: {e}'))
                results['grade'] = {'success': False, 'error': str(e)}
        
        # Risk Classifier (Random Forest)
        if model_type in ['risk', 'both', 'all']:
            self.stdout.write('\nTraining Risk Classifier (Random Forest)...')
            try:
                from ml_engine.scripts.train_risk_classifier import run_training as train_risk
                result = train_risk()
                results['risk'] = result
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  Risk training failed: {e}'))
                results['risk'] = {'success': False, 'error': str(e)}
        
        # Student Clusters (K-Means)
        if model_type in ['cluster', 'all']:
            self.stdout.write('\n🔍 Training Student Clusters (K-Means)...')
            try:
                from ml_engine.scripts.train_student_clusters import run_training as train_cluster
                result = train_cluster()
                results['cluster'] = result
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  Cluster training failed: {e}'))
                results['cluster'] = {'success': False, 'error': str(e)}
        
        # Summary
        self.stdout.write('\n' + self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('TRAINING COMPLETE!'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        
        for name, result in results.items():
            if result.get('success'):
                if name == 'cluster':
                    self.stdout.write(self.style.SUCCESS(
                        f"  {name}: {result.get('n_clusters', '?')} clusters ({result.get('samples', 0)} students)"
                    ))
                else:
                    acc = result.get('accuracy', 0)
                    if isinstance(acc, float):
                        self.stdout.write(self.style.SUCCESS(
                            f"  {name}: v{result.get('model_version', '?')} ({acc:.2%} accuracy)"
                        ))
                    else:
                        self.stdout.write(self.style.SUCCESS(
                            f"  {name}: v{result.get('model_version', '?')}"
                        ))
            else:
                self.stdout.write(self.style.ERROR(
                    f"  {name}: FAILED - {result.get('error', 'Unknown error')}"
                ))
        
        # Usage hint
        if results.get('cluster', {}).get('success'):
            self.stdout.write('\n' + self.style.WARNING(
                'Restart your server for the new cluster model to take effect.'
            ))