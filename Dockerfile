FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
# --with-deps installs the Linux libraries Chromium needs
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY . .

# No screen in a container, so the browser runs headless. The dashboard must
# listen on 0.0.0.0 inside the container; publish it on 127.0.0.1 on the host.
ENV HEADLESS=true \
    DASHBOARD_HOST=0.0.0.0 \
    DATA_DIR=/app/data \
    PYTHONUNBUFFERED=1

VOLUME /app/data
EXPOSE 8765

CMD ["python", "dashboard.py", "--no-browser"]
