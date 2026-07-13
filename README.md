# cp-collection-ms — Microservico de Coletas

## Proposito do Sistema

O **cp-collection-ms** e o microservico responsavel pelo registro de **coletas de materiais reciclaveis** em campo, utilizado pelos **coletores** (agentes de campo) via app mobile. Ele faz parte do ecossistema **Coleta Premiada** e se comunica de forma assincrona com o **Core** (monolito Django + PostgreSQL) via **RabbitMQ**.

### O que ele resolve

1. **Busca geoespacial de imoveis** — localiza imoveis cadastrados no programa por QR Code, numero do IPTU, endereco parcial ou **proximidade geografica** (indice `2dsphere` no MongoDB).
2. **Registro offline de coletas** — o coletor pode registrar uma coleta mesmo sem conexao; os dados ficam no SQLite local do app e sao sincronizados via endpoint `POST /api/sincronizar` quando a rede volta (idempotente por `offline_id`).
3. **Upload de fotos** — cada coleta pode incluir uma foto enviada diretamente ao MinIO (S3-compatible).
4. **Publicacao de eventos** — ao registrar uma coleta, o MS publica um evento na fila `coletas` (RabbitMQ), que o Core consome para creditar pontos ao morador.
5. **Replica de imoveis** — consome a fila `imoveis` (publicada pelo Core) e mantem uma replica local no MongoDB com dados geoespaciais otimizados para consulta em campo.

### Fluxo de Dados

```
Core (PostgreSQL)                 cp-collection-ms                 App Mobile (Expo)
     │                                  │                                │
     ├─ publica fila "imoveis" ────────►│ consome e grava no MongoDB     │
     │                                  │                                │
     │                                  │◄── GET /api/imoveis/proximos ──┤ (busca imovel)
     │                                  │◄── POST /api/coletas ──────────┤ (registra coleta + foto)
     │                                  │                                │
     │◄─── fila "coletas" ──────────────┤ publica evento                 │
     │   (Celery credita pontos)        │                                │
```

---

## Tecnologias

### Stack Principal

| Camada | Tecnologia | Versao |
|---|---|---|
| **Linguagem** | Python | — (`3.12` via `.python-version`) |
| **Framework Web** | Django | 6.0 |
| **API REST** | Django REST Framework | 3.17 |
| **Banco de Dados** | MongoDB | 7.0 |
| **Backend MongoDB** | `django-mongodb-backend` | 6.0 |
| **Mensageria** | RabbitMQ (via `pika`) | 3-management-alpine |
| **Object Storage** | MinIO (S3-compatible) | latest |
| **Autenticacao** | `djangorestframework-simplejwt` (JWT) | 5.5 |
| **Infraestrutura** | Docker / Docker Compose | — |

### Por que MongoDB?

Diferente do Core (que usa PostgreSQL para dados relacionais e integridade transacional), este microservico usa **MongoDB** por tres razoes principais:

- **Busca geoespacial nativa** — indices `2dsphere` permitem queries `$near` para encontrar imoveis por proximidade (essencial para o coletor em campo).
- **Schema flexivel** — os dados de imoveis replicados do Core podem evoluir sem migracoes rigidas.
- **Alta ingestao de escrita** — registros de coleta sao write-heavy e o MongoDB lida bem com esse perfil.

### Bibliotecas e Suas Funcoes

| Biblioteca | Funcao |
|---|---|
| `django-mongodb-backend` | Backend oficial MongoDB para Django ORM (models, migrations, admin) |
| `pymongo` | Driver MongoDB de baixo nivel (usado pelo backend) |
| `dnspython` | Resolucao DNS para conexoes MongoDB Atlas |
| `pika` | Cliente RabbitMQ — publica na fila `coletas`, consome da fila `imoveis` |
| `minio` | SDK MinIO para upload de fotos das coletas |
| `djangorestframework-simplejwt` | Autenticacao JWT dos coletores |
| `django-cors-headers` | CORS para o app mobile |
| `django-prometheus` | Exporta metricas para o Prometheus (`/metrics`) |
| `gunicorn` | Servidor WSGI de producao |

### Estrutura de Apps Django

```
cp-collection-ms/
├── coleta/           # Models Imovel (GeoJSON), Coleta (registro de coleta),
│                     #   endpoints de busca e sincronizacao, services (storage,
│                     #   fila RabbitMQ), management commands
├── coletores/        # Model Coletor (AUTH_USER_MODEL) com matricula, zona, cargo
├── custom_audit/     # Middleware + signals para auditoria em MongoDB (audit_logs)
├── mongo_migrations/ # Migrations customizadas para admin, auth, contenttypes no MongoDB
├── config/           # settings.py, urls.py (configuracao central)
├── mongo-backup/     # Scripts de backup/restore do MongoDB (mongodump/mongorestore)
└── scripts/          # Manutencao automatizada (limpeza de logs, indices) e relatorios
```

