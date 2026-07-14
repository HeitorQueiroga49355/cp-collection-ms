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

# Comandos de manutencao do MongoDB

maintenance-cleanup:
	docker compose run --rm mongo-maintenance sh /maintenance/mongo_cleanup.sh

maintenance-reindex:
	docker compose run --rm mongo-maintenance sh /maintenance/mongo_index_maintenance.sh

# Relatorio de monitoramento (Python)
# Requer: pip install pymongo
# Uso: make monitor-report ARGS="--json --output /tmp/report.json"
monitor-report:
	docker compose run --rm mongo-maintenance python3 /scripts/mongo_monitoring_report.py $(ARGS)

# Comandos para CI

ci-up:
	docker network create coleta-observability 2>/dev/null || true
	docker network create coleta-shared 2>/dev/null || true
	docker compose up -d --wait
check:
	docker compose run --rm ms python manage.py check
migrations-check:
	docker compose run --rm ms python manage.py makemigrations --check --dry-run
