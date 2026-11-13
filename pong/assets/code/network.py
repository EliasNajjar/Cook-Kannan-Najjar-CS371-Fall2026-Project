"""Newline-delimited JSON messages shared by the client and server."""

import json
import socket
from typing import BinaryIO


def sendMessage(conn: socket.socket, message: dict) -> None:
    conn.sendall((json.dumps(message) + "\n").encode("utf-8"))


def receiveMessage(stream: BinaryIO) -> dict:
    # A buffered reader preserves extra messages and joins fragmented TCP reads.
    line = stream.readline(4097)
    if not line:
        raise EOFError("Server or player disconnected")
    if len(line) > 4096 or not line.endswith(b"\n"):
        raise ValueError("Invalid message length")
    message = json.loads(line)
    if not isinstance(message, dict):
        raise ValueError("Expected a JSON object")
    return message
