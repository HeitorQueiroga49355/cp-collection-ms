FROM mongo:7.0

# A imagem oficial mongo:7.0 já inclui mongodump/mongorestore (mongodb-database-tools)
# na versão compatível com o servidor. Só falta o cron para o agendamento diário.
RUN apt-get update \
    && apt-get install -y --no-install-recommends cron \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /scripts

COPY entrypoint.sh backup.sh restore.sh ./
RUN chmod +x entrypoint.sh backup.sh restore.sh

ENTRYPOINT ["/scripts/entrypoint.sh"]
