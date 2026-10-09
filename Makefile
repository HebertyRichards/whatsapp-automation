# Requires GNU Make (Windows: "winget install ezwinports.make" or "choco install make").
ifeq ($(OS),Windows_NT)
    VENV_PY := venv/Scripts/python.exe
    SYS_PY  := python
else
    VENV_PY := venv/bin/python
    SYS_PY  := python3
endif

PY      := $(VENV_PY)
ALEMBIC := $(VENV_PY) -m alembic

.PHONY: help venv install dev lint typecheck migrate upgrade downgrade current history

help:
	@echo "make install              Create the venv if needed and install dependencies"
	@echo "make dev                  Run the server with reload on localhost:8000"
	@echo "make lint                 ruff check"
	@echo "make typecheck            mypy (strict)"
	@echo "make migrate m=\"msg\"      Autogenerate a migration from the models"
	@echo "make upgrade              Apply pending migrations"
	@echo "make downgrade            Revert the last migration"
	@echo "make current              Show the applied revision"
	@echo "make history              List all migrations"

$(VENV_PY):
	$(SYS_PY) -m venv venv

venv: $(VENV_PY)

install: $(VENV_PY)
	$(PY) -m pip install -r requirements-dev.txt

dev:
	$(PY) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

lint:
	$(PY) -m ruff check app/ alembic/

typecheck:
	$(PY) -m mypy app/

migrate:
	$(if $(m),,$(error Usage: make migrate m="short description"))
	$(ALEMBIC) revision --autogenerate -m "$(m)"
	@echo "-> Review the file created in alembic/versions/, then run: make upgrade"

upgrade:
	$(ALEMBIC) upgrade head

downgrade:
	$(ALEMBIC) downgrade -1

current:
	$(ALEMBIC) current

history:
	$(ALEMBIC) history
