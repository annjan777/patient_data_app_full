from django.contrib import admin
from .models import Patient, MeasurementSession, SpectralPoint

@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ('patient_id','name','age','gender')
    search_fields = ('patient_id','name')

@admin.register(MeasurementSession)
class SessionAdmin(admin.ModelAdmin):
    list_display = ('session_id', 'patient', 'initiated_by', 'created_at', 'status', 'device')
    list_filter = ('status', 'created_at', 'device')
    readonly_fields = ('created_at', 'updated_at')
    search_fields = ('session_id', 'patient__name', 'device__name', 'device__device_id')
    list_select_related = ('patient', 'initiated_by', 'device')

@admin.register(SpectralPoint)
class SpectralAdmin(admin.ModelAdmin):
    list_display = ('session','wavelength','intensity')
    ordering = ('session','wavelength')
