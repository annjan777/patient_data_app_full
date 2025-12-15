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
                device_id = data.get('device_id', '001')  # Default to '001' if not provided
                
                # Check if this is a control message or data message
                if 'spectra' in data:
                    # This is a data message with spectral data
                    spectra = data.get('spectra', [])
                    
                    # Basic validation
                    if not isinstance(spectra, list):
                        self.stderr.write('Invalid payload: spectra must be a list')
                        return
                    
                    # Get or create a session for this device
                    session = None
                    session_id = data.get('session_id')
                    
                    if session_id:
                        # Try to find existing session by ID
                        try:
                            session = MeasurementSession.objects.get(pk=session_id)
                        except (ValueError, MeasurementSession.DoesNotExist):
                            self.stderr.write(f'Session {session_id} not found, creating new session')
                    
                    if not session:
                        # Create a new session if no valid session_id provided or found
                        patient = None
                        pid = data.get('patient_id')
                        if pid:
                            patient = Patient.objects.filter(patient_id=pid).first()
                        
                        session = MeasurementSession.objects.create(
                            patient=patient,
                            device_id=device_id,
                            initiated_by=None  # Can't determine user from MQTT
                        )
                    
                    # Process spectral data
                    for sp in spectra:
                        try:
                            w = float(sp.get('wavelength'))
                            i = float(sp.get('intensity'))
                            # Skip if values are not valid numbers
                            if not (isinstance(w, (int, float)) and isinstance(i, (int, float))):
                                continue
                            SpectralPoint.objects.create(session=session, wavelength=w, intensity=i)
                        except (TypeError, ValueError) as e:
                            self.stderr.write(f'Bad spectral point: {sp} -> {e}')
                    
                    session.completed = True
                    session.save()
                    self.stdout.write(self.style.SUCCESS(
                        f'Ingested {len(spectra)} data points for device {device_id} (session: {session.id})'
                    ))
                
                elif 'command' in data:
                    # Handle control messages if needed
                    command = data.get('command')
                    self.stdout.write(f'Received command: {command} from device {device_id}')
                
                else:
                    self.stderr.write(f'Unknown message format: {data}')
                    
            except json.JSONDecodeError:
                self.stderr.write(f'Failed to decode JSON: {msg.payload}')
            except Exception as e:
                self.stderr.write(f'Error processing message: {str(e)}')
            except Exception as e:
                self.stderr.write(f'Error parsing message: {e}')

        client.on_connect = on_connect
        client.on_message = on_message
        client.connect(broker, port, 60)
        client.loop_forever()
