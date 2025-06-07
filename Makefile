# OCR Platform - Makefile
# =====================
# Automatização de comandos para desenvolvimento e deployment

.PHONY: help install install-dev test clean lint format type-check security-check
.PHONY: start-api start-workers start-redis start-flower stop-all
.PHONY: docker-build docker-run docker-stop docker-clean
.PHONY: backup restore monitor benchmark
.PHONY: setup-dev setup-prod migrate seed-data
.DEFAULT_GOAL := help

# Variáveis
PYTHON := python3
PIP := pip3
DOCKER := docker
DOCKER_COMPOSE := docker-compose
PROJECT_NAME := ocr-platform
VERSION := 2.0.0

# Cores para output
RED := \033[0;31m
GREEN := \033[0;32m
YELLOW := \033[1;33m
BLUE := \033[0;34m
NC := \033[0m # No Color

help: ## Mostra esta ajuda
	@echo "$(BLUE)OCR Platform v$(VERSION) - Comandos Disponíveis$(NC)"
	@echo "=================================================="
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "$(YELLOW)%-20s$(NC) %s\n", $$1, $$2}'

# =============================================================================
# INSTALAÇÃO E CONFIGURAÇÃO
# =============================================================================

install: ## Instala dependências base
	@echo "$(GREEN)Installing base dependencies...$(NC)"
	$(PIP) install -r requirements/base.txt

install-dev: ## Instala dependências de desenvolvimento
	@echo "$(GREEN)Installing development dependencies...$(NC)"
	$(PIP) install -r requirements/dev.txt
	$(PIP) install -r requirements/base.txt
	$(PIP) install -r requirements/api.txt
	$(PIP) install -r requirements/workers.txt

install-api: ## Instala dependências da API
	@echo "$(GREEN)Installing API dependencies...$(NC)"
	$(PIP) install -r requirements/base.txt
	$(PIP) install -r requirements/api.txt

install-workers: ## Instala dependências dos workers
	@echo "$(GREEN)Installing worker dependencies...$(NC)"
	$(PIP) install -r requirements/base.txt
	$(PIP) install -r requirements/workers.txt

install-trocr: ## Instala dependências específicas do TrOCR
	@echo "$(GREEN)Installing TrOCR dependencies...$(NC)"
	$(PIP) install -r requirements/trocr.txt

install-surya: ## Instala dependências específicas do Surya
	@echo "$(GREEN)Installing Surya dependencies...$(NC)"
	$(PIP) install -r requirements/surya.txt

setup-dev: install-dev ## Configura ambiente de desenvolvimento
	@echo "$(GREEN)Setting up development environment...$(NC)"
	cp .env.example .env
	mkdir -p uploads results temp logs
	@echo "$(YELLOW)Don't forget to configure .env file!$(NC)"

setup-prod: install ## Configura ambiente de produção
	@echo "$(GREEN)Setting up production environment...$(NC)"
	mkdir -p uploads results temp logs data/redis
	chmod 755 uploads results temp logs
	@echo "$(YELLOW)Configure production .env file!$(NC)"

# =============================================================================
# DESENVOLVIMENTO E TESTES
# =============================================================================

test: ## Executa testes
	@echo "$(GREEN)Running tests...$(NC)"
	$(PYTHON) -m pytest tests/ -v --tb=short

test-coverage: ## Executa testes com coverage
	@echo "$(GREEN)Running tests with coverage...$(NC)"
	$(PYTHON) -m pytest tests/ --cov=app --cov-report=html --cov-report=term

lint: ## Verifica código com flake8
	@echo "$(GREEN)Running linter...$(NC)"
	$(PYTHON) -m flake8 app/ scripts/ tests/

format: ## Formata código com black
	@echo "$(GREEN)Formatting code...$(NC)"
	$(PYTHON) -m black app/ scripts/ tests/

format-check: ## Verifica formatação sem alterar
	@echo "$(GREEN)Checking code format...$(NC)"
	$(PYTHON) -m black --check app/ scripts/ tests/

type-check: ## Verifica tipos com mypy
	@echo "$(GREEN)Checking types...$(NC)"
	$(PYTHON) -m mypy app/

security-check: ## Verifica segurança com bandit
	@echo "$(GREEN)Running security check...$(NC)"
	$(PYTHON) -m bandit -r app/ -f json -o security-report.json

clean: ## Limpa arquivos temporários
	@echo "$(GREEN)Cleaning temporary files...$(NC)"
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf build/ dist/ .coverage htmlcov/ .pytest_cache/
	rm -rf temp/* uploads/* results/*

# =============================================================================
# EXECUÇÃO LOCAL
# =============================================================================

start-redis: ## Inicia Redis local
	@echo "$(GREEN)Starting Redis...$(NC)"
	redis-server --daemonize yes --port 6379

stop-redis: ## Para Redis local
	@echo "$(GREEN)Stopping Redis...$(NC)"
	redis-cli shutdown

start-api: ## Inicia API FastAPI
	@echo "$(GREEN)Starting OCR Platform API...$(NC)"
	$(PYTHON) scripts/start_api.py

start-workers: ## Inicia workers Celery
	@echo "$(GREEN)Starting OCR Workers...$(NC)"
	$(PYTHON) scripts/start_workers.py

start-worker-type: ## Inicia worker específico (use: make start-worker-type TYPE=trocr)
	@echo "$(GREEN)Starting $(TYPE) worker...$(NC)"
	celery -A app.core.celery_app worker --loglevel=info --queues=$(TYPE)_queue --concurrency=2

start-flower: ## Inicia Flower para monitoramento
	@echo "$(GREEN)Starting Flower monitoring...$(NC)"
	celery -A app.core.celery_app flower --port=5555

start-all: start-redis start-api start-workers ## Inicia todos os serviços

stop-all: ## Para todos os serviços
	@echo "$(GREEN)Stopping all services...$(NC)"
	pkill -f "celery.*worker" || true
	pkill -f "uvicorn.*app.api.main:app" || true
	pkill -f "flower" || true

# =============================================================================
# DOCKER
# =============================================================================

docker-build: ## Constrói todas as imagens Docker
	@echo "$(GREEN)Building Docker images...$(NC)"
	$(DOCKER) build -f docker/Dockerfile.api -t $(PROJECT_NAME)-api:$(VERSION) .
	$(DOCKER) build -f docker/Dockerfile.worker -t $(PROJECT_NAME)-worker:$(VERSION) .
	$(DOCKER) build -f docker/Dockerfile.trocr -t $(PROJECT_NAME)-trocr:$(VERSION) .
	$(DOCKER) build -f docker/Dockerfile.surya -t $(PROJECT_NAME)-surya:$(VERSION) .

docker-build-api: ## Constrói imagem da API
	@echo "$(GREEN)Building API Docker image...$(NC)"
	$(DOCKER) build -f docker/Dockerfile.api -t $(PROJECT_NAME)-api:$(VERSION) .

docker-build-workers: ## Constrói imagens dos workers
	@echo "$(GREEN)Building worker Docker images...$(NC)"
	$(DOCKER) build -f docker/Dockerfile.worker -t $(PROJECT_NAME)-worker:$(VERSION) .
	$(DOCKER) build -f docker/Dockerfile.trocr -t $(PROJECT_NAME)-trocr:$(VERSION) .
	$(DOCKER) build -f docker/Dockerfile.surya -t $(PROJECT_NAME)-surya:$(VERSION) .

docker-run: ## Executa stack completa com Docker Compose
	@echo "$(GREEN)Starting Docker stack...$(NC)"
	$(DOCKER_COMPOSE) up -d

docker-run-dev: ## Executa stack de desenvolvimento
	@echo "$(GREEN)Starting development Docker stack...$(NC)"
	$(DOCKER_COMPOSE) -f docker-compose.dev.yml up -d

docker-run-prod: ## Executa stack de produção
	@echo "$(GREEN)Starting production Docker stack...$(NC)"
	$(DOCKER_COMPOSE) -f docker-compose.prod.yml up -d

docker-stop: ## Para containers Docker
	@echo "$(GREEN)Stopping Docker containers...$(NC)"
	$(DOCKER_COMPOSE) down

docker-logs: ## Mostra logs dos containers
	@echo "$(GREEN)Showing Docker logs...$(NC)"
	$(DOCKER_COMPOSE) logs -f

docker-clean: ## Remove containers e imagens
	@echo "$(GREEN)Cleaning Docker resources...$(NC)"
	$(DOCKER_COMPOSE) down -v --rmi all
	$(DOCKER) system prune -f

# =============================================================================
# MONITORAMENTO E MANUTENÇÃO
# =============================================================================

monitor: ## Inicia monitoramento do sistema
	@echo "$(GREEN)Starting system monitor...$(NC)"
	$(PYTHON) scripts/monitor.py

benchmark: ## Executa benchmark de performance
	@echo "$(GREEN)Running performance benchmark...$(NC)"
	$(PYTHON) scripts/benchmark.py

health-check: ## Verifica saúde do sistema
	@echo "$(GREEN)Checking system health...$(NC)"
	curl -f http://localhost:8000/api/v1/health || exit 1

api-docs: ## Abre documentação da API
	@echo "$(GREEN)Opening API documentation...$(NC)"
	open http://localhost:8000/docs

backup: ## Faz backup dos dados
	@echo "$(GREEN)Creating backup...$(NC)"
	mkdir -p backups
	tar -czf backups/ocr-platform-backup-$(shell date +%Y%m%d_%H%M%S).tar.gz uploads/ results/ .env

restore: ## Restaura backup (use: make restore BACKUP=filename)
	@echo "$(GREEN)Restoring backup: $(BACKUP)$(NC)"
	tar -xzf backups/$(BACKUP)

# =============================================================================
# DADOS E MIGRAÇÃO
# =============================================================================

migrate: ## Executa migrações (se houver database)
	@echo "$(GREEN)Running migrations...$(NC)"
	# Placeholder para futuras migrações de database

seed-data: ## Popula dados de exemplo
	@echo "$(GREEN)Seeding example data...$(NC)"
	$(PYTHON) -c "
import requests
import os
# Upload arquivo de exemplo se API estiver rodando
try:
    response = requests.get('http://localhost:8000/api/v1/health')
    if response.status_code == 200:
        print('API is running - ready for seeding')
    else:
        print('API not available')
except:
    print('API not running - start with make start-api')
"

# =============================================================================
# UTILITÁRIOS
# =============================================================================

check-deps: ## Verifica dependências instaladas
	@echo "$(GREEN)Checking dependencies...$(NC)"
	$(PIP) check

update-deps: ## Atualiza dependências
	@echo "$(GREEN)Updating dependencies...$(NC)"
	$(PIP) install --upgrade pip
	$(PIP) install --upgrade -r requirements/base.txt

freeze-deps: ## Congela dependências atuais
	@echo "$(GREEN)Freezing current dependencies...$(NC)"
	$(PIP) freeze > requirements/frozen-$(shell date +%Y%m%d).txt

show-env: ## Mostra ambiente atual
	@echo "$(BLUE)Current Environment:$(NC)"
	@echo "Python: $(shell $(PYTHON) --version)"
	@echo "Pip: $(shell $(PIP) --version)"
	@echo "Docker: $(shell $(DOCKER) --version 2>/dev/null || echo 'Not installed')"
	@echo "Redis: $(shell redis-cli --version 2>/dev/null || echo 'Not installed')"
	@echo "Project: $(PROJECT_NAME) v$(VERSION)"

port-check: ## Verifica portas utilizadas
	@echo "$(GREEN)Checking ports...$(NC)"
	@echo "API (8000): $(shell lsof -ti:8000 >/dev/null && echo 'OCCUPIED' || echo 'FREE')"
	@echo "Redis (6379): $(shell lsof -ti:6379 >/dev/null && echo 'OCCUPIED' || echo 'FREE')"
	@echo "Flower (5555): $(shell lsof -ti:5555 >/dev/null && echo 'OCCUPIED' || echo 'FREE')"

logs: ## Mostra logs da aplicação
	@echo "$(GREEN)Showing application logs...$(NC)"
	tail -f logs/*.log 2>/dev/null || echo "No log files found in logs/"

# =============================================================================
# PRODUÇÃO
# =============================================================================

deploy: ## Deploy para produção
	@echo "$(GREEN)Deploying to production...$(NC)"
	@echo "$(YELLOW)This should be customized for your production environment$(NC)"
	# git pull
	# make install
	# make migrate
	# systemctl restart ocr-platform

init-systemd: ## Cria arquivos de serviço systemd
	@echo "$(GREEN)Creating systemd service files...$(NC)"
	sudo cp scripts/systemd/ocr-platform-api.service /etc/systemd/system/
	sudo cp scripts/systemd/ocr-platform-workers.service /etc/systemd/system/
	sudo systemctl daemon-reload

# =============================================================================
# VALIDAÇÕES
# =============================================================================

validate: test lint type-check security-check ## Executa todas as validações

pre-commit: format validate ## Executa verificações antes do commit

ci: install-dev validate test-coverage ## Pipeline de CI

cd: docker-build ## Pipeline de CD

# =============================================================================
# INFORMAÇÕES
# =============================================================================

info: ## Mostra informações do projeto
	@echo "$(BLUE)OCR Platform Information$(NC)"
	@echo "=========================="
	@echo "Version: $(VERSION)"
	@echo "Project: $(PROJECT_NAME)"
	@echo "Python: $(shell $(PYTHON) --version)"
	@echo ""
	@echo "$(BLUE)Available Engines:$(NC)"
	@echo "- TrOCR: Handwritten text recognition"
	@echo "- Surya: Layout analysis and structured documents"  
	@echo "- PaddleOCR: Fast production processing"
	@echo "- EasyOCR: General purpose multilingual"
	@echo "- Tesseract: Reliable fallback"
	@echo "- Marker: PDF to Markdown conversion"
	@echo ""
	@echo "$(BLUE)Key Directories:$(NC)"
	@echo "- app/: Application source code"
	@echo "- scripts/: Utility scripts"
	@echo "- docker/: Docker configurations"
	@echo "- requirements/: Dependency specifications"
	@echo "- tests/: Test suite"

status: ## Mostra status dos serviços
	@echo "$(GREEN)Service Status:$(NC)"
	@echo "Redis: $(shell redis-cli ping 2>/dev/null || echo 'Not running')"
	@echo "API: $(shell curl -s http://localhost:8000/ping >/dev/null && echo 'Running' || echo 'Not running')"
	@echo "Workers: $(shell pgrep -f 'celery.*worker' >/dev/null && echo 'Running' || echo 'Not running')"
	@echo "Flower: $(shell pgrep -f 'flower' >/dev/null && echo 'Running' || echo 'Not running')"