.PHONY: help up down logs ps build shell-backend shell-db migrate seed reset-db demo test clean

.DEFAULT_GOAL := help

CYAN := \033[36m
RESET := \033[0m

help: ## Show this help
	@echo "AI Quote & Procurement Platform"
	@echo ""
	@echo "Brzi start:"
	@echo "  $(CYAN)make demo$(RESET)        — otvori HTML prototip u browseru (bez ičega)"
	@echo "  $(CYAN)make up$(RESET)          — pokreni cijeli stack (Postgres + backend + frontend)"
	@echo ""
	@echo "Svi taskovi:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  $(CYAN)%-16s$(RESET) %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# -----------------------------------------------------------------------------
# Demo mode (bez Dockera)
# -----------------------------------------------------------------------------
demo: ## Otvori HTML prototip u browseru (zero deps)
	@echo "Otvaram frontend/index.html..."
	@which xdg-open >/dev/null 2>&1 && xdg-open frontend/index.html || \
	 which open >/dev/null 2>&1 && open frontend/index.html || \
	 echo "Otvori frontend/index.html ručno u browseru"

# -----------------------------------------------------------------------------
# Docker Compose
# -----------------------------------------------------------------------------
up: ## Pokreni Postgres + backend (frontend se servira statički)
	@if [ ! -f .env ]; then cp .env.example .env; echo "Kreiran .env od templatea"; fi
	docker compose up -d
	@echo ""
	@echo "  App:        http://localhost:8000"
	@echo "  API docs:   http://localhost:8000/api/docs"
	@echo "  Postgres:   localhost:5432  (postgres/postgres)"
	@echo ""

down: ## Zaustavi sve servise
	docker compose down

restart: ## Restart svih servisa
	docker compose restart

build: ## Rebuild Docker images
	docker compose build

ps: ## Lista pokrenutih kontejnera
	docker compose ps

logs: ## Tail svih logova
	docker compose logs -f

logs-backend: ## Tail backend logova
	docker compose logs -f backend

# -----------------------------------------------------------------------------
# Baza podataka
# -----------------------------------------------------------------------------
shell-db: ## psql u Postgres (host: postgres, db: quote_platform)
	docker compose exec postgres psql -U postgres -d quote_platform

reset-db: ## DROP i ponovno učitaj schema + seed (PAŽNJA: gubi sve)
	@read -p "Brišem bazu. Sigurno? [y/N] " ans && [ "$$ans" = "y" ]
	docker compose down -v
	docker compose up -d postgres
	@echo "Čekam Postgres da se podigne..."
	@sleep 6
	docker compose up -d
	@echo "Baza resetirana s svježim schema + seed podacima."

migrate: ## Pokreni Alembic migracije (kad ih bude)
	docker compose exec backend alembic upgrade head

seed: ## Učitaj seed.sql ručno (već se učita automatski na prvom up)
	cat db/seed.sql | docker compose exec -T postgres psql -U postgres -d quote_platform

# -----------------------------------------------------------------------------
# Shells & dev
# -----------------------------------------------------------------------------
shell-backend: ## Bash u backend kontejneru
	docker compose exec backend bash

test: ## Pokreni backend testove
	docker compose exec backend pytest -v

lint: ## Lint backend
	docker compose exec backend ruff check app/

format: ## Auto-format backend
	docker compose exec backend ruff format app/

# -----------------------------------------------------------------------------
# Cleanup
# -----------------------------------------------------------------------------
clean: ## Briši kontejnere + volume-ove (PAŽNJA: briše bazu)
	@read -p "Briše sve podatke. Sigurno? [y/N] " ans && [ "$$ans" = "y" ]
	docker compose down -v
