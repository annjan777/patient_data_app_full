from django.db import models
from django.contrib.auth import get_user_model
import uuid

class Patient(models.Model):
    patient_id = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=200)
    age = models.PositiveIntegerField(null=True, blank=True)
    gender = models.CharField(max_length=32, blank=True)
    clinical_notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.patient_id} - {self.name}"

class MeasurementSession(models.Model):
    session_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='sessions', null=True, blank=True)
    initiated_by = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    device_id = models.CharField(max_length=128, blank=True)
    completed = models.BooleanField(default=False)

    def __str__(self):
        return str(self.session_id)

class SpectralPoint(models.Model):
    session = models.ForeignKey(MeasurementSession, on_delete=models.CASCADE, related_name='spectra')
    wavelength = models.FloatField()
    intensity = models.FloatField()

    class Meta:
        ordering = ['wavelength']
