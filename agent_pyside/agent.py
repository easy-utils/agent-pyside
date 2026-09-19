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


async def list_sessions(base: str, token: str) -> list[str]:
    res = await _client(base, token).listSessions(pb.ListSessionsRequest())
    return [s.name for s in res.sessions]


async def create_session(base: str, token: str, name: str) -> str:
    res = await _client(base, token).createSession(
        pb.CreateSessionRequest(name=name)
    )
    if not res.session_name:
        raise RuntimeError("create_session: empty name")
    return res.session_name


async def list_messages(
    base: str, token: str, session_id: str, limit: int = 50
) -> list[str]:
    res = await _client(base, token).listMessages(
        pb.ListMessagesRequest(id=session_id, limit=limit)
    )
    lines: list[str] = []
    for m in res.messages:
        who = {"user": "You", "assistant": "Agent"}.get(m.role, m.role)
        for p in m.parts:
            try:
                d = json.loads(p.data) if p.data else {}
            except ValueError:
                d = {}
            if p.type in ("text", "reasoning"):
                text = d.get("text", "")
                if text.strip():
                    lines.append(f"{who}: {text}")
            elif p.type == "tool":
                lines.append(f"[tool: {d.get('name', 'tool')}]")
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
