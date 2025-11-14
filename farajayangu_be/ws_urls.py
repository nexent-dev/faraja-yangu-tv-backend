from django.urls import path
from socket_consumers import VideoStreamConsumer

ws_urlpatterns = [
    path("socket/v-stream/<int:video_id>/", VideoStreamConsumer.as_asgi()),
]