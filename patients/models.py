from django.db import models
from django.contrib.auth import get_user_model
import uuid

def generate_patient_id():
    """Generate a new patient ID in the format PID000001"""
    from django.db.models import Max
    from django.db.models.functions import Substr, Cast
    from django.db.models import IntegerField
    
    # Get the highest existing PID number
    max_pid = Patient.objects.annotate(
        pid_num=Cast(Substr('patient_id', 4), output_field=IntegerField())
    ).aggregate(max_pid=Max('pid_num'))['max_pid']
    
    # If no patients exist yet, start from 1, otherwise increment the max
    new_number = 1 if max_pid is None else max_pid + 1
    
    # Format as PID with leading zeros
    return f"PID{new_number:06d}"

class Patient(models.Model):
    GENDER_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
        ('O', 'Other'),
        ('', 'Prefer not to say'),
    ]
    
    patient_id = models.CharField(
        max_length=10,
        unique=True,
        help_text='Unique identifier for the patient',
        verbose_name='Patient ID',
        default=generate_patient_id,
        editable=False
    )
    name = models.CharField(
        max_length=200,
        help_text='Full name of the patient'
    )
    date_of_birth = models.DateField(
        null=True,
        blank=True,
        help_text='Date of birth (YYYY-MM-DD)',
        verbose_name='Date of Birth'
    )
    age = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Age in years',
        verbose_name='Age'
    )
    gender = models.CharField(
        max_length=1,
        choices=GENDER_CHOICES,
        blank=True,
        help_text='Gender identity'
    )
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        help_text='Contact number with country code',
        verbose_name='Phone Number'
    )
    email = models.EmailField(
        max_length=254,
        blank=True,
        help_text='Primary email address'
    )
    address = models.TextField(
        blank=True,
        help_text='Full postal address'
    )
    clinical_notes = models.TextField(
        blank=True,
        help_text='Medical history and clinical observations',
        verbose_name='Clinical Notes'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Patient'
        verbose_name_plural = 'Patients'

    def __str__(self):
        return f"{self.name} ({self.patient_id})"
        
    def save(self, *args, **kwargs):
        # Auto-calculate age from date_of_birth if provided
        if self.date_of_birth and not self.age:
            from datetime import date
            today = date.today()
            self.age = today.year - self.date_of_birth.year - (
                (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
            )
        super().save(*args, **kwargs)

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
