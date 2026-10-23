.PHONY: help install test lint format serve frontend-install frontend-dev frontend-build docker-build docker-up docker-down
help:
	@echo 'install, test, lint, format, serve, frontend-install, frontend-dev, frontend-build, docker-build, docker-up, docker-down'
install:
	bash scripts/setup-rust-duckdb.sh
	cargo build --release --locked
test:
	cargo test --all-targets --locked
	node --test rust/crashes-server/tests/admin-ui.test.cjs frontend/tests/export-api.test.cjs
lint:
	cargo fmt --all -- --check
	cargo clippy --all-targets --all-features --locked -- -D warnings
format:
	cargo fmt --all
serve:
	cargo run --release --locked -- serve
frontend-install:
	npm --prefix frontend ci
frontend-dev:
	npm --prefix frontend run dev
frontend-build:
	npm --prefix frontend run build
docker-build:
	docker build -f docker/Dockerfile.rust -t chicago-crashes-rust:local .
docker-up:
	docker compose -f docker/docker-compose.rust.yml up -d --build
docker-down:
	docker compose -f docker/docker-compose.rust.yml down
