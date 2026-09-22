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
from .navigation import CONFIG_SUB_IDS, NavStore, PAGE_VIEWS, SIDER_TABS, SESSION_OVERLAYS

DEFAULT_BASE = "https://agent.agent.10.199.64.20.nip.io"


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
    def __init__(self, on_open, on_new, on_refresh, on_fork):
        super().__init__()
        self._on_open = on_open
        self._on_fork = on_fork

        self.list = QListWidget()
        self.list.itemClicked.connect(self._pick)
        # Right-click a row → fork (without opening).
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)

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

    def _context_menu(self, pos):
        item = self.list.itemAt(pos)
        if item is None:
            return
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.addAction("Fork", lambda: self._on_fork(item.text()))
        menu.exec(self.list.mapToGlobal(pos))

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

    def start(self, session_id: str, lines: list[dict]):
        self.title.setText(session_id)
        self.transcript.setPlainText("\n\n".join(l["text"] for l in lines))
        self._scroll()

    def append(self, text: str):
        cur = self.transcript.toPlainText()
        self.transcript.setPlainText(cur + text)
        self._scroll()

    def clear_errors(self):
        """Drop any error lines (a new send makes an error transient)."""
        text = self.transcript.toPlainText()
        kept = [ln for ln in text.split("\n") if "failed:" not in ln and "error:" not in ln]
        self.transcript.setPlainText("\n".join(kept))

    def _scroll(self):
        bar = self.transcript.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _submit(self):
        text = self.composer.text().strip()
        if not text:
            return
        self.composer.clear()
        self._on_send(text)


class ConfigPage(QWidget):
    """Config tab root + its drill-in sub-pages (appearance/backends/presets/
    tools) and the providers list — mirrors the other clients' config surface."""

    def __init__(self, on_open_sub, on_open_providers, on_back):
        super().__init__()
        self._on_open_sub = on_open_sub
        self.list = QListWidget()
        self.list.itemClicked.connect(self._pick)
        back = QPushButton("Back")
        back.clicked.connect(on_back)
        header = QHBoxLayout()
        header.addWidget(QLabel("Settings"))
        header.addStretch(1)
        header.addWidget(back)
        lay = QVBoxLayout(self)
        lay.addLayout(header)
        lay.addWidget(self.list)
        self._rows = [
            ("appearance", "Appearance"),
            ("backends", "Users / backends"),
            ("presets", "Presets"),
            ("tools", "Tools"),
            ("providers_list", "Providers"),
        ]
        for key, label in self._rows:
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, key)
            self.list.addItem(it)

    def _pick(self, item: QListWidgetItem):
        key = item.data(Qt.ItemDataRole.UserRole)
        if key == "providers_list":
            self._on_open_providers()
        else:
            self._on_open_sub(key)


class ProvidersPage(QWidget):
    def __init__(self, on_back):
        super().__init__()
        self.list = QListWidget()
        back = QPushButton("Back")
        back.clicked.connect(on_back)
        header = QHBoxLayout()
        header.addWidget(QLabel("Providers"))
        header.addStretch(1)
        header.addWidget(back)
        lay = QVBoxLayout(self)
        lay.addLayout(header)
        lay.addWidget(self.list)

    def set_providers(self, providers: list[dict]):
        self.list.clear()
        for p in providers:
            self.list.addItem(QListWidgetItem(f"{p['provider_id']} · {p['capability']}"))


class PresetFormPage(QWidget):
    def __init__(self, on_back):
        super().__init__()
        back = QPushButton("Back")
        back.clicked.connect(on_back)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Create / edit a preset"))
        lay.addWidget(back)


class ProviderFormPage(QWidget):
    def __init__(self, on_back):
        super().__init__()
        back = QPushButton("Back")
        back.clicked.connect(on_back)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Register a provider"))
        lay.addWidget(back)


class MailboxPage(QWidget):
    def __init__(self, on_back):
        super().__init__()
        self.list = QListWidget()
        back = QPushButton("Back")
        back.clicked.connect(on_back)
        header = QHBoxLayout()
        header.addWidget(QLabel("Mailbox"))
        header.addStretch(1)
        header.addWidget(back)
        lay = QVBoxLayout(self)
        lay.addLayout(header)
        lay.addWidget(self.list)

    def set_entries(self, entries: list[dict]):
        self.list.clear()
        for m in entries:
            self.list.addItem(QListWidgetItem(f"{_mailbox_label(m['msg_type'], m.get('source', ''))} · {m['status']}"))


