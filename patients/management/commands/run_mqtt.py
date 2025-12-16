import json
import logging
from django.core.management.base import BaseCommand
from django.conf import settings
import paho.mqtt.client as mqtt
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from patients.models import MeasurementSession, SpectralPoint
from django.utils import timezone

# Set up logging
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Run MQTT subscriber to ingest device data (blocking)'

    def handle(self, *args, **options):
        broker = settings.MQTT['BROKER']
        port = settings.MQTT['PORT']
        data_topic = settings.MQTT['DATA_TOPIC']
        
        self.stdout.write(self.style.SUCCESS(f'Starting MQTT consumer on {broker}:{port}'))
        self.stdout.write(f'Subscribing to topic: {data_topic}')
        
        client = mqtt.Client()
        client.enable_logger()

        def on_connect(c, userdata, flags, rc):
            if rc == 0:
                self.stdout.write(self.style.SUCCESS(f'Connected to MQTT {broker}:{port}'))
                c.subscribe(data_topic, qos=1)
                self.stdout.write(f'Subscribed to {data_topic}')
            else:
                self.stderr.write(self.style.ERROR(f'Failed to connect to MQTT: {rc}'))

        def on_message(c, userdata, msg):
            try:
                self.stdout.write(f"\n=== New MQTT Message ===")
                self.stdout.write(f"Topic: {msg.topic}")
                self.stdout.write(f"Payload: {msg.payload}")
                
                topic_parts = msg.topic.split('/')
                if len(topic_parts) >= 3 and topic_parts[2] == 'measurements':
                    device_id = topic_parts[0]
                    session_id = topic_parts[1]
                    
                    try:
                        self.stdout.write("\n=== Processing MQTT Message ===")
                        self.stdout.write(f"Topic: {msg.topic}")
                        self.stdout.write(f"Payload: {msg.payload}")
                        
                        try:
                            data = json.loads(msg.payload.decode())
                            self.stdout.write(f"Decoded data: {data}")
                            
                            # Get the session
                            try:
                                session = MeasurementSession.objects.get(session_id=session_id)
                                
                                # If session is already completed, skip processing and unsubscribe
                                if session.status == 'completed':
                                    self.stdout.write(f"Session {session_id} is already completed. Skipping...")
                                    topic = f"{device_id}/{session_id}/measurements"
                                    c.unsubscribe(topic)
                                    self.stdout.write(f"Unsubscribed from topic: {topic}")
                                    return None
                                    
                                # If session has data but status is not updated, update status
                                if session.spectra.exists() and session.status != 'completed':
                                    session.status = 'completed'
                                    session.save(update_fields=['status', 'updated_at'])
                                    self.stdout.write(f"Updated session {session_id} to 'completed'")
                                    
                                return session
                                
                            except MeasurementSession.DoesNotExist:
                                self.stderr.write(f"Error: Session {session_id} not found")
                                return None
                                    
                            except Exception as e:
                                self.stderr.write(f"Error updating session {session_id}: {str(e)}")
                                import traceback
                                self.stderr.write(traceback.format_exc())
                                return
                            
                        except json.JSONDecodeError as e:
                            self.stderr.write(f"Failed to decode JSON: {e}")
                            return
                        except Exception as e:
                            self.stderr.write(f"Error processing session: {e}")
                            import traceback
                            self.stderr.write(traceback.format_exc())
                            return
                        
                        # If session is None, it means we should skip processing
                        if session is None:
                            return
                            
                        # Only process data if session is not already completed
                        if session.status == 'completed':
                            self.stdout.write(f"Session {session_id} is already completed. No more data will be processed.")
                            return
                            
                        # Create spectral point if we have the data
                        if 'wavelength' in data and 'intensity' in data and session is not None:
                            try:
                                wavelength = float(data.get('wavelength'))
                                intensity = float(data.get('intensity'))
                                                              # Check if this exact data point already exists to prevent duplicates
                                existing_point = SpectralPoint.objects.filter(
                                    session=session,
                                    wavelength=float(data['wavelength']),
                                    intensity=float(data['intensity'])
                                ).first()
                                
                                if not existing_point:
                                    # Create spectral point if it doesn't exist
                                    SpectralPoint.objects.create(
                                        session=session,
                                        wavelength=float(data['wavelength']),
                                        intensity=float(data['intensity']),
                                        timestamp=timezone.now()
                                    )
                                    self.stdout.write(f"Added new data point to session {session_id}")
                                    
                                    # Update session status to completed after first successful data point
                                    with connection.cursor() as cursor:
                                        cursor.execute(
                                            """
                                            UPDATE patients_measurementsession 
                                            SET status = 'completed', updated_at = NOW() 
                                            WHERE session_id = %s
                                            RETURNING status
                                            """, 
                                            [str(session_id)]
                                        )
                                        result = cursor.fetchone()
                                        self.stdout.write(f"Database update result for session {session_id}: {result}")
                                
                                    # Also update the local session object
                                    session.status = 'completed'
                                    session.save(update_fields=['status', 'updated_at'])
                                    self.stdout.write(f"Marked session {session_id} as completed")
                                    
                                    # Notify WebSocket clients
                                    self.notify_websocket(session_id, 'data_update')
                                    
                                    # Unsubscribe from this specific topic after first successful data point
                                    topic = f"{device_id}/{session_id}/measurements"
                                    c.unsubscribe(topic)
                                    self.stdout.write(f"Unsubscribed from topic: {topic} after successful data processing")
                                else:
                                    self.stdout.write(f"Skipping duplicate data point for session {session_id}")
                                    
                                    # Even if it's a duplicate, if we have data, we should mark as completed
                                    if session.status != 'completed':
                                        session.status = 'completed'
                                        session.save(update_fields=['status', 'updated_at'])
                                        self.stdout.write(f"Marked session {session_id} as completed (duplicate data)")
                                
                                self.stdout.write(f"Processing completed for session {session_id}")
                                
                        session.refresh_from_db()
                        self.stdout.write(f"Final session status: {session.status}")
                        
                    except Exception as e:
                        self.stderr.write(f'Error processing data: {str(e)}')
                        import traceback
                        self.stderr.write(traceback.format_exc())
                else:
                    self.stderr.write(f'Unhandled topic format: {msg.topic}')
                    
            except json.JSONDecodeError:
                self.stderr.write(f'Failed to decode JSON: {msg.payload}')
                import traceback
                self.stderr.write(traceback.format_exc())
            except Exception as e:
                self.stderr.write(f'Unexpected error in on_message: {str(e)}')
                import traceback
                self.stderr.write(traceback.format_exc())

        client.on_connect = on_connect
        client.on_message = on_message
        
        try:
            client.connect(broker, port, 60)
            self.stdout.write(self.style.SUCCESS('Starting MQTT loop...'))
            client.loop_forever()
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'MQTT Error: {str(e)}'))
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('Stopping MQTT consumer...'))
        finally:
            client.disconnect()
    
    def _send_ws_update(self, session):
        """Send WebSocket update for the session"""
        try:
            channel_layer = get_channel_layer()
            point_count = session.spectra.count()
            
            # Log the update for debugging
            self.stdout.write(f'Sending WebSocket update for session {session.session_id}: status={session.status}, points={point_count}')
            
            async_to_sync(channel_layer.group_send)(
                f'session_{session.session_id}',
                {
                    'type': 'session_update',
                    'session_id': str(session.session_id),
                    'status': session.status,
                    'point_count': point_count,
                    'last_updated': session.updated_at.isoformat()
                }
            )
        except Exception as e:
            self.stderr.write(f'WebSocket error: {str(e)}')
            import traceback
            self.stderr.write(traceback.format_exc())
