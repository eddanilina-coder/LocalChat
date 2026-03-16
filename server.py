import asyncio
import logging
import threading

from localchat.http_server import start_http_server
from localchat.ws import start_ws_server


logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
)


def main() -> None:
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()
    asyncio.run(start_ws_server())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Server stopped by user")

