# Sistema de Auditoria (`custom_audit`)

Documentação do app `custom_audit/`, responsável por registrar automaticamente quem fez o quê, quando e de onde, sobre os dados de `Coleta` e `Imovel` neste microsserviço.

## Sumário

- [Visão geral](#visão-geral)
- [Por que não usa MongoEngine](#por-que-não-usa-mongoengine)
- [O que é monitorado](#o-que-é-monitorado)
- [Estrutura de arquivos](#estrutura-de-arquivos)
- [Como cada operação é capturada](#como-cada-operação-é-capturada)
  - [INSERT / UPDATE / DELETE — Django Signals](#insert--update--delete--django-signals)
  - [SELECT — Middleware](#select--middleware)
- [Como o request chega até os signals](#como-o-request-chega-até-os-signals-contextvars)
- [Resolução do usuário autenticado](#resolução-do-usuário-autenticado)
- [Schema do documento `audit_logs`](#schema-do-documento-audit_logs)
- [Índices e expiração automática (TTL)](#índices-e-expiração-automática-ttl)
- [Helpers para operações em lote (bulk)](#helpers-para-operações-em-lote-bulk)
- [Configuração no projeto](#configuração-no-projeto)
- [Limitações conhecidas](#limitações-conhecidas)
- [Comandos úteis](#comandos-úteis)

---

## Visão geral

O `custom_audit` é um app Django autocontido que grava, em uma coleção MongoDB chamada `audit_logs`, um log para cada operação relevante feita sobre os models `Coleta` e `Imovel`:

- `INSERT` — quando um registro é criado.
- `UPDATE` — quando um registro existente é alterado.
- `DELETE` — quando um registro é removido.
- `SELECT` — quando um endpoint GET de leitura é acessado com sucesso.

A auditoria é **passiva**: não exige nenhuma alteração nos models `Coleta`/`Imovel` nem nas views existentes. Ela se conecta por fora, via Django Signals (para escrita) e Middleware (para leitura), e nunca propaga uma exceção para a aplicação principal — uma falha ao gravar um log de auditoria é apenas registrada no logger, nunca derruba a requisição.


## O que é monitorado

| Model | App | Operações via Signals | Operações via Middleware |
|---|---|---|---|
| `Coleta` | `coleta` | INSERT, UPDATE, DELETE | — |
| `Imovel` | `coleta` | INSERT, UPDATE, DELETE | — |
| Endpoints GET de `Coleta`/`Imovel` | `coleta` | — | SELECT |

Endpoints GET cobertos pelo middleware (ver `coleta/urls.py`):

| Endpoint | Coleção auditada | `documento_id` capturado? |
|---|---|---|
| `GET /api/imoveis/buscar` | `imovel` | Não (é busca/listagem) |
| `GET /api/imoveis/proximos` | `imovel` | Não |
| `GET /api/imoveis/<pk>` | `imovel` | Sim |
| `GET /api/coletas/historico` | `coleta` | Não |
| `GET /api/coletas/pendentes` | `coleta` | Não |
| `GET /api/coletas/<pk>` | `coleta` | Sim |

`POST /api/coletas` (criação) não é afetado pelo middleware de SELECT — ele já é auditado como `INSERT` pelos signals, já que internamente chama `Coleta.objects.create(...)`.

## Estrutura de arquivos

```
custom_audit/
├── __init__.py
├── apps.py                                  # AppConfig — conecta os signals em ready()
├── models.py                                # Model AuditLog (collection "audit_logs")
├── middleware.py                            # CustomAuditMiddleware — audita SELECT
├── request_store.py                         # contextvars — ponte request -> signals
├── signals.py                               # Handlers de INSERT/UPDATE/DELETE + helpers bulk
├── admin.py                                  # AuditLog no Django Admin (somente leitura)
├── migrations/
│   ├── __init__.py
│   └── 0001_initial.py                       # CreateModel AuditLog
└── management/
    └── commands/
        └── ensure_audit_indexes.py           # Garante os índices Mongo (incl. TTL)
```

## Como cada operação é capturada

### INSERT / UPDATE / DELETE — Django Signals

`custom_audit/apps.py` chama `connect_audit_signals()` (definida em `signals.py`) dentro de `CustomAuditConfig.ready()`. Esse é o único lugar correto para conectar signals — conectar no nível do módulo faria isso rodar antes dos models estarem totalmente carregados, e poderia duplicar handlers em recarregamentos do `runserver`.

Para cada model em `AUDITED_MODELS = [Coleta, Imovel]`, três signals do Django são conectados, cada um com um `dispatch_uid` único (`custom_audit_pre_save_coleta`, etc.) para garantir que não fiquem duplicados se o app recarregar em `DEBUG=True`:

1. **`pre_save`** (`_pre_save_handler`) — dispara *antes* de salvar. Se o objeto já tem `pk` (ou seja, é uma atualização, não uma criação), busca o estado atual no banco com `sender.objects.get(pk=instance.pk)` e serializa para `instance._audit_dados_antes`. Isso precisa ser feito **antes** do save porque depois dele o estado anterior já foi sobrescrito no banco — não haveria mais como recuperá-lo.

2. **`post_save`** (`_post_save_handler`) — dispara *depois* de salvar, e recebe o flag `created` do Django:
   - `created=True` → operação `INSERT`, `dados_antes=null`.
   - `created=False` → operação `UPDATE`, `dados_antes` é o que o `pre_save` guardou.
   - Em ambos os casos, `dados_depois` é o estado atual da instância já salva.

3. **`post_delete`** (`_post_delete_handler`) — dispara depois que o objeto é removido do banco. Como o Python ainda mantém a instância em memória nesse momento, ela é serializada como `dados_antes`; `dados_depois` é sempre `null`.

Cada handler delega a gravação efetiva para `_save_audit_log()`, que monta o `AuditLog` e chama `.save()` dentro de um `try/except` — se a gravação falhar (ex: Mongo fora do ar), o erro é apenas logado (`logger.exception`) e a operação original em `Coleta`/`Imovel` segue intacta.

#### Como os dados são serializados

A função `_serialize_instance()` percorre apenas `instance._meta.fields` (os campos concretos do model) e ignora relações reversas (`many_to_many`, `one_to_many`), evitando consultas extras (N+1) e recursão infinita. Para cada campo:

1. Lê o valor "crú" com `field.value_from_object(instance)` — para uma `ForeignKey`, isso retorna o valor da coluna (o id relacionado), não o objeto completo, sem disparar uma query adicional.
2. Faz um round-trip por `json.dumps(..., cls=DjangoJSONEncoder)` / `json.loads(...)` para garantir que o valor é 100% serializável em JSON (`Decimal`, `UUID`, `datetime` e `JSONField` já são tratados nativamente pelo `DjangoJSONEncoder`).
3. Se isso falhar (ex: um `ObjectId` do backend Mongo, que o `DjangoJSONEncoder` não conhece), cai no `except` e o valor é simplesmente convertido para `str(...)`.

O resultado é um `dict` plano, pronto para ser salvo em `dados_antes`/`dados_depois` (campos `JSONField`).

### SELECT — Middleware

Como o Django não tem um "signal de leitura" (não existe `post_select`), capturar operações de leitura é feito de forma diferente: via `CustomAuditMiddleware`, em `custom_audit/middleware.py`.

Fluxo por requisição (`__call__`):

1. Registra o `request` atual no `contextvars` (`set_current_request`) — isso é o que permite que os signals, disparados *dentro* de `get_response()`, também tenham acesso ao IP/endpoint/usuário da requisição (ver seção seguinte).
2. Chama `self.get_response(request)`, deixando a view processar normalmente.
3. Depois que a resposta volta, `_handle_select_audit()` decide se deve auditar:
   - Só audita se o método for `GET`.
   - Só audita se o status da resposta estiver entre 200 e 299 (erros e respostas de autenticação/permissão negada, como 401/403/404, **não** geram log).
   - Só audita se o path bater com algum padrão em `SELECT_ENDPOINT_MAP`.
4. Se todas as condições passarem, grava um `AuditLog` com `operacao="SELECT"`, `dados_antes=null`, `dados_depois=null` (leitura não tem "antes/depois", só o fato de ter sido lida).
5. **Sempre**, no `finally`, limpa o contextvars (`clear_current_request()`) — mesmo que a view tenha lançado uma exceção. Isso evita que o request de uma requisição "vaze" para outra em caso de reuso de worker/thread.

#### `SELECT_ENDPOINT_MAP`

```python
SELECT_ENDPOINT_MAP = [
    (re.compile(r'^/api/imoveis/buscar/?$'), 'imovel', None),
    (re.compile(r'^/api/imoveis/proximos/?$'), 'imovel', None),
    (re.compile(r'^/api/coletas/historico/?$'), 'coleta', None),
    (re.compile(r'^/api/coletas/pendentes/?$'), 'coleta', None),
    (re.compile(r'^/api/imoveis/(?P<doc_id>[^/]+)/?$'), 'imovel', 'doc_id'),
    (re.compile(r'^/api/coletas/(?P<doc_id>[^/]+)/?$'), 'coleta', 'doc_id'),
]
```

Cada entrada é `(regex, nome_da_colecao, nome_do_grupo_de_id)`. A lista é percorrida em ordem, e a **ordem importa**: os padrões literais (`buscar`, `proximos`, `historico`, `pendentes`) vêm antes do padrão genérico de detalhe (`<pk>`). Se estivesse na ordem contrária, uma requisição para `/api/coletas/historico` seria erroneamente interpretada como "coleta de id `historico`".

### Resumo do comportamento por operação

| Operação | Disparado por | `dados_antes` | `dados_depois` |
|---|---|---|---|
| `model.save()` em objeto novo | `post_save` (created=True) | `null` | dict com todos os campos |
| `model.save()` em objeto existente | `pre_save` + `post_save` (created=False) | dict com estado anterior | dict com estado novo |
| `model.delete()` / `queryset.delete()` | `post_delete` | dict com estado do objeto deletado | `null` |
| `GET .../coletas/...` ou `.../imoveis/...` com 200–299 | `CustomAuditMiddleware` | `null` | `null` |

## Como o request chega até os signals (`contextvars`)

Os signals (`pre_save`/`post_save`/`post_delete`) são disparados pelo Django ORM, em um contexto onde não existe nenhuma referência direta ao `request` HTTP que originou a operação — uma função de signal recebe apenas `sender`, `instance` e kwargs específicos do signal. Para resolver isso sem precisar alterar a assinatura de nenhuma view, o `custom_audit` usa `contextvars.ContextVar` (`custom_audit/request_store.py`):

```python
_current_request: ContextVar = ContextVar('current_request', default=None)

def set_current_request(request): _current_request.set(request)
def get_current_request(): return _current_request.get()
def clear_current_request(): _current_request.set(None)
```

`ContextVar` é thread-safe (e seguro também em código assíncrono): cada thread/corrotina tem seu próprio "slot" isolado, então requisições concorrentes nunca leem o `request` umas das outras.

O ciclo é:

1. `CustomAuditMiddleware.__call__` roda **antes** da view → chama `set_current_request(request)`.
2. A view processa a requisição. Se ela criar/alterar/remover uma `Coleta`/`Imovel`, os signals disparam **durante** esse processamento (ainda dentro do `get_response()` do middleware) e chamam `get_current_request()` dentro de `signals.py` (`_get_request_context()`) para ler `ip_origem`, `endpoint` e o usuário autenticado.
3. Quando a view termina e a resposta volta para o middleware, o bloco `finally` chama `clear_current_request()`.

Fora do ciclo de uma requisição HTTP (management commands, shell, tarefas em background), `get_current_request()` retorna `None`, e `_get_request_context()` simplesmente devolve `ip_origem=None`, `endpoint=None`, `usuario_matricula=None` — a auditoria continua funcionando, só sem esses três campos.

## Resolução do usuário autenticado

O requisito original era resolver o JWT manualmente "antes que o DRF processe a autenticação", e isso está implementado em `middleware.py` (`_resolve_user`):

```python
def _resolve_user(request):
    user = getattr(request, 'user', None)
    if user and not getattr(user, 'is_anonymous', True):
        return user
    try:
        from rest_framework_simplejwt.authentication import JWTAuthentication
        auth_result = JWTAuthentication().authenticate(request)
        if auth_result:
            user, _ = auth_result
            return user
    except Exception:
        pass
    return None
```

Na prática, como `_handle_select_audit` roda **depois** de `get_response()`, a view DRF já rodou e `request.user` já foi populado pela autenticação JWT padrão do `rest_framework_simplejwt` (configurado em `DEFAULT_AUTHENTICATION_CLASSES`, em `config/settings.py`) — então o primeiro `if` normalmente já resolve. A decodificação manual do JWT existe como uma segunda tentativa de segurança, para casos em que `request.user` ainda não esteja populado (ex.: uma view futura sem DRF, ou uma falha silenciosa na autenticação padrão).

Esse mesmo padrão de resolução (usuário → matrícula) é repetido em dois lugares, intencionalmente desacoplados:

- `middleware.py` → `_get_usuario_matricula()`, usado para SELECT.
- `signals.py` → dentro de `_get_request_context()`, usado para INSERT/UPDATE/DELETE.

Em ambos, a ordem de prioridade para extrair o identificador do usuário é:

```python
getattr(user, 'matricula', None) or getattr(user, 'username', None) or str(getattr(user, 'pk', '')) or None
```

O model de usuário deste MS é `Coletor` (`coletores/models.py`, `AUTH_USER_MODEL = 'coletores.Coletor'`), que expõe `matricula` como uma `@property` que apenas retorna `self.username` — por isso, na prática, `usuario_matricula` sempre acaba sendo o `username` do coletor.

## Schema do documento `audit_logs`

Definido em `custom_audit/models.py` como um model Django padrão (`db_table = 'audit_logs'`):

| Campo | Tipo | Observação |
|---|---|---|
| `id` | ObjectId (auto) | Gerado automaticamente pelo MongoDB/`django-mongodb-backend` |
| `timestamp` | `DateTimeField` | Default `timezone.now` (timezone-aware, igual ao resto do projeto) |
| `usuario_matricula` | `CharField` (opcional) | Matrícula/username do usuário autenticado, ou `null` |
| `operacao` | `CharField` com choices | `INSERT`, `UPDATE`, `DELETE` ou `SELECT` |
| `colecao` | `CharField` | Nome do model em lowercase: `"coleta"` ou `"imovel"` |
| `documento_id` | `CharField` (opcional) | `str(pk)` do objeto afetado |
| `dados_antes` | `JSONField` (opcional) | Estado anterior do objeto, ou `null` |
| `dados_depois` | `JSONField` (opcional) | Estado posterior do objeto, ou `null` |
| `ip_origem` | `CharField` (opcional) | IP do cliente (considera `X-Forwarded-For`) |
| `endpoint` | `CharField` (opcional) | Path da requisição HTTP que originou o log |

Exemplo de documento (`UPDATE` em uma coleta):

```json
{
  "_id": "665f1a2b3c4d5e6f7a8b9c0d",
  "timestamp": "2026-06-18T19:30:00.123Z",
  "usuario_matricula": "joao.silva",
  "operacao": "UPDATE",
  "colecao": "coleta",
  "documento_id": "6a3441f837d4449d98266856",
  "dados_antes": { "status": "pendente", "sincronizado_core": false, "...": "..." },
  "dados_depois": { "status": "confirmada", "sincronizado_core": true, "...": "..." },
  "ip_origem": "192.168.1.10",
  "endpoint": "/api/coletas/6a3441f837d4449d98266856"
}
```

## Índices e expiração automática (TTL)

Como `expireAfterSeconds` não é um conceito que o `models.Index` do Django sabe expressar, os índices da coleção `audit_logs` **não** são declarados em `Meta.indexes` do model — eles são criados explicitamente pelo management command `ensure_audit_indexes`, usando acesso direto ao driver `pymongo` (`connections['default'].get_collection(...)`, o mesmo padrão já usado em `coleta/views.py` e na migration `coleta/migrations/0007_imovel_location.py`).

Índices criados (`custom_audit/management/commands/ensure_audit_indexes.py`):

| Nome | Campos | Propósito |
|---|---|---|
| `audit_ttl_90d` | `timestamp` (asc) | **TTL**: `expireAfterSeconds=7776000` (90 dias) — o MongoDB remove automaticamente documentos mais antigos que 90 dias, sem necessidade de um cron job. |
| `idx_usuario_matricula` | `usuario_matricula` | Consultas "tudo que o usuário X fez". |
| `idx_colecao` | `colecao` | Consultas "todos os logs de Coleta/Imovel". |
| `idx_operacao` | `operacao` | Consultas "todos os INSERTs/DELETEs/...". |
| `idx_colecao_timestamp` | `colecao` (asc) + `timestamp` (desc) | Consultas "histórico de uma coleção em um período", já ordenado do mais recente para o mais antigo. |

O comando é **idempotente** — `create_index` com o mesmo nome/especificação não falha se o índice já existir, então pode ser executado novamente a qualquer momento (ex.: após um deploy) sem efeito colateral.

> Esses índices não são criados pela migration `0001_initial.py` (que só registra o model no Django) — é necessário rodar `python manage.py ensure_audit_indexes` pelo menos uma vez no ambiente de destino. Veja [Comandos úteis](#comandos-úteis).

## Helpers para operações em lote (bulk)

Os signals do Django cobrem `instance.save()` e `instance.delete()`, mas **dois** métodos de queryset não disparam `pre_save`/`post_save`/`post_delete`:

- `Model.objects.bulk_create(...)`
- `queryset.update(...)`

(`queryset.delete()` **não** está nessa lista — o `Collector` do Django dispara `post_delete` para cada objeto removido, mesmo em uma deleção em massa via queryset, então `_post_delete_handler` já audita esse caso automaticamente, sem necessidade de nenhum helper.)

Para os dois casos que realmente pulam signals, `custom_audit/signals.py` expõe helpers equivalentes que fazem a chamada original **e** registram o log:

```python
from custom_audit.signals import bulk_create_with_audit, queryset_update_with_audit

# em vez de Coleta.objects.bulk_create([...])
bulk_create_with_audit(Coleta, [Coleta(...), Coleta(...)])

# em vez de Coleta.objects.filter(status='pendente').update(status='aprovado')
queryset_update_with_audit(Coleta.objects.filter(status='pendente'), status='aprovado')
```

- `bulk_create_with_audit`: executa o `bulk_create` normal e grava um `AuditLog` de `INSERT` por instância criada.
- `queryset_update_with_audit`: carrega os objetos afetados **antes** do update (para capturar `dados_antes`), executa o `update()`, depois recarrega e grava um `AuditLog` de `UPDATE` por objeto. Para querysets muito grandes (milhares de objetos), processar em lotes/chunks, já que tudo é carregado em memória.

Atualmente, nenhuma view ou service deste MS usa `bulk_create`/`queryset.update()` sobre `Coleta`/`Imovel` — esses helpers existem para uso futuro, caso alguma feature precise de operações em massa.

## Configuração no projeto

Duas alterações em `config/settings.py`:

```python
INSTALLED_APPS = [
    # ...
    'coletores',
    'coleta',
    'custom_audit',          # <- adicionado
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'custom_audit.middleware.CustomAuditMiddleware',   # <- adicionado aqui
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
```

O middleware fica logo após `SessionMiddleware` e antes de qualquer middleware de autenticação — precisa rodar antes da view (para registrar o `request` no `contextvars` a tempo dos signals) e seu processamento de SELECT só acontece depois que a resposta já voltou da view.

## Limitações conhecidas

- **Sem auditoria de leitura fora do `SELECT_ENDPOINT_MAP`**: endpoints como `GET /api/sincronizacao/status` (que também consulta `Coleta` internamente, mas é um agregado/derivado, não uma listagem/detalhe direta) não geram log de `SELECT`. Para cobrir um novo endpoint, basta adicionar uma entrada em `SELECT_ENDPOINT_MAP`.
- **Falha de auditoria é silenciosa por design**: se o Mongo estiver indisponível no momento de gravar um log, a operação de negócio (criar/atualizar/remover uma coleta/imóvel) segue normalmente, e o erro só aparece no logger (`logging.getLogger('custom_audit.signals')` / `'custom_audit.middleware'`). Isso é intencional — auditoria nunca deve derrubar a aplicação principal — mas significa que perda de conectividade gera lacunas no histórico.
- **`queryset_update_with_audit` carrega tudo em memória**: adequado para volumes pequenos/médios; para milhares de registros, processar em chunks.

## Comandos úteis

```bash
# Aplicar a migration que cria o model AuditLog no Django (e registra o app)
python manage.py migrate custom_audit

# Garantir que os índices do MongoDB existem (incluindo o TTL de 90 dias) — idempotente
python manage.py ensure_audit_indexes

# Conferir no shell se os signals foram conectados
python manage.py shell -c "
from django.db.models.signals import post_save
print([u for u in (r[0][0] for r in post_save.receivers) if 'custom_audit' in str(u)])
"

# Consultar logs recentes de uma coleção específica
python manage.py shell -c "
from custom_audit.models import AuditLog
for log in AuditLog.objects.filter(colecao='coleta').order_by('-timestamp')[:10]:
    print(log)
"
```