def _error_text(params: dict) -> str:
    """The message body of a streamed `error` event."""
    e = params.get("error")
    if isinstance(e, str):
        return e
    if isinstance(e, dict) and isinstance(e.get("message"), str):
        return e["message"]
    if isinstance(params.get("message"), str):
        return params["message"]
    return "Unknown error"


def _mailbox_label(msg_type: str, source: str) -> str:
    """(msgType, source) → a human label (mirrors the other clients)."""
    if msg_type == "interrupt":
        return "Interrupt"
    if msg_type != "trigger":
        return "Event"
    if source == "user":
        return "Message"
    if source.startswith("session:"):
        return f"From session · {source[len('session:'):]}"
    if source.startswith("system:"):
        return f"From system · {source[len('system:'):]}"
    return "Message"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Easy Agent")
        self.resize(480, 820)
        self.setStyleSheet("background:#0d1117; color:#e6edf3;")

        self.nav = NavStore()
        self.nav.subscribe(self._render)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.connect_page = ConnectPage(self.do_connect)
        self.sessions_page = SessionsPage(
            self.open_session, self.new_session, self.refresh_sessions, self.fork_session
        )
        self.chat_page = ChatPage(self.send, self.back)
        self.config_page = ConfigPage(
            self.open_config_sub, self.open_providers, self.back_to_chat
        )
        self.providers_page = ProvidersPage(self.back)
        self.preset_form_page = PresetFormPage(self.back)
        self.provider_form_page = ProviderFormPage(self.back)
        self.mailbox_page = MailboxPage(self.back)
        for w in (
            self.connect_page,
            self.sessions_page,
            self.chat_page,
            self.config_page,
            self.providers_page,
            self.preset_form_page,
            self.provider_form_page,
            self.mailbox_page,
        ):
            self.stack.addWidget(w)

        self.base = ""
        self.token = ""
        self.username = ""
        self.session_id = ""
        self._watch_task: asyncio.Task | None = None

    def _render(self):
        """Dispatch the top page of the active tab (the page contract)."""
        page = self.nav.top
        kind = page["kind"]
        if kind == "chat_list":
            self.stack.setCurrentWidget(self.sessions_page)
        elif kind == "chat_session":
            self.stack.setCurrentWidget(self.chat_page)
        elif kind == "chat_overlay":
            self.stack.setCurrentWidget(self.mailbox_page)
            asyncio.ensure_future(self._load_mailbox())
        elif kind in ("config_root", "config_sub"):
            self.stack.setCurrentWidget(self.config_page)
        elif kind == "providers_list":
            self.stack.setCurrentWidget(self.providers_page)
        elif kind == "preset_form":
            self.stack.setCurrentWidget(self.preset_form_page)
        elif kind == "provider_form":
            self.stack.setCurrentWidget(self.provider_form_page)

    def open_config_sub(self, sub_id: str):
        self.nav.push(
            {"kind": "config_sub", "key": f"config_sub_{sub_id}", "id": sub_id}
        )

    def open_providers(self):
        self.nav.push({"kind": "providers_list", "key": "providers_list"})
        asyncio.ensure_future(self._load_providers())

    async def _load_mailbox(self):
        if not self.session_id:
            return
        try:
            page = await agent.mailbox(self.base, self.token, self.session_id, limit=30)
            self.mailbox_page.set_entries(page["entries"])
        except Exception:  # noqa: BLE001
            pass

    async def _load_providers(self):
        try:
            providers = await agent.list_providers(self.base, self.token)
            self.providers_page.set_providers(providers)
        except Exception:  # noqa: BLE001
            pass

    def back(self):
        self.nav.pop()

    def back_to_chat(self):
        self.nav.switch_tab("chat")

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
        self.username = await agent.resolve_username(base, token)
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

    @qasync.asyncSlot(str)
    async def fork_session(self, session_id: str):
        branch = f"fork-{agent.now_ms()}"
        try:
            await agent.fork(self.base, self.token, session_id, branch)
            await self._refresh()
        except Exception as e:  # noqa: BLE001
            self.sessions_page.set_status(f"Fork failed: {e}")

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
            elif event == "error":
                self.chat_page.append(f"\n[Model error: {_error_text(params)}]\n")

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
        # An error is TRANSIENT: a new prompt clears any prior error line.
        self.chat_page.clear_errors()
        self.chat_page.append(f"\n\nYou: {text}\n\nAgent: ")
        try:
            await agent.prompt(self.base, self.token, session_id, text)
        except Exception as e:  # noqa: BLE001
            # The title says what failed; the body is the raw error.
            self.chat_page.append(f"\n[Send failed: {e}]")


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
