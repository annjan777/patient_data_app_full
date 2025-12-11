from django.shortcuts import render, redirect, get_object_or_404
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

@login_required
def patient_create(request):
    if request.method=='POST':
        form = PatientForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('patients:patient_list')
    else:
        form = PatientForm()
    return render(request,'patients/patient_form.html',{'form':form})

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
