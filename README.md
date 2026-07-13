# cp-collection-ms

Microsserviço de **coletas de materiais recicláveis**, desenvolvido em Django + Django REST Framework com persistência em **MongoDB**. Faz parte do ecossistema **Coleta Premiada**, comunicando-se de forma assíncrona via **RabbitMQ** com o sistema **Core** (monolito modular em Postgres) responsável pelo cadastro de imóveis e pontuação dos moradores.

O coletor (agente de campo) usa este microsserviço para localizar imóveis aptos a participar do programa e registrar as coletas feitas em campo, inclusive em modo offline, sincronizando posteriormente.

## Sumário

- [Arquitetura](#arquitetura)
- [Stack](#stack)
- [Modelos de domínio](#modelos-de-domínio)
- [Como executar](#como-executar)
- [Variáveis de ambiente](#variáveis-de-ambiente)
- [Endpoints da API](#endpoints-da-api)
- [Mensageria (RabbitMQ)](#mensageria-rabbitmq)
- [Armazenamento de fotos (MinIO)](#armazenamento-de-fotos-minio)
- [Backup e restauração do MongoDB](#backup-e-restauração-do-mongodb)
- [Auditoria](#auditoria)
- [Testes e ferramentas de apoio](#testes-e-ferramentas-de-apoio)
- [Comandos de gerenciamento (management commands)](#comandos-de-gerenciamento-management-commands)

## Arquitetura

```
                 fila "imoveis"                      fila "coletas"
Core (Postgres) ───────────────────▶  cp-collection-ms  ───────────────────▶ Core (Postgres)
  cadastra imóvel                    consome e grava           publica coleta   computa pontos
  publica evento                     no MongoDB                registrada      do morador
```

- O **Core** publica na fila `imoveis` sempre que um imóvel adere ao programa. O comando `consumir_imoveis` deste serviço consome essa fila e faz *upsert* do imóvel no MongoDB (`Imovel.objects.upsert_from_evento`).
- O **coletor**, usando o app deste microsserviço, busca o imóvel (por QR Code, número do IPTU ou endereço) e registra uma coleta (`POST /api/coletas`).
- Ao salvar a coleta, o serviço publica um evento na fila `coletas`, que o Core consome para creditar a pontuação do morador.
- Todo o fluxo end-to-end está documentado passo a passo em [`apresentacao_fluxo.md`](apresentacao_fluxo.md).

## Stack

- **Django 6** + **Django REST Framework**
- **MongoDB** via [`django-mongodb-backend`](https://github.com/mongodb/django-mongodb-backend) (incluindo índice `2dsphere` para busca geoespacial)
- **RabbitMQ** (via `pika`) para mensageria assíncrona com o Core
- **MinIO** (S3-compatible) para armazenamento das fotos das coletas
- **JWT** (`djangorestframework-simplejwt`) para autenticação
- **Docker / Docker Compose** para orquestração local

## Modelos de domínio

| Model | App | Descrição |
|---|---|---|
| `Coletor` | `coletores` | Usuário autenticável do microsserviço (`AUTH_USER_MODEL`); estende `AbstractUser` com `matricula` (= `username`), `zona`, `cargo`. |
| `Imovel` | `coleta` | Réplica local (MongoDB) do imóvel cadastrado no Core, sincronizada via fila `imoveis`. Guarda `location` em GeoJSON para busca por proximidade. |
| `Coleta` | `coleta` | Registro de uma coleta feita por um `Coletor` em um `Imovel`: peso total, foto, status de sincronização com o Core, controle de tentativas/erros. |

## Como executar

### Com Docker Compose (recomendado)

```bash
cp .env.example .env   # ajuste os valores se necessário
docker-compose up -d
```

Isso inicia:
- `mongodb` — banco do microsserviço (host: `27018`, dentro da rede: `27017`)
- `app` — aplicação Django (host: `8002`, dentro do container: `8001`)
- `coleta-ms-consumer` — consumidor da fila `imoveis` (`python manage.py consumir_imoveis`)
- `mongo-backup` — backup diário do MongoDB via `mongodump` (ver [Backup e restauração do MongoDB](#backup-e-restauração-do-mongodb))

> O serviço `app` espera uma rede externa `coleta-shared`, criada pelo `docker-compose` do projeto **Coleta-Premiada** (Core), para acessar o RabbitMQ compartilhado entre os dois sistemas. Suba o Core antes (ou crie a rede manualmente: `docker network create coleta-shared`).

Após subir os containers, aplique as migrations e garanta os índices do MongoDB:

```bash
docker exec -it coleta-ms-app python manage.py migrate
docker exec -it coleta-ms-app python manage.py ensure_audit_indexes
```

### Localmente (sem Docker)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # configure Mongo/RabbitMQ/MinIO apontando para localhost

python manage.py migrate
python manage.py ensure_audit_indexes
python manage.py runserver 0.0.0.0:8001
```

Para também consumir a fila `imoveis` localmente:

```bash
python manage.py consumir_imoveis
```

## Variáveis de ambiente

Definidas em `.env` (veja [`.env.example`](.env.example)):

| Variável | Descrição |
|---|---|
| `DJANGO_SECRET_KEY` / `DEBUG` | Configuração padrão do Django. |
| `MONGO_INITDB_DATABASE`, `MONGO_USER`, `MONGO_PASSWORD`, `MONGO_HOST`, `MONGO_PORT` | Conexão com o MongoDB. |
| `RABBITMQ_HOST`, `RABBITMQ_PORT`, `RABBITMQ_DEFAULT_USER`, `RABBITMQ_DEFAULT_PASS` | Conexão com o RabbitMQ compartilhado com o Core. |
| `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET_NAME`, `MINIO_USE_HTTPS` | Conexão com o MinIO para upload das fotos de coleta. |

## Endpoints da API

Todos os endpoints (exceto registro/login) exigem `Authorization: Bearer <token>` (JWT do `Coletor`).

### Autenticação (`coletores`)

| Método | Endpoint | Descrição |
|---|---|---|
| `POST` | `/api/auth/register` | Cadastra um novo coletor (`matricula`, `senha`, `nome`, `email`, `zona`, `cargo`). |
| `POST` | `/api/auth/login` | Login por `matricula`/`senha`, retorna token JWT. |
| `POST` | `/api/auth/logout` | Encerra a sessão (stateless, apenas confirmação). |
| `GET` | `/api/me` | Dados do coletor autenticado. |

### Imóveis (`coleta`)

| Método | Endpoint | Descrição |
|---|---|---|
| `GET` | `/api/imoveis/buscar?tipo=&valor=` | Busca por `numero` (IPTU), `qrcode` (id) ou `endereco` (parcial, com `limit`). |
| `GET` | `/api/imoveis/proximos?lat=&lng=&raio=` | Imóveis ativos num raio em metros (padrão 200 m), ordenados por distância via `$near`/`2dsphere`. |
| `GET` | `/api/imoveis/<id>` | Detalhe do imóvel, com histórico das últimas 10 coletas. |

### Coletas (`coleta`)

| Método | Endpoint | Descrição |
|---|---|---|
| `POST` | `/api/coletas` | Registra uma coleta (multipart, com `foto` opcional enviada ao MinIO). Idempotente via `offline_id`. Publica na fila `coletas`. |
| `GET` | `/api/coletas/historico?tipo_periodo=&data=&page=&limit=` | Histórico de coletas do coletor autenticado (`hoje`, `ontem`, `semana`, `mes` ou data específica). |
| `GET` | `/api/coletas/pendentes` | Coletas ainda não sincronizadas com o Core. |
| `GET` | `/api/coletas/<id>` | Detalhe de uma coleta do coletor autenticado. |

### Sincronização (`coleta`)

| Método | Endpoint | Descrição |
|---|---|---|
| `POST` | `/api/sincronizar` | Sincroniza em lote coletas feitas offline (`{"coletas": [...]}`), idempotente por `offline_id`. |
| `GET` | `/api/sincronizacao/status` | Resumo: pendentes, sincronizadas hoje, última sincronização, detalhes dos pendentes. |

> Uma collection do Insomnia com o fluxo completo está em [`insomnia.yaml`](insomnia.yaml).

## Mensageria (RabbitMQ)

Duas filas compartilhadas com o Core:

| Fila | Publicador | Consumidor | Disparada por |
|---|---|---|---|
| `imoveis` | Core | Este MS (`consumir_imoveis`) | Cadastro/atualização de imóvel no Core. |
| `coletas` | Este MS (`services/fila.py`) | Core | `POST /api/coletas` ou `POST /api/sincronizar`. |

- Se a publicação na fila `coletas` falhar (RabbitMQ indisponível), a coleta é salva normalmente com `sincronizado_core=False` e pode ser reenviada depois com o comando `reenviar_coletas`.
- `teste_mq.py` é uma ferramenta de linha de comando interativa para publicar, escutar e inspecionar essas filas manualmente, sem depender da aplicação Django.

## Armazenamento de fotos (MinIO)

`coleta/services/storage.py` faz upload da foto da coleta para o bucket configurado em `MINIO_BUCKET_NAME` (criado automaticamente se não existir) e retorna a URL pública do objeto, salva em `Coleta.foto_url`.

## Backup e restauração do MongoDB

O serviço `mongo-backup` (definido em [`mongo-backup/`](mongo-backup/)) sobe junto com o `docker-compose` e mantém backups automáticos do banco `coleta_db`:

- Roda `mongodump` todo dia às **03h** (cron `0 3 * * *`, configurável via `CRON_SCHEDULE`).
- Compacta o dump em um único arquivo com `--archive` + `--gzip` (`coleta_db_AAAAMMDD_HHMMSS.gz`).
- Mantém apenas os **7 backups mais recentes** (configurável via `BACKUP_RETENTION`), apagando os mais antigos a cada execução.
- Grava tudo no volume nomeado `mongo_backups`, montado em `/backups/mongo` — os arquivos sobrevivem a `docker-compose down` (mas não a `docker-compose down -v`).

### Backup manual (sem esperar o cron)

```bash
docker exec coleta-mongo-backup /scripts/backup.sh
```

### Listar backups disponíveis

```bash
docker exec coleta-mongo-backup ls -lh /backups/mongo
```

### Recuperação de desastre (restore)

`mongo-backup/restore.sh` usa `mongorestore` para repor um dump no MongoDB. Por padrão restaura o backup **mais recente** e pede confirmação antes de continuar, pois **substitui (`--drop`) as collections existentes** em `coleta_db`:

```bash
# Restaura o backup mais recente, com confirmação interativa
docker exec -it coleta-mongo-backup /scripts/restore.sh

# Restaura um arquivo específico (nome do arquivo dentro de /backups/mongo)
docker exec -it coleta-mongo-backup /scripts/restore.sh coleta_db_20260101_030000.gz

# Pula a confirmação interativa (uso em scripts/CI)
docker exec coleta-mongo-backup /scripts/restore.sh -y
```

Passo a passo recomendado em caso de perda de dados:

1. Confirme que o container `mongodb` está saudável: `docker compose ps mongodb`.
2. Liste os backups disponíveis (comando acima) e escolha o arquivo desejado (ou deixe em branco para usar o mais recente).
3. Execute o `restore.sh` correspondente. Ele roda `mongorestore --drop`, ou seja, as collections presentes no dump são recriadas do zero; collections que não constam no dump **não** são apagadas.
4. Valide os dados (ex.: `docker exec -it coleta-mongodb mongosh "mongodb://coleta_user:senha123@localhost:27017/coleta_db?authSource=admin"`).
5. Se a aplicação (`app`/`coleta-ms-consumer`) estava de pé durante a restauração, reinicie-a (`docker compose restart app coleta-ms-consumer`) para garantir que conexões/caches fiquem consistentes com os dados restaurados.

> O `mongo-backup` só conecta no `mongodb` da rede `coleta-ms-network` — ele não expõe portas nem precisa da rede `coleta-shared`.

## Auditoria

O app `custom_audit` registra automaticamente quem fez o quê, quando e de onde sobre os models `Coleta` e `Imovel` — INSERT/UPDATE/DELETE via Django Signals e SELECT via middleware, gravando tudo na coleção MongoDB `audit_logs` (com TTL de 90 dias). É passivo: nunca derruba a aplicação principal em caso de falha.

Documentação completa em [`docs/auditoria.md`](docs/auditoria.md).

## Testes e ferramentas de apoio

- [`test_integration.py`](test_integration.py) — valida o fluxo ponta-a-ponta entre este microsserviço e o Core (incluindo a propagação via RabbitMQ), com relatório final em tabela. Configuração em [`config.yaml`](config.yaml). Execução: `python test_integration.py` (requer Core e MS rodando via Docker Compose).
- [`teste_mq.py`](teste_mq.py) — menu interativo para testar as filas RabbitMQ isoladamente (publicar, escutar, inspecionar).
- `coleta/tests.py` — testes unitários Django (`python manage.py test`).

## Comandos de gerenciamento (management commands)

| Comando | App | Descrição |
|---|---|---|
| `consumir_imoveis` | `coleta` | Inicia o consumidor da fila `imoveis`, com reconexão automática em caso de queda do RabbitMQ. |
| `reenviar_coletas` | `coleta` | Reenvia para a fila `coletas` todas as coletas com `sincronizado_core=False`. |
| `ensure_audit_indexes` | `custom_audit` | Cria/garante os índices do MongoDB para `audit_logs`, incluindo o TTL de 90 dias. Idempotente. |
