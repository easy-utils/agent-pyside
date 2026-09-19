# Easy Agent — PySide6 (Python) client. Qt needs a platform plugin to render;
# on a headless host use `QT_QPA_PLATFORM=offscreen` (import/smoke checks only).
.PHONY: install run test

VENV ?= .venv

install:
	uv venv $(VENV)
	uv pip install --python $(VENV)/bin/python -e .

run: install
	$(VENV)/bin/python -m agent_pyside.app

test: install
	QT_QPA_PLATFORM=offscreen $(VENV)/bin/python -c "import agent_pyside.agent, agent_pyside.app"
