"""Hostname detection — slim wrapper for testability."""
import socket


def current_hostname() -> str:
    return socket.gethostname()
