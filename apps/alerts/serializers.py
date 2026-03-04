from rest_framework import serializers
from .models import Alert, AIAnalysis


class AIAnalysisSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIAnalysis
        exclude = ('alert',)
        read_only_fields = ('analyzed_at',)


class AlertSerializer(serializers.ModelSerializer):
    ai_analysis = AIAnalysisSerializer(read_only=True)

    class Meta:
        model = Alert
        fields = '__all__'
        read_only_fields = ('created_at',)


class AlertCreateSerializer(serializers.ModelSerializer):
    ai_analysis = AIAnalysisSerializer(required=False)

    class Meta:
        model = Alert
        fields = '__all__'
        read_only_fields = ('created_at',)

    def create(self, validated_data):
        ai_data = validated_data.pop('ai_analysis', None)
        alert = Alert.objects.create(**validated_data)
        if ai_data:
            AIAnalysis.objects.create(alert=alert, **ai_data)
        return alert
