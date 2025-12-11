from django.core.management.base import BaseCommand
from django.conf import settings
import paho.mqtt.client as mqtt
import json
from patients.models import MeasurementSession, SpectralPoint, Patient
from django.utils import timezone

class Command(BaseCommand):
    help = 'Run MQTT subscriber to ingest device data (blocking)'

    def handle(self, *args, **options):
        broker = settings.MQTT['BROKER']
        port = settings.MQTT['PORT']
        topic = settings.MQTT['DATA_TOPIC']
        client = mqtt.Client()

        def on_connect(c, userdata, flags, rc):
            self.stdout.write(self.style.SUCCESS(f'Connected to MQTT {broker}:{port}, rc={rc}'))
            c.subscribe(topic)

        def on_message(c, userdata, msg):
            try:
                payload = msg.payload.decode()
                data = json.loads(payload)
                sid = data.get('session_id')
                device = data.get('device_id')
                spectra = data.get('spectra', [])
                # Basic validation
                if not sid or not isinstance(spectra, list):
                    self.stderr.write('Invalid payload: missing session_id or spectra not a list')
                    return
                session = MeasurementSession.objects.filter(session_id=sid).first()
                if not session:
                    # attempt to link patient by patient_id if provided
                    pid = data.get('patient_id')
                    patient = None
                    if pid:
                        patient = Patient.objects.filter(patient_id=pid).first()
                    session = MeasurementSession.objects.create(patient=patient, device_id=device or 'unknown')
                for sp in spectra:
                    try:
                        w = float(sp.get('wavelength'))
                        i = float(sp.get('intensity'))
                        SpectralPoint.objects.create(session=session, wavelength=w, intensity=i)
                    except Exception as e:
                        self.stderr.write(f'Bad spectral point: {sp} -> {e}')
                session.completed = True
                if device:
                    session.device_id = device
                session.save()
                self.stdout.write(self.style.SUCCESS(f'Ingested data for session {session.session_id} (points: {len(spectra)})'))
            except Exception as e:
                self.stderr.write(f'Error parsing message: {e}')

        client.on_connect = on_connect
        client.on_message = on_message
        client.connect(broker, port, 60)
        client.loop_forever()
