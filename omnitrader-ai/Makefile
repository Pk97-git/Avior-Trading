.PHONY: up down restart logs init-db

up:
	docker-compose up -d

down:
	docker-compose down

restart: down up

logs:
	docker-compose logs -f

init-db:
	@echo "Initializing TimescaleDB and pgvector..."
    # Logic to run alembic migrations or init scripts will go here
	docker exec -it omnitrader_db psql -U omnitrader -d omnitrader_db -c "CREATE EXTENSION IF NOT EXISTS vector;"

install:
	cd backend && pip install -r requirements.txt
