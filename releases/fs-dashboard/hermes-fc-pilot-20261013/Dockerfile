# Build context contains only fixed official archives, never business data/keys.
FROM python@sha256:d686a5de867d5af0bce88112d8dee7dcdf8bbf1a8cadf5d0589f48381f229638 AS sqlite
WORKDIR /build
COPY sqlite-autoconf-3530400.tar.gz .
RUN echo '0e9483900e92cd5de8fd48d16bf9200145a61f7fd5be542a5ac81d8a9516eb9c  sqlite-autoconf-3530400.tar.gz' | sha256sum -c - \
 && tar xzf sqlite-autoconf-3530400.tar.gz \
 && cd sqlite-autoconf-3530400 \
 && CFLAGS='-O2 -DSQLITE_ENABLE_FTS3 -DSQLITE_ENABLE_FTS3_PARENTHESIS -DSQLITE_ENABLE_FTS4 -DSQLITE_ENABLE_FTS5 -DSQLITE_ENABLE_RTREE -DSQLITE_ENABLE_GEOPOLY -DSQLITE_ENABLE_COLUMN_METADATA -DSQLITE_ENABLE_UNLOCK_NOTIFY -DSQLITE_ENABLE_DBSTAT_VTAB -DSQLITE_ENABLE_DBPAGE_VTAB -DSQLITE_ENABLE_MATH_FUNCTIONS -DSQLITE_ENABLE_PREUPDATE_HOOK -DSQLITE_ENABLE_SESSION -DSQLITE_SECURE_DELETE -DSQLITE_THREADSAFE=1 -DSQLITE_MAX_VARIABLE_NUMBER=250000' ./configure --prefix=/opt/sqlite --disable-static \
 && make -j2 && make install

FROM python@sha256:998acd06f485adfd6890e3e15a4b542543e0cf22ff904310095da328a5e3e561 AS dependencies
COPY --from=sqlite /opt/sqlite /opt/sqlite
ENV LD_LIBRARY_PATH=/opt/sqlite/lib UV_PYTHON_DOWNLOADS=never UV_NO_CACHE=1
WORKDIR /opt/hermes
COPY hermes-71d34bad.tar.gz uv-0.12.3.tar.gz /build/
RUN echo 'a88ae3f634a3fd45050d3418d80b30ee5af51c89b9de40ec1ea3039d3024d77a  /build/hermes-71d34bad.tar.gz' | sha256sum -c - \
 && echo '600cf9a742aca00d292673b16b5acffaa7b8c269a364ad0c2e79498dcb1fe101  /build/uv-0.12.3.tar.gz' | sha256sum -c - \
 && tar xzf /build/hermes-71d34bad.tar.gz --strip-components=1 -C /opt/hermes \
 && tar xzf /build/uv-0.12.3.tar.gz -C /build \
 && /build/uv-x86_64-unknown-linux-gnu/uv sync --frozen --no-dev --extra sms --no-install-project --python /usr/local/bin/python \
 && /opt/hermes/.venv/bin/python -c "import sqlite3; assert sqlite3.sqlite_version == '3.53.4'"

FROM python@sha256:998acd06f485adfd6890e3e15a4b542543e0cf22ff904310095da328a5e3e561
COPY --from=sqlite /opt/sqlite/lib /opt/sqlite/lib
COPY --from=dependencies /opt/hermes /opt/hermes
ENV LD_LIBRARY_PATH=/opt/sqlite/lib PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
WORKDIR /opt/hermes
# Runtime UID is supplied by the controlled launcher; this fallback is unprivileged.
USER 65534:65534
ENTRYPOINT ["/opt/hermes/.venv/bin/python"]
