FROM python:3.12-slim AS base

ENV VARIABLE=${BUILD_ARG}

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Create a non-privileged user that the app will run under.
ARG UID=10001
RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/nonexistent" \
    --shell "/sbin/nologin" \
    --no-create-home \
    --uid "${UID}" \
    appuser

USER appuser
COPY app.py .

ENV APP_VERSION=${APP_VERSION}
ENV APP_COLOR=${APP_COLOR}

EXPOSE 8000

CMD ["python","app.py"]