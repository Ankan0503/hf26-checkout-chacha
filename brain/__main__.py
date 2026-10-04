"""python -m brain  ->  starts Chacha's brain on this laptop. Restart it after changing the code."""
import socket

import uvicorn

from . import store

PORT = 8765


def lan_ip() -> str:
    """The address your phone can reach. No packet is sent; this only asks which interface would be used."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    print(
        "\n  Checkout Chacha brain"
        f"\n  On your phone, enter:  {lan_ip()}:{PORT}"
        f"\n  Pairing code:          {store.pairing_code()}\n",
        flush=True,
    )
    uvicorn.run("brain.app:app", host="0.0.0.0", port=PORT, log_level="info")
