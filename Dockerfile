FROM python:3.12-slim

WORKDIR /workspace

COPY pyproject.toml README.md /tmp/site-agent/
COPY site_agent /tmp/site-agent/site_agent
RUN python -m pip install --no-cache-dir /tmp/site-agent[crawl]
RUN python -m playwright install --with-deps chromium

ENTRYPOINT ["site-agent"]
CMD ["--help"]
