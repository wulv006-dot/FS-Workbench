FROM python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TMPDIR=/var/lib/fs-data-connector
WORKDIR /app
COPY fs_mcp_connector/requirements.txt /tmp/connector-requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r /tmp/connector-requirements.txt && rm /tmp/connector-requirements.txt
COPY fs_mcp_connector/ /app/fs_mcp_connector/
COPY ui-system/ /app/ui-system/
COPY releases/ /app/releases/
COPY tools/ /app/tools/
COPY runtime-manifest.json /app/runtime-manifest.json
LABEL org.opencontainers.image.revision="9c1fac9c4e6c49ef40b4c58cabe75a71e01159b5" fs.approved-head="787b5c0" fs.purpose="readonly-mcp-connector"
CMD ["python","-m","fs_mcp_connector"]
