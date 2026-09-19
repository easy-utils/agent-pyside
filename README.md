# agent-pyside

**Easy Agent** — desktop client in Python using [PySide6](https://doc.qt.io/qtforpython/)
(Qt 6), over the same easy-rpc (Connect) wire as every other Easy Agent client.

It consumes the generated [`agent-sdk-python`](https://github.com/easy-utils/agent-sdk-python)
client and the [`easy-rpc-python`](https://github.com/easy-utils/easy-rpc-python)
transport; Qt runs an asyncio loop via [qasync](https://github.com/CabbageDevelopment/qasync).

```bash
make run            # or: QT_QPA_PLATFORM=offscreen python -m agent_pyside.app
```

Connect with the standalone agent's base URL + a tenant token, list sessions,
open a chat, and stream a prompt turn (`text-delta`, `reasoning-delta`,
`tool-call`).
