"""Thin async RPC facade over the generated ``agentsdk`` messages and the
easy-rpc Python transport. Mirrors the other Easy Agent clients: same POST
paths, same application/connect+proto framing, same streamed Prompt events.
"""

from __future__ import annotations

import json
import os
import time

import httpx
from easyrpc import MODE_STD, HttpxTransport
from easyrpc import connect as easy_connect

from agentsdk.agent.v1 import agent_pb2 as pb
from agentsdk.agent.v1.agent_AgentService_easyrpc_pb2 import AgentServiceClient


def now_ms() -> int:
    return int(time.time() * 1000)


def _client(base: str, token: str) -> AgentServiceClient:
    """Build a client. ``AGENT_CA`` (a PEM path) adds a private CA — required
    for the dev cluster's self-signed *.nip.io chain."""
    base = base.strip().rstrip("/")
    cacert = os.environ.get("AGENT_CA", "").strip()
    if cacert:
        http = httpx.AsyncClient(
            verify=cacert,
            http2=True,
            timeout=httpx.Timeout(5.0, read=None),
        )
        inner = HttpxTransport(base=base, client=http)
        transport = easy_connect(base, token=token, transport=inner)
    else:
        transport = easy_connect(base, token=token, mode=MODE_STD)
    return AgentServiceClient(transport)


async def connect(base: str, token: str) -> None:
    await _client(base, token).health(pb.HealthRequest())


async def identity(base: str, token: str) -> dict:
    """The caller's resolved identity (tenant id/name + role), from the token."""
    r = await _client(base, token).getIdentity(pb.GetIdentityRequest())
    return {"tenant": r.tenant, "tenant_name": r.tenant_name, "role": r.role}


async def resolve_username(base: str, token: str) -> str:
    try:
        i = await identity(base, token)
        return i["tenant_name"] or i["tenant"]
    except Exception:
        return ""


async def list_sessions(base: str, token: str) -> list[str]:
    res = await _client(base, token).listSessions(pb.ListSessionsRequest())
    return [s.name for s in res.sessions]


async def list_presets(base: str, token: str, locale: str = "") -> list[dict]:
    res = await _client(base, token).listPresets(pb.ListPresetsRequest(locale=locale))
    return [
        {
            "id": p.id,
            "system_prompt": p.system_prompt,
            "tools": list(p.tools),
            "max_turns": p.max_turns,
            "is_system": p.is_system,
        }
        for p in res.presets
    ]


async def list_providers(base: str, token: str) -> list[dict]:
    res = await _client(base, token).listProviders(pb.ListProvidersRequest())
    return [
        {
            "provider_id": p.provider_id,
            "api_type": p.api_type,
            "base_url": p.base_url,
            "api_key": p.api_key,
            "capability": p.capability,
            "models": [{"id": m.id, "name": m.name} for m in p.models],
        }
        for p in res.providers
    ]


async def list_tools(base: str, token: str, locale: str = "") -> list[dict]:
    res = await _client(base, token).listTools(pb.ListToolsRequest(locale=locale))
    return [
        {"name": t.name, "description": t.description, "category": t.category}
        for t in res.tools
    ]


async def get_config(base: str, token: str, key: str) -> str:
    r = await _client(base, token).getConfig(pb.GetConfigRequest(key=key))
    return r.value


async def set_config(base: str, token: str, key: str, value: str) -> None:
    await _client(base, token).setConfig(pb.SetConfigRequest(key=key, value=value))


async def mailbox(
    base: str, token: str, session_id: str, before: str = "", limit: int = 0
) -> dict:
    """One page of the mailbox (NEWEST-FIRST, paged backward)."""
    r = await _client(base, token).mailbox(
        pb.MailboxRequest(id=session_id, before=before, limit=limit)
    )
    return {
        "has_more": r.has_more,
        "entries": [
            {
                "id": m.id,
                "msg_type": m.msg_type,
                "payload": m.payload,
                "status": m.status,
                "source": m.source,
            }
            for m in r.mailbox
        ],
    }


async def fork(base: str, token: str, session_id: str, branch: str) -> str:
    r = await _client(base, token).fork(pb.ForkRequest(id=session_id, name=branch))
    return r.session.name if r.session is not None else ""


async def settings(base: str, token: str, session_id: str, updates: dict) -> None:
    """Only model/preset/locale/variant are client-editable (proto v0.18)."""
    req = pb.UpdateSettingsRequest(id=session_id)
    if updates.get("model"):
        req.model = updates["model"]
    if updates.get("preset"):
        req.preset = updates["preset"]
    req.locale = updates.get("locale", "")
    req.variant = updates.get("variant", "")
    await _client(base, token).updateSettings(req)


async def create_session(base: str, token: str, name: str) -> str:
    res = await _client(base, token).createSession(
        pb.CreateSessionRequest(name=name)
    )
    if not res.session_name:
        raise RuntimeError("create_session: empty name")
    return res.session_name


async def list_messages(
    base: str, token: str, session_id: str, limit: int = 50
) -> list[dict]:
    res = await _client(base, token).listMessages(
        pb.ListMessagesRequest(id=session_id, limit=limit)
    )
    lines: list[dict] = []
    for m in res.messages:
        # A `session:{name}` user message is a hand-off from another session.
        if m.source.startswith("session:"):
            who = f"[{m.source[len('session:'):]}]"
        elif m.source.startswith("system:"):
            who = f"[system:{m.source[len('system:'):]}]"
        else:
            who = {"user": "You", "assistant": "Agent"}.get(m.role, m.role)
        for p in m.parts:
            try:
                d = json.loads(p.data) if p.data else {}
            except ValueError:
                d = {}
            if p.type in ("text", "reasoning"):
                text = d.get("text", "")
                if text.strip():
                    lines.append({"text": f"{who}: {text}", "role": m.role, "source": m.source})
            elif p.type == "tool":
                lines.append({"text": f"[tool: {d.get('name', 'tool')}]", "role": m.role, "source": m.source})
    return lines


async def prompt(base: str, token: str, session_id: str, text: str) -> None:
    """Start a turn. The Prompt stream returns as soon as the turn is accepted;
    the live turn events arrive on the WatchSession stream (see watch_session)."""
    stream = await _client(base, token).prompt(
        pb.PromptRequest(id=session_id, prompt=text)
    )
    try:
        async for _ev in stream:
            pass
    finally:
        stream.close()


async def watch_session(base: str, token: str, session_id: str, on_event) -> None:
    """Stream live session events until cancelled.

    ``on_event(event, params)`` is invoked for every frame; ``params`` is the
    decoded ``google.protobuf.Struct`` as a plain dict.
    """
    from google.protobuf.json_format import MessageToDict

    stream = await _client(base, token).watchSession(
        pb.WatchSessionRequest(id=session_id)
    )
    try:
        async for ev in stream:
            params = MessageToDict(ev.params) if ev.params is not None else {}
            on_event(ev.event, params)
    finally:
        stream.close()
