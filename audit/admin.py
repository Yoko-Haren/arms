from django.contrib import admin
from .models import (
    ActivityLog,
    BlockchainBlock,
    AnomalyDetectionEvent,
    DataCorrectionRequest,
)


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = [
        'timestamp', 'user_name', 'action_type', 'resource_type',
        'resource_id', 'ip_address', 'blockchain_verified',
    ]
    list_filter = ['action_type', 'resource_type', 'blockchain_verified', 'timestamp']
    search_fields = ['user_name', 'resource_id', 'ip_address']
    date_hierarchy = 'timestamp'
    readonly_fields = [
        'timestamp', 'user', 'user_name', 'user_role', 'action_type',
        'resource_type', 'resource_id', 'affected_student', 'affected_teacher',
        'details_json', 'ip_address', 'user_agent', 'session',
        'blockchain_hash', 'prev_blockchain_hash', 'blockchain_verified',
        'created_at',
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BlockchainBlock)
class BlockchainBlockAdmin(admin.ModelAdmin):
    list_display = [
        'block_index', 'log_count', 'current_hash_preview',
        'merkle_root_preview', 'mined_at',
    ]
    search_fields = ['current_hash', 'merkle_root']
    readonly_fields = [
        'block_index', 'previous_hash', 'current_hash', 'merkle_root',
        'log_count', 'log_ids', 'nonce', 'mined_at', 'created_at',
    ]

    def current_hash_preview(self, obj):
        return obj.current_hash[:16] + '...'
    current_hash_preview.short_description = 'Block Hash'

    def merkle_root_preview(self, obj):
        return obj.merkle_root[:16] + '...'
    merkle_root_preview.short_description = 'Merkle Root'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AnomalyDetectionEvent)
class AnomalyDetectionEventAdmin(admin.ModelAdmin):
    list_display = [
        'anomaly_type', 'severity', 'confidence_score',
        'is_investigated', 'investigation_result', 'created_at',
    ]
    list_filter = ['anomaly_type', 'severity', 'is_investigated', 'investigation_result']
    search_fields = ['details_json', 'resolution_notes']
    raw_id_fields = ['triggering_log', 'investigated_by']
    readonly_fields = [
        'triggering_log', 'anomaly_type', 'severity', 'confidence_score',
        'model_version', 'details_json', 'created_at',
    ]
    fieldsets = (
        ('Anomaly Details', {
            'fields': (
                'triggering_log', 'anomaly_type', 'severity',
                'confidence_score', 'model_version', 'details_json',
            ),
        }),
        ('Investigation', {
            'fields': (
                'is_investigated', 'investigated_by', 'investigated_at',
                'investigation_result', 'resolution_notes',
            ),
        }),
        ('Audit', {
            'fields': ('created_at', 'updated_at'),
        }),
    )


@admin.register(DataCorrectionRequest)
class DataCorrectionRequestAdmin(admin.ModelAdmin):
    list_display = [
        'entity_type', 'entity_id', 'field_to_correct',
        'status', 'requested_by', 'created_at',
    ]
    list_filter = ['status', 'entity_type']
    search_fields = ['entity_id', 'field_to_correct', 'justification']
    raw_id_fields = ['requested_by', 'reviewed_by', 'executed_by']
    readonly_fields = ['created_at', 'updated_at']