"""WebSocket server logic."""

import json
import logging
import time
from typing import Optional

import websockets
from websockets.server import WebSocketServerProtocol

from . import config
from .state import connected, history


async def broadcast(message: dict) -> None:
    """Рассылка сообщения всем подключённым клиентам."""
    if not connected:
        return

    data = json.dumps(message)
    to_remove = []

    for ws in list(connected.keys()):
        try:
            await ws.send(data)
        except websockets.ConnectionClosed:
            to_remove.append(ws)
        except Exception as e:  # noqa: BLE001
            logging.warning("Error sending to %s: %s", ws.remote_address, e)

    for ws in to_remove:
        connected.pop(ws, None)


async def send_user_list() -> None:
    """Отправка актуального списка онлайн-пользователей всем клиентам."""
    users = list(connected.values())
    message = {
        "type": "user_list",
        "users": users,
    }
    await broadcast(message)


async def handler(websocket: WebSocketServerProtocol) -> None:
    """Основной обработчик WebSocket-соединения."""
    username: Optional[str] = None
    logging.info("New connection from %s", websocket.remote_address)

    try:
        # Этап регистрации — ждём первый пакет {"type": "register"}
        try:
            raw = await websocket.recv()
        except websockets.ConnectionClosed:
            return

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            await websocket.send(
                json.dumps({"type": "error", "message": "Invalid JSON in register packet"})
            )
            return

        if data.get("type") != "register":
            await websocket.send(
                json.dumps({"type": "error", "message": "First message must be 'register'"})
            )
            return

        username = str(data.get("username", "")).strip()

        if not username:
            await websocket.send(
                json.dumps({"type": "error", "message": "Username must not be empty"})
            )
            return

        if len(username) > 20:
            await websocket.send(
                json.dumps(
                    {"type": "error", "message": "Username must be at most 20 characters"}
                )
            )
            return

        if username in connected.values():
            await websocket.send(
                json.dumps({"type": "error", "message": "Username is already taken"})
            )
            return

        # Успешная регистрация
        connected[websocket] = username
        logging.info("User registered: %s (%s)", username, websocket.remote_address)

        # Отправка истории новому участнику
        if history:
            await websocket.send(
                json.dumps(
                    {
                        "type": "history",
                        "messages": list(history),
                    }
                )
            )

        # Рассылка события "пользователь вошёл"
        await broadcast(
            {
                "type": "system",
                "text": f"{username} вошёл в чат",
            }
        )

        # Обновление списка онлайн для всех
        await send_user_list()

        # Подтверждение регистрации
        await websocket.send(json.dumps({"type": "registered"}))

        # Цикл приёма сообщений
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send(
                    json.dumps({"type": "error", "message": "Invalid JSON"})
                )
                continue

            msg_type = msg.get("type")

            if msg_type == "message":
                text = str(msg.get("text", "")).strip()
                if not text:
                    continue
                if len(text) > 1000:
                    text = text[:1000]

                message_entry = {
                    "username": username,
                    "text": text,
                    "time": time.time(),
                }
                history.append(message_entry)

                await broadcast(
                    {
                        "type": "message",
                        **message_entry,
                    }
                )
            else:
                await websocket.send(
                    json.dumps({"type": "error", "message": "Unknown message type"})
                )

    finally:
        # finally: очистка + уведомление об уходе + обновление списка
        if username is not None and websocket in connected:
            connected.pop(websocket, None)
            logging.info(
                "User disconnected: %s (%s)", username, websocket.remote_address
            )
            await broadcast(
                {
                    "type": "system",
                    "text": f"{username} вышел из чата",
                }
            )
            await send_user_list()


async def start_ws_server() -> None:
    """Запуск WebSocket-сервера."""
    ws_server = await websockets.serve(
        handler,
        config.WS_HOST,
        config.WS_PORT,
        ping_interval=20,
        ping_timeout=20,
        max_size=2**20,
        path=config.WS_PATH,
    )
    logging.info(
        "WebSocket server listening on %s:%d%s",
        config.WS_HOST,
        config.WS_PORT,
        config.WS_PATH,
    )

    async with ws_server:
        await ws_server.wait_closed()

