# syntax = docker/dockerfile:1.2
ARG PYTHON_VERSION=3.11-slim-bullseye
ARG POETRY_VERSION=1.5.1
ARG BUILD_ENVIRONMENT=production
ARG APP_HOME=/app

# define an alias for the specfic python version used in this file.
FROM python:${PYTHON_VERSION} as python

# Python build stage
FROM python as python-build-stage

ARG APP_HOME

ENV POETRY_VIRTUALENVS_IN_PROJECT=true
ENV PIP_INDEX_URL=https://pypi.wochacha.cn/simple/
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR ${APP_HOME}

# Install apt packages
RUN sed -i "s@http://deb.debian.org@https://mirrors.aliyun.com@g" /etc/apt/sources.list \
    && apt-get update && apt-get install -y --no-install-recommends \
    # dependencies for building Python packages
    build-essential \
    # psycopg2 dependencies
    libpq-dev


# Speed up installing poetry
RUN python3 -m pip install poetry==${POETRY_VERSION} \
    && poetry --version

# Requirements are installed here to ensure they will be cached.
COPY ./poetry.lock ./pyproject.toml ./

# Use poetry to install python dependencies
RUN  poetry install --only main,${BUILD_ENVIRONMENT} --no-interaction --no-ansi --no-root


# Python 'run' stage
FROM python as python-run-stage

ARG BUILD_ENVIRONMENT
ARG APP_HOME

ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE 1
ENV BUILD_ENV ${BUILD_ENVIRONMENT}
ENV PATH="${APP_HOME}/.venv/bin:$PATH"
ENV TZ=Asia/Shanghai
ENV LC_ALL=C.UTF-8

WORKDIR ${APP_HOME}

RUN addgroup --system django \
    && adduser --system --ingroup django django


# Install required system dependencies
RUN sed -i "s@http://deb.debian.org@https://mirrors.aliyun.com@g" /etc/apt/sources.list \
    && apt-get update && apt-get install -y --no-install-recommends \
    # psycopg2 dependencies
    libpq-dev \
    # Translations dependencies
    gettext \
    # cleaning up unused files
    && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
    && rm -rf /var/lib/apt/lists/*

# All absolute dir copies ignore workdir instruction. All relative dir copies are wrt to the workdir instruction
# copy python dependency packages from python-build-stage
COPY --from=python-build-stage --chown=django:django ${APP_HOME}/.venv ${APP_HOME}/.venv/

COPY --chown=django:django ./compose/production/django/entrypoint /entrypoint
RUN sed -i 's/\r$//g' /entrypoint \
    && chmod +x /entrypoint

COPY --chown=django:django ./compose/production/django/start /start
RUN sed -i 's/\r$//g' /start \
    && chmod +x /start

{%- if cookiecutter.use_celery == "y" %}
COPY --chown=django:django ./compose/production/django/celery/worker/start /start-celeryworker
RUN sed -i 's/\r$//g' /start-celeryworker \
    && chmod +x /start-celeryworker

COPY --chown=django:django ./compose/production/django/celery/beat/start /start-celerybeat
RUN sed -i 's/\r$//g' /start-celerybeat \
    && chmod +x /start-celerybeat

COPY ./compose/production/django/celery/flower/start /start-flower
RUN sed -i 's/\r$//g' /start-flower \
    && chmod +x /start-flower
{%- endif %}

# copy application code to WORKDIR
COPY --chown=django:django . ${APP_HOME}

# make django owner of the WORKDIR directory as well.
RUN chown django:django ${APP_HOME}

USER django

ENTRYPOINT ["/entrypoint"]
