"""Navigation model — port of the Flutter/Compose/webui contract.

Two side tabs, each with its own page stack. Page keys and config sub-ids are
identical to every other Easy Agent client (guarded by tools/pages.py), so a
page added here must be added everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

SIDER_TABS = ["chat", "config"]
CONFIG_SUB_IDS = ["appearance", "backends", "presets", "tools"]
SESSION_OVERLAYS = ["mailbox"]

# Static page keys -> the view that dispatches them.
PAGE_VIEWS = {
    "chat_list": "SessionsPage",
    "chat_session": "ChatPage",
    "chat_overlay": "MailboxPage",
    "config_root": "ConfigPage",
    "providers_list": "ProvidersPage",
    "preset_form_new": "PresetFormPage",
    "provider_form": "ProviderFormPage",
}


def root_key(tab: str) -> str:
    return "chat_list" if tab == "chat" else "config_root"


class NavStore:
    """Per-tab page stacks with the same push/pop semantics as the other clients."""

    def __init__(self) -> None:
        self.stacks: dict[str, list[dict]] = {
            "chat": [{"kind": "chat_list", "key": "chat_list"}],
            "config": [{"kind": "config_root", "key": "config_root"}],
        }
        self.tab = "chat"
        self.active_session_id = ""
        self._listeners: list = []

    def subscribe(self, fn) -> None:
        self._listeners.append(fn)

    def _emit(self) -> None:
        for fn in self._listeners:
            fn()

    def switch_tab(self, tab: str) -> None:
        self.tab = tab
        self._emit()

    @property
    def top(self) -> dict:
        return self.stacks[self.tab][-1]

    def push(self, page: dict) -> None:
        self.stacks[self.tab].append(page)
        self._emit()

    def pop(self) -> None:
        if len(self.stacks[self.tab]) > 1:
            self.stacks[self.tab].pop()
            self._emit()
