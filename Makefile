.PHONY: up down seed migrate revision test lint fmt logs

up:            ## build + start the full stack
	docker compose up --build

down:          ## stop the stack
	docker compose down

seed:          ## create bootstrap Owner + Workspace
	docker compose exec backend python -m app.cli seed

migrate:       ## apply migrations
	docker compose exec backend alembic upgrade head

revision:      ## autogenerate a migration: make revision m="message"
	docker compose exec backend alembic revision --autogenerate -m "$(m)"

test:          ## run backend tests (expects TEST_DATABASE_URL)
	cd backend && . .venv/bin/activate && pytest -q

lint:          ## ruff
	cd backend && . .venv/bin/activate && ruff check .

fmt:           ## ruff --fix
	cd backend && . .venv/bin/activate && ruff check --fix .

logs:
	docker compose logs -f backend
