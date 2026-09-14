"""
Poro AI — Anomaly Detection Engine for Formify LIS
Detects suspicious patterns in grades, logins, and data modifications.
SQLite-compatible version.
"""

from datetime import timedelta
from django.utils import timezone
from django.db.models import Count
from django.contrib.auth.models import User

from audit.models import AnomalyDetectionEvent
from grades.models import GradeChangeLog
from accounts.models import LoginAttempt


class PoroDetector:
    """Main anomaly detection engine."""

    MODEL_VERSION = 'v1.0.0'
    CONFIDENCE_THRESHOLD = 0.65

    @classmethod
    def run_all_checks(cls):
        """Run all detection checks and return count of new anomalies."""
        count = 0
        count += cls.check_grade_anomalies()
        count += cls.check_login_anomalies()
        count += cls.check_off_hours_access()
        return count

    # ── 1. Grade Change Anomalies ──
    @classmethod
    def check_grade_anomalies(cls):
        """Detect suspicious grade modifications."""
        new_anomalies = 0
        recent = timezone.now() - timedelta(hours=24)

        # Rapid grade changes by a single user
        changes = GradeChangeLog.objects.filter(
            created_at__gte=recent
        ).values('changed_by').annotate(
            count=Count('id')
        ).filter(count__gte=5)

        for entry in changes:
            if not entry['changed_by']:
                continue
            user = User.objects.get(pk=entry['changed_by'])
            count = entry['count']
            confidence = min(0.95, 0.6 + (count * 0.05))

            if confidence >= cls.CONFIDENCE_THRESHOLD:
                # Check if similar anomaly already exists
                exists = AnomalyDetectionEvent.objects.filter(
                    anomaly_type='Unusual_Grade_Change',
                    is_investigated=False,
                    created_at__gte=recent,
                ).exists()

                if not exists:
                    AnomalyDetectionEvent.objects.create(
                        anomaly_type='Unusual_Grade_Change',
                        severity='High' if count >= 10 else 'Medium',
                        confidence_score=confidence,
                        model_version=cls.MODEL_VERSION,
                        details_json={
                            'user_name': user.get_full_name() or user.username,
                            'change_count': count,
                            'timeframe': '24 hours',
                            'note': f'{count} grade changes detected',
                        },
                    )
                    new_anomalies += 1

        # Off-hours grade changes
        off_hour_count = GradeChangeLog.objects.filter(
            created_at__gte=recent,
            created_at__hour__gte=20,
        ).count() + GradeChangeLog.objects.filter(
            created_at__gte=recent,
            created_at__hour__lte=6,
        ).count()

        if off_hour_count >= 3:
            confidence = min(0.85, 0.55 + (off_hour_count * 0.08))
            if confidence >= cls.CONFIDENCE_THRESHOLD:
                exists = AnomalyDetectionEvent.objects.filter(
                    anomaly_type='Unusual_Grade_Change',
                    is_investigated=False,
                    created_at__gte=recent,
                ).count()
                if exists < 2:
                    AnomalyDetectionEvent.objects.create(
                        anomaly_type='Unusual_Grade_Change',
                        severity='Low',
                        confidence_score=confidence,
                        model_version=cls.MODEL_VERSION,
                        details_json={
                            'change_count': off_hour_count,
                            'timeframe': 'off-hours (8PM-6AM)',
                            'note': 'Grade changes outside working hours',
                        },
                    )
                    new_anomalies += 1

        return new_anomalies

    # ── 2. Login Anomalies ──
    @classmethod
    def check_login_anomalies(cls):
        """Detect suspicious login patterns."""
        new_anomalies = 0
        recent = timezone.now() - timedelta(hours=1)

        failed = LoginAttempt.objects.filter(
            attempted_at__gte=recent,
            attempt_result__startswith='FAILED'
        ).values('ip_address').annotate(
            count=Count('id')
        ).filter(count__gte=5)

        for entry in failed:
            ip = entry['ip_address']
            count = entry['count']
            confidence = min(0.98, 0.5 + (count * 0.08))

            if confidence >= cls.CONFIDENCE_THRESHOLD:
                exists = AnomalyDetectionEvent.objects.filter(
                    anomaly_type='Suspicious_Login',
                    is_investigated=False,
                    created_at__gte=recent,
                ).exists()

                if not exists:
                    AnomalyDetectionEvent.objects.create(
                        anomaly_type='Suspicious_Login',
                        severity='Critical' if count >= 10 else 'High',
                        confidence_score=confidence,
                        model_version=cls.MODEL_VERSION,
                        details_json={
                            'ip_address': ip,
                            'failed_count': count,
                            'timeframe': '1 hour',
                            'note': f'{count} failed logins from {ip}',
                        },
                    )
                    new_anomalies += 1

        return new_anomalies

    # ── 3. Off-Hours Access ──
    @classmethod
    def check_off_hours_access(cls):
        """Detect logins outside normal working hours."""
        new_anomalies = 0
        recent = timezone.now() - timedelta(days=1)

        off_hour_count = LoginAttempt.objects.filter(
            attempted_at__gte=recent,
            attempt_result='SUCCESS',
            attempted_at__hour__gte=22,
        ).count() + LoginAttempt.objects.filter(
            attempted_at__gte=recent,
            attempt_result='SUCCESS',
            attempted_at__hour__lte=4,
        ).count()

        if off_hour_count >= 2:
            confidence = 0.65
            if confidence >= cls.CONFIDENCE_THRESHOLD:
                exists = AnomalyDetectionEvent.objects.filter(
                    anomaly_type='Suspicious_Login',
                    is_investigated=False,
                    created_at__gte=recent,
                ).count()
                if exists < 2:
                    AnomalyDetectionEvent.objects.create(
                        anomaly_type='Suspicious_Login',
                        severity='Low',
                        confidence_score=confidence,
                        model_version=cls.MODEL_VERSION,
                        details_json={
                            'login_count': off_hour_count,
                            'timeframe': 'off-hours (10PM-4AM)',
                            'note': f'{off_hour_count} logins outside normal hours',
                        },
                    )
                    new_anomalies += 1

        return new_anomalies