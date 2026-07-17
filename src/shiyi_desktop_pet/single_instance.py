"""Windows single-instance ownership and newline-delimited local IPC."""

from __future__ import annotations

import ctypes
import logging
import sys
import time
from collections.abc import Callable

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


MUTEX_NAME = r"Local\ShiyiDesktopPet.Singleton.v1"
SERVER_NAME = "ShiyiDesktopPet.IPC.v1"
ERROR_ALREADY_EXISTS = 183
_VALID_COMMANDS = frozenset({"activate", "quit"})
_LOGGER = logging.getLogger(__name__)


class _WindowsMutex:
    """Own a named Win32 mutex without waiting on another process."""

    def __init__(self, name: str) -> None:
        if sys.platform != "win32":
            raise OSError("the desktop application is supported only on Windows")

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._release = kernel32.ReleaseMutex
        self._release.argtypes = (ctypes.c_void_p,)
        self._release.restype = ctypes.c_int
        self._close = kernel32.CloseHandle
        self._close.argtypes = (ctypes.c_void_p,)
        self._close.restype = ctypes.c_int
        create = kernel32.CreateMutexW
        create.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
        create.restype = ctypes.c_void_p

        ctypes.set_last_error(0)
        self._handle = create(None, True, name)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.already_exists = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
        self._owns_mutex = not self.already_exists

    def close(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        if self._owns_mutex:
            self._release(handle)
        self._close(handle)


class SingleInstanceGuard(QObject):
    """Acquire application ownership or send a command to the current owner."""

    command_received = Signal(str)

    def __init__(
        self,
        instance_name: str = MUTEX_NAME,
        *,
        server_name: str | None = None,
        timeout_ms: int = 1_000,
        mutex_factory: Callable[[str], object] = _WindowsMutex,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if not instance_name:
            raise ValueError("instance_name must not be empty")
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        self.instance_name = instance_name
        self.server_name = server_name or (
            SERVER_NAME if instance_name == MUTEX_NAME else f"{instance_name}.IPC"
        )
        self.timeout_ms = timeout_ms
        self._mutex_factory = mutex_factory
        self._mutex: object | None = None
        self._server: QLocalServer | None = None
        self._sockets: dict[int, QLocalSocket] = {}
        self._buffers: dict[int, bytearray] = {}
        self._owner = False
        self.last_delivery_succeeded: bool | None = None

    @property
    def is_owner(self) -> bool:
        return self._owner

    def acquire(self, command: str = "activate") -> bool:
        if command not in _VALID_COMMANDS:
            raise ValueError(f"unsupported IPC command: {command}")
        if self._owner:
            return True
        if self._mutex is not None:
            return False

        mutex = self._mutex_factory(self.instance_name)
        self._mutex = mutex
        if bool(getattr(mutex, "already_exists", False)):
            try:
                self.last_delivery_succeeded = self._send(command)
            finally:
                mutex.close()
                self._mutex = None
            return False

        server = QLocalServer(self)
        QLocalServer.removeServer(self.server_name)
        if not server.listen(self.server_name):
            error = server.errorString()
            mutex.close()
            self._mutex = None
            raise OSError(f"could not listen on local IPC server: {error}")
        server.newConnection.connect(self._accept_connections)
        self._server = server
        self._owner = True
        return True

    def _send(self, command: str) -> bool:
        deadline = time.monotonic() + self.timeout_ms / 1000.0
        while True:
            remaining_ms = self._remaining_ms(deadline)
            if remaining_ms <= 0:
                _LOGGER.warning("Could not connect to the running desktop-pet instance")
                return False

            socket = QLocalSocket()
            socket.connectToServer(self.server_name)
            if socket.waitForConnected(min(50, remaining_ms)):
                return self._send_connected(socket, command, deadline)
            socket.abort()
            remaining_ms = self._remaining_ms(deadline)
            if remaining_ms > 0:
                self._wait_with_events(min(10, remaining_ms))

    def _send_connected(
        self,
        socket: QLocalSocket,
        command: str,
        deadline: float,
    ) -> bool:
        delivered = False
        try:
            if socket.write(f"{command}\n".encode("utf-8")) < 0:
                _LOGGER.warning("Could not deliver command to the desktop-pet instance")
                return False
            socket.flush()
            # This also makes two guards deterministic when exercised in one
            # process: the owner can accept and drain its local socket before
            # this short-lived sender is destroyed.
            while socket.bytesToWrite() and self._remaining_ms(deadline) > 0:
                QCoreApplication.processEvents()
                socket.flush()
                if socket.bytesToWrite():
                    self._wait_with_events(
                        min(5, self._remaining_ms(deadline))
                    )
            if socket.bytesToWrite():
                _LOGGER.warning("Could not flush command to the desktop-pet instance")
                return False
            delivered = True
            socket.disconnectFromServer()
            return True
        finally:
            if not delivered:
                socket.abort()

    @staticmethod
    def _remaining_ms(deadline: float) -> int:
        return max(0, int((deadline - time.monotonic()) * 1_000))

    @staticmethod
    def _wait_with_events(milliseconds: int) -> None:
        if milliseconds <= 0:
            return
        if QCoreApplication.instance() is None:
            time.sleep(milliseconds / 1_000.0)
            return
        loop = QEventLoop()
        QTimer.singleShot(milliseconds, loop.quit)
        loop.exec()

    def _accept_connections(self) -> None:
        server = self._server
        if server is None:
            return
        while server.hasPendingConnections():
            socket = server.nextPendingConnection()
            if socket is None:
                continue
            key = id(socket)
            self._sockets[key] = socket
            self._buffers[key] = bytearray()
            socket.readyRead.connect(lambda current=socket: self._read_socket(current))
            socket.disconnected.connect(lambda current=socket: self._drop_socket(current))
            self._read_socket(socket)

    def _read_socket(self, socket: QLocalSocket) -> None:
        key = id(socket)
        buffer = self._buffers.get(key)
        if buffer is None:
            return
        buffer.extend(bytes(socket.readAll()))
        if len(buffer) > 4_096:
            socket.abort()
            self._drop_socket(socket)
            return
        while b"\n" in buffer:
            raw, _, remainder = buffer.partition(b"\n")
            buffer[:] = remainder
            try:
                command = raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                continue
            if command in _VALID_COMMANDS:
                self.command_received.emit(command)

    def _drop_socket(self, socket: QLocalSocket) -> None:
        key = id(socket)
        self._buffers.pop(key, None)
        self._sockets.pop(key, None)

    def close(self) -> None:
        for socket in tuple(self._sockets.values()):
            try:
                socket.readyRead.disconnect()
                socket.disconnected.disconnect()
            except RuntimeError:
                pass
            socket.abort()
        self._sockets.clear()
        self._buffers.clear()

        server = self._server
        self._server = None
        if server is not None:
            try:
                server.newConnection.disconnect()
            except RuntimeError:
                pass
            server.close()
            QLocalServer.removeServer(self.server_name)

        mutex = self._mutex
        self._mutex = None
        if mutex is not None:
            mutex.close()
        self._owner = False
