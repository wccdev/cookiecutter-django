ARG PYTHON_VERSION=3.11-slim-bullseye

# define an alias for the specfic python version used in this file.
FROM python:${PYTHON_VERSION} as python

# Python build stage
FROM python as python-build-stage

ARG BUILD_ENVIRONMENT=production
ARG DEBIAN_FRONTEND=noninteractive
ARG APP_HOME=/app
WORKDIR ${APP_HOME}

ENV BUILD_ENV=${BUILD_ENVIRONMENT} \
    # python:
    PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PYTHONDONTWRITEBYTECODE=1 \
    # pip:
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    # poetry:
    POETRY_VERSION=1.3.1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_CACHE_DIR="/var/cache/pypoetry" \
    POETRY_HOME="/etc/poetry" \
    PATH="/etc/poetry/bin:$PATH" \
    # system:
    LANG=C.UTF-8 \
    TZ=Asia/Shanghai


# Install apt packages
RUN apt-get update && apt-get install --no-install-recommends -y \
  # dependencies for building Python packages
  build-essential \
  # psycopg2 dependencies
  libpq-dev \
  # used to install poetry
  curl \
  # Translations dependencies
  gettext \
  # Installing `poetry` package manager:
  # https://github.com/python-poetry/poetry
  && curl -sSL "https://install.python-poetry.org" | python3 - \
  && echo $PATH \
  && poetry --version \
  # cleaning up unused files
  && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
  && rm -rf /var/lib/apt/lists/*


# Requirements are installed here to ensure they will be cached.
COPY ./poetry.lock ./pyproject.toml ./

# use poetry to install python dependencies
RUN  poetry install \
  $(if [ "$BUILD_ENVIRONMENT" = 'production' ]; then echo '--only main,production'; fi) \
  --no-interaction --no-ansi --no-root \
  # Cleaning poetry installation's cache for production:
  && if [ "$BUILD_ENVIRONMENT" = 'production' ]; then rm -rf "$POETRY_CACHE_DIR"; fi
