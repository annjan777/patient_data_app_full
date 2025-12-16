from django import forms
from .models import Patient, Device, UserProfile
from django.forms.widgets import DateInput, TextInput, Textarea, EmailInput, NumberInput, Select, CheckboxInput
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

User = get_user_model()

class PatientForm(forms.ModelForm):
    date_of_birth = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        input_formats=['%Y-%m-%d', '%d/%m/%Y', '%d/%m/%y']
    )
    
    class Meta:
        model = Patient
        fields = ['name', 'date_of_birth', 'age', 'gender', 'phone_number', 'email', 'address', 'clinical_notes']
        widgets = {
            'name': TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter full name'}),
            'age': NumberInput(attrs={'class': 'form-control', 'min': '0', 'max': '150'}),
            'gender': Select(attrs={'class': 'form-control'}),
            'phone_number': TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. +1234567890'}),
            'email': EmailInput(attrs={'class': 'form-control', 'placeholder': 'example@email.com'}),
            'address': Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Enter full address'}),
            'clinical_notes': Textarea(attrs={
                'class': 'form-control', 
                'rows': 6, 
                'placeholder': 'Enter medical history, symptoms, diagnoses, and treatment plans',
                'style': 'min-height: 180px;'
            })
        }
        help_texts = {
            'patient_id': 'Unique identifier for the patient (auto-generated)',
            'email': 'A valid email address for communication',
            'phone_number': 'Include country code if applicable (e.g., +1 for US)',
            'clinical_notes': 'Medical history, observations, and treatment details'
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        
        # Only generate a new patient ID for new instances
        if not instance.patient_id:
            instance.patient_id = generate_patient_id()
            
        if commit:
            instance.save()
            self.save_m2m()
            
        return instance

    def clean_phone_number(self):
        phone_number = self.cleaned_data.get('phone_number')
        # Add any phone number validation here
        if phone_number and not phone_number.replace('+', '').replace(' ', '').replace('-', '').isdigit():
            raise forms.ValidationError("Enter a valid phone number")
        return phone_number

    def clean(self):
        cleaned_data = super().clean()
        date_of_birth = cleaned_data.get('date_of_birth')
        age = cleaned_data.get('age')
        
        # If both date_of_birth and age are provided, prioritize date_of_birth
        if date_of_birth and age:
            from datetime import date
            today = date.today()
            calculated_age = today.year - date_of_birth.year - ((today.month, today.day) < (date_of_birth.month, date_of_birth.day))
            if calculated_age != age:
                self.add_error('age', f'Age does not match date of birth (should be {calculated_age} years)')
        
        return cleaned_data


class DeviceForm(forms.ModelForm):
    class Meta:
        model = Device
        fields = ['device_id', 'name', 'is_active']
        widgets = {
            'device_id': TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter device ID (e.g., DEV001)'
            }),
            'name': TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter device name (e.g., Spectrometer 1)'
            }),
            'is_active': CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }
        help_texts = {
            'device_id': 'Unique identifier for the device (letters and numbers only)',
            'name': 'A friendly name for the device',
            'is_active': 'Uncheck to deactivate this device'
        }

    def clean_device_id(self):
        device_id = self.cleaned_data.get('device_id')
        if not device_id.isalnum():
            raise ValidationError('Device ID can only contain letters and numbers')
        return device_id.upper()


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['device', 'is_admin']
        widgets = {
            'device': Select(attrs={'class': 'form-select'}),
            'is_admin': CheckboxInput(attrs={'class': 'form-check-input'})
        }
        help_texts = {
            'device': 'Select the device assigned to this user',
            'is_admin': 'Check to grant admin privileges to this user'
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show active devices in the dropdown
        self.fields['device'].queryset = Device.objects.filter(is_active=True)
