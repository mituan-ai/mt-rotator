.PHONY: backend-test frontend-test e2e test dev seed-admin seed-catalog backup restore-verify

backend-test:
	cd backend && MT_TESTING=1 uv run pytest

frontend-test:
	cd frontend && npm run typecheck && npm test && npm run build

e2e:
	cd frontend && npm run e2e

test: backend-test frontend-test

dev:
	docker compose up --build

seed-admin:
	docker compose exec api python manage.py create_admin

seed-catalog:
	docker compose exec api python manage.py seed_catalog

backup:
	./infra/backup.sh

restore-verify:
	test -n "$(BACKUP)" && ./infra/restore-verify.sh "$(BACKUP)"
