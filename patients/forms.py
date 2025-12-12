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
