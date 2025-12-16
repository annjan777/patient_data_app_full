import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .models import MeasurementSession

class SessionConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.session_id = self.scope['url_route']['kwargs']['session_id']
        self.room_group_name = f'session_{self.session_id}'

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

        # Send current session status
        session = await self.get_session()
        if session:
            await self.send(text_data=json.dumps({
                'type': 'session_update',
                'session_id': str(session.session_id),
                'status': session.status,
                'point_count': await self.get_point_count(session)
            }))

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        data = json.loads(text_data)
        message = data.get('message')
        
        if message == 'update_status':
            # Get the latest session status
            try:
                session = MeasurementSession.objects.get(session_id=self.session_id)
                # Send updated status to the group
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'status_update',
                        'status': session.status,
                        'has_data': session.spectra.exists()
                    }
                )
            except MeasurementSession.DoesNotExist:
                pass
        elif message:
            # Handle regular messages
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'session_message',
                    'message': message
                }
            )

    # Receive message from room group
    async def session_message(self, event):
        message = event['message']
        await self.send(text_data=json.dumps({
            'type': 'message',
            'message': message
        }))
        
    # Handle status updates
    async def status_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'status_update',
            'status': event['status'],
            'has_data': event['has_data']
        }))

    async def session_update(self, event):
        # Send message to WebSocket
        await self.send(text_data=json.dumps(event))

    @database_sync_to_async
    def get_session(self):
        try:
            return MeasurementSession.objects.get(session_id=self.session_id)
        except MeasurementSession.DoesNotExist:
            return None

    @database_sync_to_async
    def get_point_count(self, session):
        return session.spectra.count()
