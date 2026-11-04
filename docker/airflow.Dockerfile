# Airflow 3.3.2 with Tesseract and the invoiceflow package (plus the review-app extra).
# Build context is the repo root. Used by every Airflow service and the review-app.
FROM apache/airflow:3.3.2-python3.12

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
USER airflow

# Install the package (and the streamlit "app" extra so the review-app can reuse this image).
# --chown lets the airflow user read the source during the pip build.
COPY --chown=airflow:0 pyproject.toml README.md /tmp/invoiceflow/
COPY --chown=airflow:0 src /tmp/invoiceflow/src
RUN pip install --no-cache-dir "/tmp/invoiceflow[app]" \
    && rm -rf /tmp/invoiceflow
