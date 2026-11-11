# syntax=docker/dockerfile:1
# One backend image; the command picks the process: api | worker | relay | scheduler | migrate | s3-init | cli | healthcheck.
# Build from the repository root:  docker build -f infra/docker/backend.Dockerfile -t facilityhub-backend .
# No secrets are baked in: every secret (FH_DB_*_PASSWORD, FH_DATA_KEY, FH_S3_*, ...) arrives as an environment variable.

FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS build
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PIP_DISABLE_PIP_VERSION_CHECK=1
RUN pip install --no-cache-dir uv==0.9.26
WORKDIR /src
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin fh
COPY --from=build /opt/venv /opt/venv
# settings.py takes REPO_ROOT as three levels above app/core: /srv/fh holds backend/ and config/ side by side.
WORKDIR /srv/fh
COPY backend/ backend/
COPY config/ config/
COPY infra/docker/entrypoint.sh /usr/local/bin/fh
COPY infra/docker/healthcheck.py infra/docker/s3-init.py /usr/local/bin/
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 FH_ENV=production
USER 10001
WORKDIR /srv/fh/backend
EXPOSE 8100
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 CMD ["python", "/usr/local/bin/healthcheck.py", "api"]
ENTRYPOINT ["fh"]
CMD ["api"]
