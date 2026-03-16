"""In-memory shared state for the chat server."""

from collections import deque
from typing import Deque, Dict

from websockets.server import WebSocketServerProtocol


connected: Dict[WebSocketServerProtocol, str] = {}  # websocket → username
history: Deque[dict] = deque(maxlen=50)  # последние 50 сообщений

