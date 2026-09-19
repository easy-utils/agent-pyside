"""Easy Agent — PySide6 client for the standalone agent.

Same easy-rpc (Connect) wire + generated ``agentsdk`` messages as every other
Easy Agent client. Qt runs an asyncio event loop (qasync) so every RPC is
awaited on the UI thread without blocking it.
"""

from __future__ import annotations

import asyncio
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import qasync

from . import agent

DEFAULT_BASE = "https://standalone-agent.temp.10.199.64.20.nip.io"


class ConnectPage(QWidget):
    def __init__(self, on_connect):
        super().__init__()
        self._on_connect = on_connect

        self.base = QLineEdit(DEFAULT_BASE)
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#d97706;")

        btn = QPushButton("Connect")
        btn.clicked.connect(self._submit)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(10)
        lay.addWidget(QLabel("Gateway URL"))
        lay.addWidget(self.base)
        lay.addWidget(QLabel("Token"))
        lay.addWidget(self.token)
        lay.addWidget(btn)
        lay.addWidget(self.status)
        lay.addStretch(1)

    def _submit(self):
        base = self.base.text().strip()
        token = self.token.text().strip()
        if not base or not token:
            self.status.setText("Enter both a gateway URL and a token.")
            return
        self._on_connect(base, token)

    def set_status(self, text: str):
        self.status.setText(text)


class SessionsPage(QWidget):
    def __init__(self, on_open, on_new, on_refresh):
        super().__init__()
        self._on_open = on_open

        self.list = QListWidget()
        self.list.itemClicked.connect(self._pick)

        new_btn = QPushButton("New")
        new_btn.clicked.connect(on_new)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(on_refresh)

        header = QHBoxLayout()
        header.addWidget(QLabel("Sessions"))
        header.addStretch(1)
        header.addWidget(new_btn)
        header.addWidget(refresh_btn)

        self.status = QLabel("")
        self.status.setWordWrap(True)

        lay = QVBoxLayout(self)
        lay.addLayout(header)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.status)

    def set_sessions(self, names: list[str]):
        self.list.clear()
        for n in names:
            self.list.addItem(QListWidgetItem(n))

    def _pick(self, item: QListWidgetItem):
        self._on_open(item.text())

    def set_status(self, text: str):
        self.status.setText(text)


class ChatPage(QWidget):
    def __init__(self, on_send, on_back):
        super().__init__()
        self._on_send = on_send

        self.back = QPushButton("Back")
        self.back.clicked.connect(on_back)
        self.title = QLabel("")
        self.title.setStyleSheet("font-weight:700;")

        header = QHBoxLayout()
        header.addWidget(self.back)
        header.addWidget(self.title, 1)

        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setStyleSheet(
            "background:#0d1117; color:#e6edf3; border:none;"
        )

        self.composer = QLineEdit()
        self.composer.setPlaceholderText("Message…")
        self.composer.returnPressed.connect(self._submit)
        send = QPushButton("Send")
        send.clicked.connect(self._submit)

        bottom = QHBoxLayout()
        bottom.addWidget(self.composer, 1)
        bottom.addWidget(send)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(header)
        lay.addWidget(self.transcript, 1)
        lay.addLayout(bottom)

    def start(self, session_id: str, lines: list[str]):
        self.title.setText(session_id)
        self.transcript.setPlainText("\n\n".join(lines))
        self._scroll()

    def append(self, text: str):
        cur = self.transcript.toPlainText()
        self.transcript.setPlainText(cur + text)
        self._scroll()

    def _scroll(self):
        bar = self.transcript.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _submit(self):
        text = self.composer.text().strip()
        if not text:
            return
        self.composer.clear()
        self._on_send(text)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Easy Agent")
        self.resize(480, 820)
        self.setStyleSheet("background:#0d1117; color:#e6edf3;")

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.connect_page = ConnectPage(self.do_connect)
        self.sessions_page = SessionsPage(
            self.open_session, self.new_session, self.refresh_sessions
        )
        self.chat_page = ChatPage(self.send, self.back)
        for w in (self.connect_page, self.sessions_page, self.chat_page):
            self.stack.addWidget(w)

        self.base = ""
        self.token = ""
        self.session_id = ""
        self._watch_task: asyncio.Task | None = None

    # ---- connection ----
    @qasync.asyncSlot(str, str)
    async def do_connect(self, base: str, token: str):
        self.base, self.token = base, token
        self.connect_page.set_status("Connecting…")
        try:
            await agent.connect(base, token)
        except Exception as e:  # noqa: BLE001
            self.connect_page.set_status(f"Connect failed: {e}")
            return
        self.connect_page.set_status("")
        self.stack.setCurrentWidget(self.sessions_page)
        await self._refresh()

    # ---- sessions ----
    @qasync.asyncSlot()
    async def refresh_sessions(self):
        await self._refresh()

    async def _refresh(self):
        try:
            names = await agent.list_sessions(self.base, self.token)
        except Exception as e:  # noqa: BLE001
            self.sessions_page.set_status(f"Refresh failed: {e}")
            return
        self.sessions_page.set_status("")
        self.sessions_page.set_sessions(names)

    @qasync.asyncSlot()
    async def new_session(self):
        name = f"easy-{agent.now_ms()}"
        try:
            await agent.create_session(self.base, self.token, name)
        except Exception as e:  # noqa: BLE001
            self.sessions_page.set_status(f"Create failed: {e}")
            return
        await self._refresh()

    @qasync.asyncSlot(str)
    async def open_session(self, session_id: str):
        self.session_id = session_id
        try:
            lines = await agent.list_messages(self.base, self.token, session_id, 50)
        except Exception as e:  # noqa: BLE001
            self.sessions_page.set_status(f"Load failed: {e}")
            return
        self.chat_page.start(session_id, lines)
        self.stack.setCurrentWidget(self.chat_page)
        self._start_watch(session_id)

    @qasync.asyncSlot()
    async def back(self):
        self.session_id = ""
        self._stop_watch()
        self.stack.setCurrentWidget(self.sessions_page)

    # ---- chat ----
    def _start_watch(self, session_id: str):
        self._stop_watch()

        def on_event(event: str, params: dict):
            if event == "text-delta":
                self.chat_page.append(params.get("text", ""))
            elif event == "reasoning-delta":
                self.chat_page.append(f"[reasoning] {params.get('text', '')}")
            elif event == "tool-call":
                name = params.get("toolName") or params.get("name") or "tool"
                self.chat_page.append(f"\n[tool: {name}]\n")

        async def run():
            try:
                await agent.watch_session(
                    self.base, self.token, session_id, on_event
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.chat_page.append(f"\n[stream error: {e}]")

        self._watch_task = asyncio.ensure_future(run())

    def _stop_watch(self):
        if self._watch_task is not None:
            self._watch_task.cancel()
            self._watch_task = None

    @qasync.asyncSlot(str)
    async def send(self, text: str):
        session_id = self.session_id
        if not session_id:
            return
        self.chat_page.append(f"\n\nYou: {text}\n\nAgent: ")
        try:
            await agent.prompt(self.base, self.token, session_id, text)
        except Exception as e:  # noqa: BLE001
            self.chat_page.append(f"\n[error: {e}]")


def main() -> int:
    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    win = MainWindow()
    win.show()

    with loop:
        loop.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
