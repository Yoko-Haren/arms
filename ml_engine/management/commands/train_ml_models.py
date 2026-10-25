# ml_engine/management/commands/train_models.py
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = ('Train ML models. The default, forecast, is the grade forecaster every School Head page uses '
            '(ml_engine/forecast.py); grade, risk and cluster are the earlier experiments.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--model',
            type=str,
            choices=['forecast', 'grade', 'risk', 'cluster', 'both', 'all'],
            default='forecast',
            help='Which model to train (forecast = the grade forecaster; both = grade + risk; all = every model)'
        )
        parser.add_argument('--record', action='store_true',
                            help='Record how the forecaster run ended in the status the Admin Portal shows (ml_engine/training.py)')

    def handle(self, *args, **options):
        model_type = options['model']

        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('STARTING ML TRAINING'))
        self.stdout.write(self.style.SUCCESS('=' * 60))

        results = {}

        # Grade forecaster (XGBoost, every period ahead, scored on held-out periods)
        if model_type in ['forecast', 'all']:
            self.stdout.write('\nTraining the grade forecaster (XGBoost)...')
            try:
                from ml_engine.forecast import train as train_forecast
                meta = train_forecast(log=self.stdout.write)
                latest = meta['evaluation'][-1]
                results['forecast'] = {'success': True, 'model_version': meta['version'], 'samples': meta['samples'],
                                       'mae': latest['model']['mae'], 'split': latest['split']}
                if options['record']:
                    from ml_engine import training
                    training.finish(True, f'Version {meta["version"]}: {meta["samples"]:,} records, off by '
                                          f'{latest["model"]["mae"]:.1f} points on average for {latest["split"]}.')
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  Forecaster training failed: {e}'))
                results['forecast'] = {'success': False, 'error': str(e)}
                if options['record']:
                    from ml_engine import training
                    training.finish(False, str(e)[:300])

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
                if name == 'forecast':
                    self.stdout.write(self.style.SUCCESS(
                        f"  forecast: v{result['model_version']} trained on {result['samples']:,} samples; "
                        f"off by {result['mae']:.2f} points on average for {result['split']}"
                    ))
                elif name == 'cluster':
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