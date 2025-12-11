from django import forms
from .models import Patient
from django.forms.widgets import DateInput, TextInput, Textarea, EmailInput, NumberInput, Select

class PatientForm(forms.ModelForm):
    date_of_birth = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        input_formats=['%Y-%m-%d', '%d/%m/%Y', '%d/%m/%y']
    )
    
    class Meta:
        model = Patient
        fields = ['patient_id', 'name', 'date_of_birth', 'age', 'gender', 'phone_number', 'email', 'address', 'clinical_notes']
        widgets = {
            'patient_id': TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter patient ID'}),
            'name': TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter full name'}),
            'age': NumberInput(attrs={'class': 'form-control', 'min': '0', 'max': '150'}),
            'gender': Select(attrs={'class': 'form-control'}),
            'phone_number': TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. +1234567890'}),
            'email': EmailInput(attrs={'class': 'form-control', 'placeholder': 'example@email.com'}),
            'address': Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Enter full address'}),
            'clinical_notes': Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Enter any clinical notes'}),
        }
        help_texts = {
            'patient_id': 'Unique identifier for the patient',
            'email': 'A valid email address',
            'phone_number': 'Include country code if applicable',
        }

    def clean_patient_id(self):
        patient_id = self.cleaned_data.get('patient_id')
        if not patient_id:
            raise forms.ValidationError("Patient ID is required")
        return patient_id

    def clean_phone_number(self):
        phone_number = self.cleaned_data.get('phone_number')
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
            if age != calculated_age:
                self.add_error('age', f'Age should be {calculated_age} based on the date of birth')
        
        return cleaned_data