### Servicos Docker

| Servico | Descricao |
|---|---|
| `ms-db` | MongoDB 7.0 com autenticacao (admin database) |
| `rabbitmq-local` | RabbitMQ com management UI (portas `5673`/`15673` para nao conflitar com o Core) |
| `ms` | API Django em modo dev (`runserver`) — porta `8002` |
| `ms-consumer` | Consumidor da fila `imoveis` (`manage.py consumir_imoveis`) |
| `mongo-backup` | Backup diario via `mongodump` (cron `0 3 * * *`), compactado com gzip, retencao de 7 dias |
| `mongo-maintenance` | Limpeza batch de `audit_logs` (TTL 90 dias) e manutencao periodica de indices |
| `mongodb-exporter` | Exporta metricas do MongoDB para Prometheus (Percona) |

---

## Instalacao

### Pre-requisitos

- [Docker](https://docs.docker.com/engine/install/) e [Docker Compose](https://docs.docker.com/compose/install/)
- [Git](https://git-scm.com/)

### Passo a Passo (Docker — modo standalone)

Este compose sobe o MS com suas proprias instancias de MongoDB e RabbitMQ (portas diferentes para nao conflitar com o Core).

**1. Clone e acesse:**

```bash
git clone <url-do-repositorio> cp-collection-ms
cd cp-collection-ms
```

**2. Configure as variaveis:**

```bash
cp .env.example .env
```

Edite o `.env` e ajuste as credenciais, especialmente:
- `DJANGO_SECRET_KEY` — chave secreta do Django
- `CORE_JWT_SECRET_KEY` — deve ser **igual** ao `DJANGO_SECRET_KEY` do Core em producao (para validar JWTs)
- `MONGO_USER`, `MONGO_PASSWORD` — credenciais do MongoDB
- `RABBITMQ_DEFAULT_USER`, `RABBITMQ_DEFAULT_PASS` — credenciais do RabbitMQ
- `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` — credenciais do MinIO

**3. Suba os containers:**

```bash
docker compose up -d
```

**4. Aplique as migrations e garanta indices:**

```bash
docker compose exec ms python manage.py migrate
docker compose exec ms python manage.py ensure_audit_indexes
```

**5. Acesse:**

| Recurso | URL |
|---|---|
| **API REST** | `http://localhost:8002/api/` |
| **Django Admin (MongoDB)** | `http://localhost:8002/admin/` |
| **RabbitMQ Management** | `http://localhost:15673` |

### Passo a Passo (Local, sem Docker)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # ajuste host/port apontando para localhost

python manage.py migrate
python manage.py ensure_audit_indexes
python manage.py runserver 0.0.0.0:8001
```

Para consumir a fila `imoveis`:

```bash
python manage.py consumir_imoveis
```

### Comandos Uteis (via Makefile)

```bash
make up                   # Sobe containers
make down                 # Derruba containers
make logs                 # Logs em tempo real
make shell                # Bash no container ms
make migrate              # Aplica migrations
make migrations           # Gera novas migrations
make maintenance-cleanup  # Limpeza manual de audit_logs antigos
make maintenance-reindex  # Reindexacao manual do MongoDB
make ci-up                # Sobe com verificacao de saude (CI/CD)
```

### Mensageria (Filas RabbitMQ)

| Fila | Publicador | Consumidor | Evento |
|---|---|---|---|
| `imoveis` | Core | `ms-consumer` (este MS) | Imovel cadastrado/atualizado no Core |
| `coletas` | Este MS | Core (Celery) | Coleta registrada em campo |

### Backup e Restauracao do MongoDB

Backups automaticos rodam diariamente as 03h. Para operacoes manuais:

```bash
# Backup manual
docker exec coleta-mongo-backup /scripts/backup.sh

# Listar backups
docker exec coleta-mongo-backup ls -lh /backups/mongo

# Restaurar backup mais recente (com confirmacao)
docker exec -it coleta-mongo-backup /scripts/restore.sh

# Restaurar arquivo especifico
docker exec -it coleta-mongo-backup /scripts/restore.sh coleta_db_20260101_030000.gz
```

---

## Documentacao Adicional

- [Apresentacao do Fluxo](apresentacao_fluxo.md) — Fluxo end-to-end detalhado
- [Docs/Auditoria](docs/auditoria.md) — Especificacao completa da auditoria
- [`test_integration.py`](test_integration.py) — Teste de integracao ponta-a-ponta (Core + MS)
- [`teste_mq.py`](teste_mq.py) — Ferramenta interativa para testar filas RabbitMQ
- [`config.yaml`](config.yaml) — Configuracao do teste de integracao
