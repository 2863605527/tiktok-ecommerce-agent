# ===== 环境 =====
PYTHON ?= python
PIP ?= pip
UVICORN ?= uvicorn

# ===== 安装 =====
.PHONY: install install-dev
install:
	$(PIP) install -e .

install-dev:
	$(PIP) install -e ".[dev]"

# ===== 质量检查 =====
.PHONY: lint format type
lint:
	ruff check src tests

format:
	ruff format src tests
	ruff check --fix src tests

type:
	mypy src

# ===== 测试 =====
.PHONY: test test-int
test:
	pytest tests/unit -m "not integration"

test-int:
	pytest tests/integration -m integration

# ===== 运行 =====
.PHONY: run serve
run:
	tiktok-agent run-selection --product "wireless earbuds" --region "US"

serve:
	tiktok-agent serve --port 8000

# ===== Docker =====
.PHONY: docker-up docker-down
docker-up:
	docker compose up -d milvus

docker-down:
	docker compose down

# ===== 检查清单 =====
.PHONY: check
check: lint type test
	@echo "✓ 全部检查通过"
