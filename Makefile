# Comandos para Docker Compose

up:
	docker compose up -d
build:
	docker compose build
down:
	docker compose down
down-vol:
	docker compose down -v
logs:
	docker compose logs -f --tail=100
stop:
	docker compose stop

# Comandos para Django

migrations:
	docker compose exec ms python manage.py makemigrations
migrate:
	docker compose exec ms python manage.py migrate
createsuperuser:
	docker compose exec ms python manage.py createsuperuser
shell:
	docker compose exec ms bash

# Comandos para CI

ci-up:
	docker network create coleta-observability 2>/dev/null || true
	docker compose up -d --wait
check:
	docker compose run --rm ms python manage.py check
migrations-check:
	docker compose run --rm ms python manage.py makemigrations --check --dry-run
