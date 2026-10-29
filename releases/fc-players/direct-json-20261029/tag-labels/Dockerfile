FROM fc27-player-tool:2026.10.29-cloud.15
USER root
WORKDIR /app
COPY player_web /app/player_web
COPY ["球员维护工具", "/app/球员维护工具"]
COPY VERSION /app/VERSION
RUN ["python3", "-B", "-c", "import hashlib; from pathlib import Path; assert hashlib.sha256(Path('/app/VERSION').read_bytes()).hexdigest() == 'd97a2c6633eec626b62d9798ca38fb305909b22423111a206945dfd9990ca668'"]
