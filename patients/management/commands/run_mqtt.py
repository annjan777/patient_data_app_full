from django.core.management.base import BaseCommand
import paho.mqtt.client as mqtt
import json
from django.conf import settings
from django.utils import timezone
from patients.models import Device, MeasurementSession, SpectralPoint
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

class Command(BaseCommand):
    help = 'Run MQTT subscriber to ingest device data (blocking)'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting MQTT consumer...'))
        
        # Initialize MQTT client
        client = mqtt.Client()
        client.on_connect = self.on_connect
        client.on_message = self.on_message
        
        # Connect to MQTT broker
        try:
            client.connect(
                settings.MQTT['BROKER'],
                settings.MQTT['PORT'],
                settings.MQTT.get('KEEPALIVE', 60)
            )
            self.stdout.write(self.style.SUCCESS(f'Connected to MQTT broker at {settings.MQTT["BROKER"]}:{settings.MQTT["PORT"]}'))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'Failed to connect to MQTT broker: {str(e)}'))
            return

        # Start the MQTT loop
        client.loop_forever()

    def on_connect(self, client, userdata, flags, rc):
        """Callback for when the client receives a CONNACK response from the server."""
        if rc == 0:
            self.stdout.write(self.style.SUCCESS('Successfully connected to MQTT broker'))
            # Subscribe to the data topic
            client.subscribe(settings.MQTT['DATA_TOPIC'])
            self.stdout.write(f'Subscribed to topic: {settings.MQTT["DATA_TOPIC"]}')
        else:
            self.stderr.write(self.style.ERROR(f'Failed to connect to MQTT broker with result code {rc}'))

    def on_message(self, client, userdata, msg):
        """Callback for when a PUBLISH message is received from the server."""
        try:
            self.stdout.write(f'\n=== New MQTT Message ===')
            self.stdout.write(f'Topic: {msg.topic}')
            self.stdout.write(f'Payload: {msg.payload}')

            # Parse topic to get device_id and session_id
            topic_parts = msg.topic.split('/')
            if len(topic_parts) >= 3 and topic_parts[2] == 'measurements':
                device_id = topic_parts[0]
                session_id = topic_parts[1]
                self.process_spectral_data(device_id, session_id, msg.payload)
        except Exception as e:
            self.stderr.write(f'Error processing message: {str(e)}')

    def process_spectral_data(self, device_id, session_id, payload):
        """Process spectral data and save to database."""
        try:
            # Parse JSON payload
            data = json.loads(payload.decode())
            self.stdout.write(f'Decoded data: {data}')

            # Get device and session
            device = Device.objects.get(device_id=device_id, is_active=True)
            session = MeasurementSession.objects.get(session_id=session_id)

            # Check if session is already completed
            if session.status == 'completed':
                self.stdout.write(f'Session {session_id} is already completed')
                return

            # Create spectral point
            wavelength = float(data.get('wavelength'))
            intensity = float(data.get('intensity'))
            
            # Check for duplicate data point
            if not SpectralPoint.objects.filter(session=session, wavelength=wavelength).exists():
                SpectralPoint.objects.create(
                    session=session,
                    wavelength=wavelength,
                    intensity=intensity
                )
                self.stdout.write(f'Added new data point to session {session_id}')

                # Update session status
                session.status = 'completed'
                session.save(update_fields=['status', 'updated_at'])
                
                # Notify WebSocket clients
                self.notify_websocket(session_id, 'data_update')
                self.stdout.write(f'Marked session {session_id} as completed')
            else:
                self.stdout.write(f'Skipping duplicate data point for session {session_id}')

        except json.JSONDecodeError as e:
            self.stderr.write(f'Failed to decode JSON: {str(e)}')
        except Device.DoesNotExist:
            self.stderr.write(f'Device {device_id} not found or inactive')
        except MeasurementSession.DoesNotExist:
            self.stderr.write(f'Session {session_id} not found')
        except Exception as e:
            self.stderr.write(f'Error processing data: {str(e)}')

    def notify_websocket(self, session_id, message_type):
        """Send WebSocket notification for session updates."""
        try:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'session_{session_id}',
                {
                    'type': 'session_update',
                    'message': {
                        'type': message_type,
                        'session_id': str(session_id)
                    }
                }
            )
        except Exception as e:
            self.stderr.write(f'WebSocket notification failed: {str(e)}')