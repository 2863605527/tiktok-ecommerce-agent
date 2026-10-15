# 应用镜像（多阶段构建）
FROM python:3.11-slim AS base

WORKDIR /app

# 系统依赖（lxml 等需要编译工具，安装最小集合）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 依赖层缓存
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# 运行时镜像
FROM python:3.11-slim AS runtime

WORKDIR /app
COPY --from=base /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=base /usr/local/bin /usr/local/bin
COPY src ./src
COPY .env.example .env

EXPOSE 8000

CMD ["uvicorn", "tiktok_ecommerce.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
