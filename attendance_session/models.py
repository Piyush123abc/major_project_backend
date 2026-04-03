from django.db import models

# Create your models here.

from django.utils import timezone
from user.models import Student

class SecurityAnomaly(models.Model):
    class AnomalyType(models.IntegerChoices):
        LATENCY_SPIKE = 1, 'Latency Spike (Relay Risk)'
        PROXIMITY_VIOLATION = 2, 'Proximity Violation (MITM Risk)'
        RAPID_FIRE_SCANS = 3, 'Rapid Fire Scans (Brute Force)'
        DEVICE_MISMATCH = 4, 'Device Mismatch (Account Sharing)'
        BIOMETRIC_ALTERED = 5, 'Biometric State Altered (Tampering)'
        PLAY_INTEGRITY_FAIL = 6, 'Play Integrity API Failure'

    # Changed from CharField to a ForeignKey pointing to the Student model
    student = models.ForeignKey(
        Student, 
        on_delete=models.CASCADE, 
        related_name='security_anomalies'
    )
    anomaly_type = models.IntegerField(choices=AnomalyType.choices)
    device_id = models.CharField(max_length=255, blank=True, null=True)
    timestamp = models.DateTimeField(default=timezone.now)
    
    metadata = models.JSONField(blank=True, null=True) 

    class Meta:
        verbose_name_plural = "Security Anomalies"
        ordering = ['-timestamp']

    def __str__(self):
        # Now we access the UID through the foreign key relationship
        return f"{self.student.uid} - {self.get_anomaly_type_display()}"