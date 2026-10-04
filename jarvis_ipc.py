"""
JARVIS IPC Bridge
=================
Enables communication between the background daemon (jarvis.py)
and the desktop widget (jarvis_inir_widget.py) over local socket.
"""

import socket
import threading
import json
import time

IPC_HOST = "127.0.0.1"
IPC_PORT = 49152


class JarvisIPCServer:
    """Runs inside jarvis.py to broadcast events to the widget and receive commands."""

    def __init__(self, on_command_callback=None):
        self.on_command = on_command_callback
        self.clients = []
        self.running = True
        self.lock = threading.Lock()

        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_sock.bind((IPC_HOST, IPC_PORT))
            self.server_sock.listen(5)
            threading.Thread(target=self._accept_loop, daemon=True).start()
            print(f"[IPC] Server listening on {IPC_HOST}:{IPC_PORT}")
        except Exception as e:
            print(f"[IPC] Server bind error: {e}")

    def _accept_loop(self):
        while self.running:
            try:
                conn, _ = self.server_sock.accept()
                with self.lock:
                    self.clients.append(conn)
                threading.Thread(target=self._client_handler, args=(conn,), daemon=True).start()
            except Exception:
                break

    def _client_handler(self, conn):
        buffer = ""
        while self.running:
            try:
                data = conn.recv(2048)
                if not data:
                    break
                buffer += data.decode("utf-8")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.strip():
                        try:
                            msg = json.loads(line)
                            if self.on_command:
                                self.on_command(msg)
                        except json.JSONDecodeError:
                            pass
            except Exception:
                break
        with self.lock:
            if conn in self.clients:
                self.clients.remove(conn)
        try:
            conn.close()
        except Exception:
            pass

    def broadcast(self, event_data: dict):
        """Send an event notification to all connected widgets."""
        payload = (json.dumps(event_data) + "\n").encode("utf-8")
        dead_clients = []
        with self.lock:
            for c in self.clients:
                try:
                    c.sendall(payload)
                except Exception:
                    dead_clients.append(c)
            for dc in dead_clients:
                if dc in self.clients:
                    self.clients.remove(dc)

    def close(self):
        self.running = False
        try:
            self.server_sock.close()
        except Exception:
            pass


class JarvisIPCClient:
    """Runs inside the widget to connect to jarvis.py daemon."""

    def __init__(self, on_event_callback=None):
        self.on_event = on_event_callback
        self.sock = None
        self.connected = False
        self.running = True
        threading.Thread(target=self._connection_loop, daemon=True).start()

    def _connection_loop(self):
        while self.running:
            if not self.connected:
                try:
                    self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.sock.connect((IPC_HOST, IPC_PORT))
                    self.connected = True
                    print("[IPC] Connected to background JARVIS daemon!")
                    if self.on_event:
                        self.on_event({"event": "daemon_connected"})
                    self._read_loop()
                except Exception:
                    self.connected = False
                    time.sleep(1.0)
            else:
                time.sleep(1.0)

    def _read_loop(self):
        buffer = ""
        while self.running and self.connected:
            try:
                data = self.sock.recv(2048)
                if not data:
                    break
                buffer += data.decode("utf-8")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.strip():
                        try:
                            event = json.loads(line)
                            if self.on_event:
                                self.on_event(event)
                        except json.JSONDecodeError:
                            pass
            except Exception:
                break
        self.connected = False
        if self.on_event:
            self.on_event({"event": "daemon_disconnected"})

    def send_command(self, cmd_data: dict) -> bool:
        """Send command to background jarvis.py daemon."""
        if not self.connected or not self.sock:
            return False
        try:
            payload = (json.dumps(cmd_data) + "\n").encode("utf-8")
            self.sock.sendall(payload)
            return True
        except Exception:
            self.connected = False
            return False

    def close(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
