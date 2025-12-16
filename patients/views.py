from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from .models import Patient, MeasurementSession, SpectralPoint, Device, UserProfile
from .forms import PatientForm, DeviceForm, UserProfileForm
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import get_user_model
from django.conf import settings
import paho.mqtt.publish as publish
import uuid, json, io, logging
from django.http import HttpResponse, JsonResponse, Http404
import pandas as pd
from django.views.decorators.http import require_POST, require_http_methods
from django.db import transaction
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from django.utils import timezone

logger = logging.getLogger(__name__)
User = get_user_model()

def is_admin(user):
    return hasattr(user, 'profile') and user.profile.is_admin

@login_required
def dashboard(request):
    patients = Patient.objects.all()[:10]
    
    # Get the most recent sessions with their data status
    from django.db import connection
    from django.db.utils import DEFAULT_DB_ALIAS
    from django.db.models import F
    
    # Use the ORM to get sessions with their data status
    from .models import MeasurementSession, SpectralPoint
    
    # Get the most recent 10 sessions
    sessions = MeasurementSession.objects.all().order_by('-created_at')[:10]
    
    # Update status for each session if needed
    session_objects = []
    for session in sessions:
        # Check if session has data
        has_data = SpectralPoint.objects.filter(session=session).exists()
        
        # If session has data but status is still 'in_progress', update it
        if has_data and session.status == 'in_progress':
            session.status = 'completed'
            session.save(update_fields=['status', 'updated_at'])
        
        # Add to the result set
        session_objects.append(session)
    
    return render(request, 'patients/dashboard.html', {
        'patients': patients,
        'sessions': session_objects
    })

@login_required
@user_passes_test(is_admin)
def device_list(request):
    devices = Device.objects.all()
    return render(request, 'patients/device_list.html', {'devices': devices})

@login_required
@user_passes_test(is_admin)
def device_create(request):
    if request.method == 'POST':
        form = DeviceForm(request.POST)
        if form.is_valid():
            device = form.save()
            messages.success(request, f'Device {device.name} created successfully.')
            return redirect('patients:device_list')
    else:
        form = DeviceForm()
    return render(request, 'patients/device_form.html', {'form': form, 'title': 'Add Device'})

@login_required
@user_passes_test(is_admin)
def device_edit(request, pk):
    device = get_object_or_404(Device, pk=pk)
    if request.method == 'POST':
        form = DeviceForm(request.POST, instance=device)
        if form.is_valid():
            device = form.save()
            messages.success(request, f'Device {device.name} updated successfully.')
            return redirect('patients:device_list')
    else:
        form = DeviceForm(instance=device)
    return render(request, 'patients/device_form.html', {'form': form, 'title': 'Edit Device'})

@login_required
@user_passes_test(is_admin)
def device_toggle_active(request, pk):
    device = get_object_or_404(Device, pk=pk)
    device.is_active = not device.is_active
    device.save()
    status = 'activated' if device.is_active else 'deactivated'
    messages.success(request, f'Device {device.name} has been {status}.')
    return redirect('patients:device_list')

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

from django.db import transaction
from django.contrib import messages

@login_required
def patient_detail(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    
    if request.method == 'POST' and 'start_measurement' in request.POST:
        device_id = request.POST.get('device_id')
        if not device_id:
            messages.error(request, "Please select a device")
            return redirect('patients:patient_detail', pk=pk)
            
        try:
            with transaction.atomic():
                # Get the device instance
                device = get_object_or_404(Device, id=device_id, is_active=True)
                
                # Create a new session with the patient and device
                session = MeasurementSession.objects.create(
                    patient=patient,
                    device=device,
                    initiated_by=request.user,
                    status='in_progress'  # Start with in_progress
                )
                
                # Publish control message to device-specific topic
                control_topic = f"device/{device.device_id}/control"
                payload = {
                    'command': 'start_measurement',
                    'timestamp': timezone.now().isoformat(),
                    'session_id': str(session.session_id)
                }
                try:
                    publish.single(
                        control_topic,
                        payload=json.dumps(payload),
                        hostname=settings.MQTT['BROKER'],
                        port=settings.MQTT['PORT'],
                        qos=1,
                        retain=False
                    )
                    messages.success(request, f"Measurement started. Session ID: {session.session_id}")
                except Exception as e:
                    logger.error(f"Failed to publish MQTT message: {str(e)}")
                    messages.error(request, "Failed to start measurement. Please try again.")
                
                return redirect('patients:patient_detail', pk=pk)
                
        except Exception as e:
            messages.error(request, f"Error starting measurement: {str(e)}")
            return redirect('patients:patient_detail', pk=pk)
    
    # Get active devices for the dropdown
    active_devices = Device.objects.filter(is_active=True)
    
    # Get recent sessions for this patient
    recent_sessions = MeasurementSession.objects.filter(
        patient=patient
    ).select_related('device').order_by('-created_at')[:5]
    
    # Update status for each session if needed
    for session in recent_sessions:
        has_data = session.spectra.exists()
        if has_data and session.status == 'in_progress':
            session.status = 'completed'
            session.save(update_fields=['status', 'updated_at'])
    
    return render(request, 'patients/patient_detail.html', {
        'patient': patient,
        'active_devices': active_devices,
        'recent_sessions': recent_sessions
    })

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
    # Get the session with related data
    session = get_object_or_404(
        MeasurementSession.objects.select_related('patient', 'device', 'initiated_by'),
        session_id=session_id
    )
    
    # Get all spectral points ordered by wavelength
    spectral_points = session.spectra.all().order_by('wavelength')
    has_data = spectral_points.exists()
    
    # Update status if needed
    if has_data and session.status == 'in_progress':
        session.status = 'completed'
        session.save(update_fields=['status', 'updated_at'])
    
    # Prepare chart data
    chart_data = {
        'wavelengths': [str(point.wavelength) for point in spectral_points],
        'intensities': [float(point.intensity) for point in spectral_points],
        'has_data': has_data
    }
    
    if request.method == 'POST':
        if 'delete_session' in request.POST:
            patient_pk = session.patient.pk if session.patient else None
            session.delete()
            messages.success(request, 'Measurement session deleted successfully.')
            if patient_pk:
                return redirect('patients:patient_detail', pk=patient_pk)
            return redirect('patients:dashboard')
    
    return render(request, 'patients/session_detail.html', {
        'session': session,
        'spectral_points': spectral_points,
        'chart_data': chart_data,
    })

@login_required
@require_GET
def session_data(request, session_id):
    """Return session data as JSON for the chart"""
    # Get the session and force a fresh database query
    session = get_object_or_404(MeasurementSession.objects.select_for_update(), session_id=session_id)
    
    # Force a database refresh
    session.refresh_from_db()
    
    # Get the latest points
    points = session.spectra.all().order_by('wavelength')
    
    # Update status to 'completed' if there are any points and status is still 'in_progress'
    if points.exists() and session.status == 'in_progress':
        session.status = 'completed'
        session.save(update_fields=['status', 'updated_at'])
    
    data = {
        'wavelengths': [float(p.wavelength) for p in points],
        'intensities': [float(p.intensity) for p in points],
        'status': session.status,
        'point_count': points.count()
    }
    
    return JsonResponse(data)

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
