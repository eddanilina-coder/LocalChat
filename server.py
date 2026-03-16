import asyncio
import json
import logging
import time
import uuid
from typing import Dict, Set

import websockets
from websockets.server import WebSocketServerProtocol


logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
)


HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8000

WS_HOST = "0.0.0.0"
WS_PORT = 8765
WS_PATH = "/ws"

HISTORY_LIMIT = 100


with open("index.html", "rb") as f:
    INDEX_HTML_BYTES = f.read()


class ChatServer:
    def __init__(self) -> None:
        self.active_clients: Set[WebSocketServerProtocol] = set()
        self.client_info: Dict[WebSocketServerProtocol, Dict[str, str]] = {}
        self.history = []

    async def register(self, ws: WebSocketServerProtocol) -> None:
        self.active_clients.add(ws)
        logging.info("Client connected: %s", ws.remote_address)

    async def unregister(self, ws: WebSocketServerProtocol) -> None:
        self.active_clients.discard(ws)
        info = self.client_info.pop(ws, None)
        if info:
            await self.broadcast_system(f"{info['nickname']} вышел из чата")
            await self.broadcast_users()
        logging.info("Client disconnected: %s", ws.remote_address)

    async def broadcast(self, message: dict) -> None:
        if not self.active_clients:
            return
        data = json.dumps(message)
        await asyncio.gather(
            *[self._safe_send(ws, data) for ws in list(self.active_clients)],
            return_exceptions=True,
        )

    async def _safe_send(self, ws: WebSocketServerProtocol, data: str) -> None:
        try:
            await ws.send(data)
        except Exception as e:
            logging.warning("Error sending to %s: %s", ws.remote_address, e)

    async def broadcast_system(self, text: str) -> None:
        msg = {
            "type": "system",
            "payload": {
                "message": text,
                "timestamp": time.time(),
            },
        }
        await self.broadcast(msg)

    async def broadcast_users(self) -> None:
        users = [
            {"user_id": info["user_id"], "nickname": info["nickname"]}
            for info in self.client_info.values()
        ]
        msg = {
            "type": "users",
            "payload": {"users": users},
        }
        await self.broadcast(msg)

    async def send_history(self, ws: WebSocketServerProtocol) -> None:
        if not self.history:
            return
        msg = {
            "type": "history",
            "payload": {"messages": self.history},
        }
        await self._safe_send(ws, json.dumps(msg))

    async def handler(self, ws: WebSocketServerProtocol) -> None:
        await self.register(ws)
        try:
            await self._handle_client(ws)
        finally:
            await self.unregister(ws)

    async def _handle_client(self, ws: WebSocketServerProtocol) -> None:
        hello_received = False
        async for raw in ws:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await self._safe_send(
                    ws,
                    json.dumps(
                        {
                            "type": "error",
                            "payload": {"message": "Invalid JSON"},
                        }
                    ),
                )
                continue

            msg_type = data.get("type")
            payload = data.get("payload", {})

            if msg_type == "hello":
                nickname = str(payload.get("nickname", "")).strip()
                if not nickname:
                    nickname = "Гость"
                user_id = str(uuid.uuid4())
                self.client_info[ws] = {"user_id": user_id, "nickname": nickname}
                hello_received = True

                await self.send_history(ws)
                await self.broadcast_system(f"{nickname} присоединился к чату")
                await self.broadcast_users()
                continue

            if not hello_received:
                await self._safe_send(
                    ws,
                    json.dumps(
                        {
                            "type": "error",
                            "payload": {"message": "Send hello first"},
                        }
                    ),
                )
                continue

            if msg_type == "chat":
                text = str(payload.get("message", "")).strip()
                if not text:
                    continue
                if len(text) > 1000:
                    text = text[:1000]

                info = self.client_info.get(ws)
                if not info:
                    continue

                chat_msg = {
                    "type": "chat",
                    "payload": {
                        "user_id": info["user_id"],
                        "nickname": info["nickname"],
                        "message": text,
                        "timestamp": time.time(),
                    },
                }

                self.history.append(chat_msg["payload"])
                if len(self.history) > HISTORY_LIMIT:
                    self.history = self.history[-HISTORY_LIMIT:]

                await self.broadcast(chat_msg)
            else:
                await self._safe_send(
                    ws,
                    json.dumps(
                        {
                            "type": "error",
                            "payload": {"message": "Unknown message type"},
                        }
                    ),
                )


chat_server = ChatServer()


async def http_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        request_line = await reader.readline()
        if not request_line:
            writer.close()
            await writer.wait_closed()
            return

        parts = request_line.decode("latin1").strip().split()
        if len(parts) < 2:
            writer.close()
            await writer.wait_closed()
            return

        method, path = parts[0], parts[1]

        # Читаем и игнорируем заголовки до пустой строки
        while True:
            header_line = await reader.readline()
            if not header_line or header_line in (b"\r\n", b"\n"):
                break

        if method != "GET" or path != "/":
            response_body = b"Not found"
            response = (
                b"HTTP/1.1 404 Not Found\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n"
                b"Content-Length: " + str(len(response_body)).encode("ascii") + b"\r\n"
                b"Connection: close\r\n"
                b"\r\n" +
                response_body
            )
            writer.write(response)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return

        body = INDEX_HTML_BYTES
        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n"
            b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
            b"Connection: close\r\n"
            b"\r\n" +
            body
        )
        writer.write(response)
        await writer.drain()
    except Exception as e:
        logging.error("HTTP handler error: %s", e)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def main() -> None:
    http_server = await asyncio.start_server(http_handler, HTTP_HOST, HTTP_PORT)
    logging.info("HTTP server listening on %s:%d", HTTP_HOST, HTTP_PORT)

    ws_server = await websockets.serve(
        chat_server.handler,
        WS_HOST,
        WS_PORT,
        ping_interval=20,
        ping_timeout=20,
        max_size=2**20,
        process_request=None,
    )
    logging.info("WebSocket server listening on %s:%d%s", WS_HOST, WS_PORT, WS_PATH)

    async with http_server, ws_server:
        await asyncio.gather(http_server.serve_forever(), ws_server.wait_closed())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Server stopped by user")

