from django.contrib import admin
from .models import Patient, MeasurementSession, SpectralPoint

@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ('patient_id','name','age','gender')
    search_fields = ('patient_id','name')

@admin.register(MeasurementSession)
class SessionAdmin(admin.ModelAdmin):
    list_display = ('session_id','patient','initiated_by','created_at','completed')
    list_filter = ('completed','created_at')

@admin.register(SpectralPoint)
class SpectralAdmin(admin.ModelAdmin):
    list_display = ('session','wavelength','intensity')
    ordering = ('session','wavelength')
