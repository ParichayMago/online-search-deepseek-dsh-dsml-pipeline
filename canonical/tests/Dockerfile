FROM python:3.12-slim-bookworm

RUN pip install --no-cache-dir httpx==0.28.1
RUN mkdir -p /app/output /logs/verifier
COPY . /tests
WORKDIR /tests
CMD ["sleep", "infinity"]
