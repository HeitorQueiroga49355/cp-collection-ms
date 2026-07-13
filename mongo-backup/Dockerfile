FROM mongo:7.0

# mc: cliente MinIO para upload offsite dos backups.
# Atualize MC_VERSION consultando https://github.com/minio/mc/releases
ARG MC_VERSION=RELEASE.2025-04-08T01-13-53Z

RUN apt-get update \
    && apt-get install -y --no-install-recommends cron curl \
    && rm -rf /var/lib/apt/lists/* \
    && ARCH=$(dpkg --print-architecture) \
    && curl -fsSL \
         "https://dl.min.io/client/mc/release/linux-${ARCH}/archive/mc.${MC_VERSION}" \
         -o /usr/local/bin/mc \
    && chmod +x /usr/local/bin/mc

WORKDIR /scripts

COPY entrypoint.sh backup.sh restore.sh ./
RUN chmod +x entrypoint.sh backup.sh restore.sh

ENTRYPOINT ["/scripts/entrypoint.sh"]
