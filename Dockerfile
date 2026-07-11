FROM python:3.10-slim

# Create a non-root user and group for security hardening
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -m -s /bin/bash appuser

WORKDIR /app

COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Set ownership to appuser
RUN chown -R appuser:appgroup /app

# Switch context to the non-root user
USER appuser

EXPOSE 8000

ENV ALLOWED_ORIGINS=""
ENV DEV_MODE="false"

CMD ["python", "backend/main.py"]
