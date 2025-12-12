from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from .models import Patient, MeasurementSession, SpectralPoint
from .forms import PatientForm
from django.contrib.auth.decorators import login_required
from django.conf import settings
import paho.mqtt.publish as publish
import uuid, json, io
from django.http import HttpResponse, JsonResponse
import pandas as pd
from django.views.decorators.http import require_POST

@login_required
def dashboard(request):
    patients = Patient.objects.all()[:10]
    sessions = MeasurementSession.objects.order_by('-created_at')[:10]
    return render(request,'patients/dashboard.html',{'patients':patients,'sessions':sessions})

@login_required
def patient_list(request):
    q = request.GET.get('q','')
    patients = Patient.objects.filter(name__icontains=q) if q else Patient.objects.all()
    return render(request,'patients/patient_list.html',{'patients':patients,'q':q})

from django.contrib import messages
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags

def send_patient_email_async(patient, created_by):
    """Helper function to send email in a separate thread"""
    try:
        subject = f"New Patient Registration: {patient.name}"
        html_message = render_to_string('patients/email/patient_created.html', {
            'patient': patient,
            'created_by': created_by,
        })
        plain_message = strip_tags(html_message)
        
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[patient.email],
            html_message=html_message,
            fail_silently=True,  # Don't raise exceptions for email failures
        )
    except Exception as e:
        # Log the error but don't show to user
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to send patient email: {str(e)}")

@login_required
def patient_create(request):
    if request.method == 'POST':
        form = PatientForm(request.POST)
        if form.is_valid():
            patient = form.save()
            
            # Prepare success message with PID
            success_message = f"Patient created successfully! Patient ID: {patient.patient_id}"
            messages.success(request, success_message)
            
            # Send email in background thread if email is provided
            if patient.email:
                try:
                    # Start a new thread to send the email
                    email_thread = Thread(
                        target=send_patient_email_async,
                        args=(patient, request.user.get_full_name() or request.user.username)
                    )
                    email_thread.daemon = True  # Thread will close when main program exits
                    email_thread.start()
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Error preparing email: {str(e)}")
            
            # Return JSON response for AJAX or redirect for normal form submission
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'patient_id': patient.patient_id,
                    'redirect': reverse('patients:patient_list')
                })
            return redirect('patients:patient_list')
        elif request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'errors': form.errors
            }, status=400)
    else:
        form = PatientForm()
    
    return render(request, 'patients/patient_form.html', {'form': form})

@login_required
def patient_detail(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    if request.method=='POST' and 'start_measurement' in request.POST:
        # create session
        session = MeasurementSession.objects.create(patient=patient, initiated_by=request.user)
        # publish strict JSON payload
        payload = json.dumps({'timestamp': str(session.created_at), 'session_id': str(session.session_id), 'patient_id': patient.patient_id})
        publish.single(settings.MQTT['CONTROL_TOPIC'], payload=payload, hostname=settings.MQTT['BROKER'], port=settings.MQTT['PORT'])
        return redirect('patients:patient_detail', pk=pk)
    return render(request,'patients/patient_detail.html',{'patient':patient})

@login_required
def patient_update(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    if request.method == 'POST':
        form = PatientForm(request.POST, instance=patient)
        if form.is_valid():
            form.save()
            return redirect('patients:patient_detail', pk=patient.pk)
    else:
        form = PatientForm(instance=patient)
    return render(request, 'patients/patient_form.html', {'form': form, 'patient': patient})

@login_required
@require_POST
def patient_delete(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    patient.delete()
    return redirect('patients:patient_list')

@login_required
def session_detail(request, session_id):
    session = get_object_or_404(MeasurementSession, session_id=session_id)
    spectra = session.spectra.all().order_by('wavelength')
    data = [{'wavelength': s.wavelength, 'intensity': s.intensity} for s in spectra]
    return render(request,'patients/session_detail.html',{'session':session,'data':data})

@login_required
def export_csv(request, session_id):
    session = get_object_or_404(MeasurementSession, session_id=session_id)
    qs = SpectralPoint.objects.filter(session=session).order_by('wavelength')
    rows = [{'wavelength': p.wavelength, 'intensity': p.intensity} for p in qs]
    df = pd.DataFrame(rows)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    resp = HttpResponse(buf.getvalue(), content_type='text/csv')
    resp['Content-Disposition'] = f'attachment; filename="session_{session_id}.csv"'
    return resp

@login_required
def export_xlsx(request, session_id):
    session = get_object_or_404(MeasurementSession, session_id=session_id)
    qs = SpectralPoint.objects.filter(session=session).order_by('wavelength')
    rows = [{'wavelength': p.wavelength, 'intensity': p.intensity} for p in qs]
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='spectra')
    buf.seek(0)
    resp = HttpResponse(buf.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="session_{session_id}.xlsx"'
    return resp
