#!/usr/bin/env python3
"""
test_integration.py
===================
Valida o fluxo ponta-a-ponta entre o microsserviço cp-collection-ms e o
monolito Coleta-Premiada (Core), incluindo a mensageria RabbitMQ que conecta
os dois.

Execução:
    python test_integration.py

Características:
  • Sequencial — executa em ordem de dependência (parando em falhas críticas)
  • Auto-diagnóstico — em falhas, envia contexto para um modelo Claude e
    imprime a sugestão de correção
  • Validação de mensageria — inspeciona as filas 'imoveis' e 'coletas' e
    confirma a propagação consultando o serviço consumidor
  • Relatório final em tabela

Não recebe argumentos: configurações ficam em config.yaml e .env.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# ── Cores ANSI ──────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BLUE   = "\033[94m"
GRAY   = "\033[90m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def _c(text, color):    return f"{color}{text}{RESET}"
def ok(msg):    print(_c(f"  ✔  {msg}", GREEN))
def fail(msg):  print(_c(f"  ✘  {msg}", RED))
def warn(msg):  print(_c(f"  ⚠  {msg}", YELLOW))
def info(msg):  print(_c(f"  →  {msg}", CYAN))
def step(n, msg): print(_c(f"\n[{n}] {msg}", BOLD + BLUE))
def title(msg): print(_c(f"\n{'═'*72}\n{msg}\n{'═'*72}", BOLD))


# ── Dependências externas (com mensagens amigáveis) ─────────────────────────
def _require(modulo: str, pip_name: str | None = None):
    try:
        return __import__(modulo)
    except ImportError:
        nome = pip_name or modulo
        sys.exit(_c(
            f"Dependência faltando: '{modulo}'. Instale com:  pip install {nome}",
            RED,
        ))

requests = _require("requests")
yaml     = _require("yaml", "pyyaml")
pika     = _require("pika")
# dotenv é opcional
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ── Carregamento da configuração ────────────────────────────────────────────
CFG_PATH = Path(__file__).parent / "config.yaml"
if not CFG_PATH.exists():
    sys.exit(_c(f"config.yaml não encontrado em {CFG_PATH}", RED))

with CFG_PATH.open(encoding="utf-8") as f:
    CFG: dict = yaml.safe_load(f)

REQ_TIMEOUT = int(CFG["timeouts"]["http_request"])
RABBIT_WAIT = int(CFG["timeouts"]["rabbit_propagation"])
WARMUP      = int(CFG["timeouts"]["service_warmup"])


# ── Bloco de diagnóstico (lido pelo Claude Code) ────────────────────────────
# O script não chama API de IA. Em falhas, imprime um bloco delimitado
# `DIAGNOSTIC <<<EOF ... EOF` com tudo que o Claude Code precisa para
# propor a correção (teste, erro, payload, resposta, arquivos a inspecionar).

def emitir_bloco_diagnostico(test_name: str, error: str,
                              http_ctx: dict, source_hint: str = "") -> None:
    payload = {
        "test":          test_name,
        "error":         error,
        "http_context":  http_ctx,
        "files_to_read": [l.strip() for l in source_hint.splitlines() if l.strip()],
        "context_keys":  [k for k in context.keys() if not k.startswith("_")],
    }
    print(_c("\nDIAGNOSTIC <<<EOF", GRAY))
    print(_c(json.dumps(payload, indent=2, ensure_ascii=False, default=str), GRAY))
    print(_c("EOF\n", GRAY))


# ── Estado/resultados ───────────────────────────────────────────────────────
@dataclass
class TestResult:
    name: str
    status: str            # 'ok' | 'fail' | 'partial' | 'skipped'
    detail: str = ""

results: list[TestResult] = []
context: dict[str, Any] = {}        # estado compartilhado entre etapas


def record(name: str, status: str, detail: str = ""):
    results.append(TestResult(name, status, detail))


# ── Helpers de rede ─────────────────────────────────────────────────────────
def tcp_open(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_get(url: str, **kw) -> requests.Response:
    return requests.get(url, timeout=REQ_TIMEOUT, **kw)


def http_post(url: str, **kw) -> requests.Response:
    return requests.post(url, timeout=REQ_TIMEOUT, **kw)


def short(resp: requests.Response | None) -> dict:
    if resp is None:
        return {}
    try:
        body = resp.json()
    except Exception:
        body = resp.text[:500]
    return {"status": resp.status_code, "body": body}


# ── docker exec helper ──────────────────────────────────────────────────────
def docker_exec(container: str, *args: str) -> tuple[int, str, str]:
    if not shutil.which("docker"):
        return 127, "", "docker CLI não encontrado no PATH"
    proc = subprocess.run(
        ["docker", "exec", container, *args],
        capture_output=True, text=True, timeout=60,
    )
    return proc.returncode, proc.stdout, proc.stderr


# ── Decorator que captura falhas e dispara o diagnóstico ────────────────────
def runner(name: str, *, deps: list[str] | None = None,
           critical: bool = True, source_hint: str = ""):
    """Wrap uma função para virar uma etapa do pipeline."""
    deps = deps or []

    def decorator(fn: Callable[[], dict]):
        def wrapper():
            step(len(results) + 1, name)

            # checa dependências
            for d in deps:
                prev = next((r for r in results if r.name == d), None)
                if not prev or prev.status not in ("ok", "partial"):
                    warn(f"DEPENDÊNCIA não satisfeita: '{d}' "
                         f"(status={prev.status if prev else 'ausente'})")
                    record(name, "skipped",
                           detail=f"Dependência '{d}' não satisfeita")
                    if critical:
                        return False
                    return True

            try:
                out = fn() or {}
                status_ = out.get("status", "ok")
                detail = out.get("detail", "")
                if status_ == "ok":
                    ok(detail or "OK")
                    record(name, "ok", detail)
                    return True
                if status_ == "partial":
                    warn(detail or "Parcial")
                    record(name, "partial", detail)
                    return True
                raise RuntimeError(detail or "Falha sem detalhes")

            except Exception as exc:
                err_str = f"{type(exc).__name__}: {exc}"
                fail(err_str)
                ctx = {
                    "last_response": short(context.get("_last_response")),
                    "deps_satisfied": deps,
                }
                emitir_bloco_diagnostico(name, err_str, ctx, source_hint)
                record(name, "fail", err_str)
                return not critical

        return wrapper
    return decorator


# ════════════════════════════════════════════════════════════════════════════
# 1. Health checks da infraestrutura
# ════════════════════════════════════════════════════════════════════════════

@runner("Health: MongoDB (TCP)")
def t_mongo():
    db = CFG["databases"]["mongodb"]
    if not tcp_open(db["host"], db["port"]):
        raise ConnectionError(f"MongoDB inacessível em {db['host']}:{db['port']}")
    return {"detail": f"{db['host']}:{db['port']} acessível"}


@runner("Health: PostgreSQL (TCP)")
def t_postgres():
    db = CFG["databases"]["postgres"]
    if not tcp_open(db["host"], db["port"]):
        raise ConnectionError(f"Postgres inacessível em {db['host']}:{db['port']}")
    return {"detail": f"{db['host']}:{db['port']} acessível"}


@runner("Health: RabbitMQ (TCP + filas)")
def t_rabbit():
    mq = CFG["rabbitmq"]
    if not tcp_open(mq["host"], mq["port"]):
        raise ConnectionError(f"RabbitMQ inacessível em {mq['host']}:{mq['port']}")

    creds = pika.PlainCredentials(mq["user"], mq["password"])
    conn  = pika.BlockingConnection(pika.ConnectionParameters(
        host=mq["host"], port=mq["port"], credentials=creds,
        heartbeat=10, blocked_connection_timeout=10,
    ))
    canal = conn.channel()
    contagens = {}
    for fila in mq["queues"]:
        m = canal.queue_declare(queue=fila, durable=True, passive=False)
        contagens[fila] = {
            "mensagens":     m.method.message_count,
            "consumidores":  m.method.consumer_count,
        }
    conn.close()

    context["rabbit_baseline"] = contagens
    for fila, info_ in contagens.items():
        if info_["consumidores"] == 0:
            warn(f"Fila '{fila}' sem consumidores ativos!")
    return {"detail": f"filas {contagens}"}


@runner("Health: Core HTTP (8001)", deps=["Health: PostgreSQL (TCP)"])
def t_core_http():
    url = CFG["services"]["core"]["base_url"] + CFG["services"]["core"]["endpoints"]["admin"]
    resp = http_get(url, allow_redirects=False)
    context["_last_response"] = resp
    if resp.status_code not in (200, 301, 302):
        raise RuntimeError(f"Core respondeu {resp.status_code} em {url}")
    return {"detail": f"GET {url} → {resp.status_code}"}


@runner("Health: Microsserviço HTTP (8002)", deps=["Health: MongoDB (TCP)"])
def t_ms_http():
    url = CFG["services"]["microservice"]["base_url"] + \
          CFG["services"]["microservice"]["endpoints"]["admin"]
    resp = http_get(url, allow_redirects=False)
    context["_last_response"] = resp
    if resp.status_code not in (200, 301, 302):
        raise RuntimeError(f"MS respondeu {resp.status_code} em {url}")
    return {"detail": f"GET {url} → {resp.status_code}"}


# ════════════════════════════════════════════════════════════════════════════
# 2. Autenticação Core (cria morador se necessário)
# ════════════════════════════════════════════════════════════════════════════

def _ensure_core_morador():
    """Cria o usuário-morador via `docker exec` se ele ainda não existir.
    Idempotente: roda Python embutido no shell do Django."""
    u = CFG["core_user"]
    container = CFG["services"]["core"]["container"]
    code = (
        "import sys\n"
        "from accounts.models import Usuario\n"
        f"email = {u['email']!r}\n"
        f"senha = {u['password']!r}\n"
        f"nome  = {u['nome']!r}\n"
        f"cpf   = {u['cpf']!r}\n"
        f"perfil= {u['perfil']!r}\n"
        "user, novo = Usuario.objects.get_or_create(\n"
        "    email=email, defaults=dict(nome=nome, cpf=cpf, perfil=perfil),\n"
        ")\n"
        "user.set_password(senha)\n"
        "user.ativo = True\n"
        "user.save()\n"
        "print('CREATED' if novo else 'EXISTS', user.email, user.perfil)\n"
    )
    rc, out, err = docker_exec(container, "python", "manage.py", "shell", "-c", code)
    if rc != 0:
        raise RuntimeError(f"falha ao garantir morador no Core: {err.strip() or out.strip()}")
    return out.strip()


@runner("Auth: Core — preparar morador e obter JWT",
        deps=["Health: Core HTTP (8001)"])
def t_core_auth():
    setup_out = _ensure_core_morador()
    info(f"docker exec: {setup_out}")

    url = CFG["services"]["core"]["base_url"] + CFG["services"]["core"]["endpoints"]["token"]
    payload = {
        "email":    CFG["core_user"]["email"],
        "password": CFG["core_user"]["password"],
    }
    resp = http_post(url, json=payload)
    context["_last_response"] = resp
    if resp.status_code != 200:
        raise RuntimeError(f"login Core falhou ({resp.status_code}): {resp.text[:300]}")
    data = resp.json()
    if "access" not in data:
        raise RuntimeError(f"resposta sem campo 'access': {data}")
    context["core_token"] = data["access"]
    return {"detail": "JWT do Core obtido"}


# ════════════════════════════════════════════════════════════════════════════
# 3. Autenticação Microsserviço
# ════════════════════════════════════════════════════════════════════════════

@runner("Auth: Microsserviço — registrar/login coletor",
        deps=["Health: Microsserviço HTTP (8002)"])
def t_ms_auth():
    base  = CFG["services"]["microservice"]["base_url"]
    login = base + CFG["services"]["microservice"]["endpoints"]["login"]
    reg   = base + CFG["services"]["microservice"]["endpoints"]["register"]
    u = CFG["ms_user"]

    cred = {"matricula": u["matricula"], "senha": u["password"]}

    # tenta login direto
    resp = http_post(login, json=cred)
    context["_last_response"] = resp
    if resp.status_code != 200:
        # se falhou, tenta registrar
        info("Login direto falhou — tentando registrar coletor")
        full = {**cred, "nome": u["nome"], "email": u["email"],
                "zona": u["zona"], "cargo": u["cargo"]}
        rresp = http_post(reg, json=full)
        context["_last_response"] = rresp
        if rresp.status_code not in (200, 201):
            raise RuntimeError(
                f"registro falhou ({rresp.status_code}): {rresp.text[:300]}"
            )
        token = rresp.json().get("token")
    else:
        token = resp.json().get("token")

    if not token:
        raise RuntimeError("microsserviço não retornou token")
    context["ms_token"]   = token
    context["ms_user_id"] = (resp.json() if resp.status_code == 200 else rresp.json()) \
                            .get("user", {}).get("id")
    return {"detail": "JWT do microsserviço obtido"}


# ════════════════════════════════════════════════════════════════════════════
# 4. Fluxo Core → Microsserviço (criação de Imóvel propagada via fila 'imoveis')
# ════════════════════════════════════════════════════════════════════════════

@runner("Fluxo Core→MS: POST /api/program/properties",
        deps=["Auth: Core — preparar morador e obter JWT"],
        source_hint=(
            "core/program/views.py — ImovelListCreateView (POST cria Imovel)\n"
            "core/program/signals.py — post_save dispara publish_morador → fila 'imoveis'\n"
            "core/messaging/producer.py — publish_morador()\n"
        ))
def t_core_create_imovel():
    # precisa do ID do titular morador para amarrar o Imovel
    base = CFG["services"]["core"]["base_url"]
    hdr  = {"Authorization": f"Bearer {context['core_token']}"}
    me   = http_get(base + CFG["services"]["core"]["endpoints"]["me"], headers=hdr)
    context["_last_response"] = me
    if me.status_code != 200:
        raise RuntimeError(f"/auth/me falhou ({me.status_code}): {me.text[:200]}")
    titular_id = me.json().get("id")
    if not titular_id:
        raise RuntimeError(f"id do morador não encontrado em {me.json()}")

    inscricao = f"TEST-INT-{int(time.time())}"
    context["inscricao"] = inscricao
    payload = {**CFG["imovel_payload"],
               "inscricao": inscricao,
               "titular":   titular_id}

    url = base + CFG["services"]["core"]["endpoints"]["properties"]
    resp = http_post(url, json=payload, headers=hdr)
    context["_last_response"] = resp
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"POST /properties falhou ({resp.status_code}): {resp.text[:300]}")
    context["imovel_core"] = resp.json()
    return {"detail": f"Imovel inscricao={inscricao} criado no Core (id={resp.json().get('id')})"}


@runner("Mensageria: 'imoveis' propagada e consumida pelo MS",
        deps=["Fluxo Core→MS: POST /api/program/properties",
              "Health: RabbitMQ (TCP + filas)"],
        source_hint=(
            "coleta/services/consumidor.py — _callback() faz upsert_from_evento\n"
            "coleta/managers.py — ImovelManager.upsert_from_evento\n"
            "coleta/views.py — ImovelDetailView e ImovelBuscarView (verificação)\n"
        ))
def t_imoveis_queue():
    info(f"Aguardando {RABBIT_WAIT}s para o consumer processar 'imoveis'...")
    time.sleep(RABBIT_WAIT)

    # verifica que a fila esvaziou (mensagem foi acked) e que o MS gravou
    mq = CFG["rabbitmq"]
    creds = pika.PlainCredentials(mq["user"], mq["password"])
    conn  = pika.BlockingConnection(pika.ConnectionParameters(
        host=mq["host"], port=mq["port"], credentials=creds,
    ))
    canal = conn.channel()
    metrics = canal.queue_declare(queue="imoveis", durable=True, passive=True)
    pendentes = metrics.method.message_count
    consumers = metrics.method.consumer_count
    conn.close()

    if consumers == 0:
        raise RuntimeError("Fila 'imoveis' sem consumidores — o ms-consumer está rodando?")

    if pendentes > 0:
        warn(f"Fila 'imoveis' ainda com {pendentes} mensagens pendentes")

    # confirma do lado do microsserviço (busca por id_externo = inscricao)
    base = CFG["services"]["microservice"]["base_url"]
    hdr  = {"Authorization": f"Bearer {context['ms_token']}"} \
        if context.get("ms_token") else {}
    url  = base + CFG["services"]["microservice"]["endpoints"]["imovel_buscar"]
    params = {"tipo": "qrcode", "valor": context["inscricao"]}
    resp = http_get(url, params=params, headers=hdr)
    context["_last_response"] = resp

    if resp.status_code == 401:
        # se ainda não autenticou no ms, sinaliza parcial: tem dados, só não conferiu
        return {"status": "partial",
                "detail": "fila 'imoveis' OK; ms ainda não autenticado p/ confirmar"}

    if resp.status_code != 200:
        raise RuntimeError(
            f"Imovel não encontrado no MS após {RABBIT_WAIT}s "
            f"({resp.status_code}): {resp.text[:300]}"
        )
    body = resp.json()
    context["imovel_ms_id"] = body.get("id")
    return {"detail": f"Imovel propagado para o MS — id_ms={body.get('id')}"}


# ════════════════════════════════════════════════════════════════════════════
# 5. Fluxo Microsserviço → Core (criação de Coleta propagada via fila 'coletas')
# ════════════════════════════════════════════════════════════════════════════

@runner("Fluxo MS→Core: POST /api/coletas",
        deps=["Auth: Microsserviço — registrar/login coletor",
              "Mensageria: 'imoveis' propagada e consumida pelo MS"],
        source_hint=(
            "coleta/views.py — ColetaCreateView.post → publicar_coleta\n"
            "coleta/services/fila.py — publish em fila 'coletas'\n"
        ))
def t_ms_create_coleta():
    if not context.get("imovel_ms_id"):
        raise RuntimeError("imovel_ms_id ausente — etapa anterior precisa ter passado")

    base = CFG["services"]["microservice"]["base_url"]
    hdr  = {"Authorization": f"Bearer {context['ms_token']}"}

    payload = {
        "imovel_id":  context["imovel_ms_id"],
        "data_hora":  datetime.now(timezone.utc).isoformat(),
        "materiais":  CFG["coleta_payload"]["materiais"],
        "foto_url":   CFG["coleta_payload"]["foto_url"],
        "gps":        CFG["coleta_payload"]["gps"],
        "observacoes":CFG["coleta_payload"]["observacoes"],
        "offline_id": str(uuid.uuid4()),
    }
    resp = http_post(base + CFG["services"]["microservice"]["endpoints"]["coletas"],
                     json=payload, headers=hdr)
    context["_last_response"] = resp
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"POST /coletas falhou ({resp.status_code}): {resp.text[:300]}")
    body = resp.json()
    context["coleta_id_ms"]   = body.get("id") or body.get("coleta_id")
    context["sincronizado"]   = body.get("sincronizado", body.get("sincronizado_core"))
    return {"detail": f"Coleta criada no MS — id={context['coleta_id_ms']}, "
                       f"sincronizado={context['sincronizado']}"}


@runner("Mensageria: 'coletas' propagada e consumida pelo Core",
        deps=["Fluxo MS→Core: POST /api/coletas"],
        source_hint=(
            "core/collection/management/commands/consume_queue.py — _processar()\n"
            "core/program/models.py — SaldoPontos\n"
            "core/program/business_rules.py — aplicar_teto\n"
        ))
def t_coletas_queue():
    info(f"Aguardando {RABBIT_WAIT}s para o consumer do Core processar 'coletas'...")
    time.sleep(RABBIT_WAIT)

    mq = CFG["rabbitmq"]
    creds = pika.PlainCredentials(mq["user"], mq["password"])
    conn  = pika.BlockingConnection(pika.ConnectionParameters(
        host=mq["host"], port=mq["port"], credentials=creds,
    ))
    canal = conn.channel()
    metrics = canal.queue_declare(queue="coletas", durable=True, passive=True)
    pendentes = metrics.method.message_count
    consumers = metrics.method.consumer_count
    conn.close()

    if consumers == 0:
        raise RuntimeError("Fila 'coletas' sem consumidores — o core-consumer está rodando?")
    if pendentes > 0:
        warn(f"Fila 'coletas' ainda com {pendentes} mensagens pendentes")

    # confirma persistência no Core via docker exec (mais robusto que listar /collections)
    container = CFG["services"]["core"]["container"]
    coleta_id = context.get("coleta_id_ms")
    code = (
        "from collection.models import RegistroColeta\n"
        f"qs = RegistroColeta.objects.filter(id_microservico={coleta_id!r})\n"
        "if qs.exists():\n"
        "    r = qs.first()\n"
        "    print(f'FOUND id={r.id} pts={r.pontuacao} kg={r.peso_kg}')\n"
        "else:\n"
        "    print('MISSING')\n"
    )
    rc, out, err = docker_exec(container, "python", "manage.py", "shell", "-c", code)
    if rc != 0:
        raise RuntimeError(f"docker exec falhou: {err.strip() or out.strip()}")

    out = out.strip().splitlines()[-1] if out.strip() else ""
    if not out.startswith("FOUND"):
        raise RuntimeError(
            f"RegistroColeta não encontrado no Core (id_microservico={coleta_id!r}) — saída: {out!r}"
        )
    return {"detail": f"Core registrou a coleta — {out}"}


@runner("Verificação cruzada: GET /api/sincronizacao/status (MS)",
        deps=["Mensageria: 'coletas' propagada e consumida pelo Core"],
        critical=False)
def t_sync_status():
    base = CFG["services"]["microservice"]["base_url"]
    hdr  = {"Authorization": f"Bearer {context['ms_token']}"}
    url  = base + CFG["services"]["microservice"]["endpoints"]["sincronizacao_status"]
    resp = http_get(url, headers=hdr)
    context["_last_response"] = resp
    if resp.status_code != 200:
        raise RuntimeError(f"status falhou ({resp.status_code}): {resp.text[:200]}")
    data = resp.json()
    return {"detail": f"pendentes={data.get('pendentes')} "
                       f"sincronizadas_hoje={data.get('sincronizadas_hoje')}"}


# ════════════════════════════════════════════════════════════════════════════
# Relatório final
# ════════════════════════════════════════════════════════════════════════════
def imprimir_relatorio():
    title("RELATÓRIO FINAL")
    largura = max(len(r.name) for r in results) if results else 30
    icones = {"ok": _c("✅ OK     ", GREEN),
              "fail": _c("❌ FALHOU ", RED),
              "partial": _c("⚠️  PARCIAL", YELLOW),
              "skipped": _c("⏭  PULADO ", GRAY)}

    print(f"\n  {'Etapa'.ljust(largura)}  Status      Detalhe")
    print(f"  {'─'*largura}  {'─'*10}  {'─'*40}")
    for r in results:
        print(f"  {r.name.ljust(largura)}  {icones.get(r.status, r.status)}  {r.detail[:60]}")

    falhas = [r for r in results if r.status == "fail"]
    parciais = [r for r in results if r.status == "partial"]
    pulados = [r for r in results if r.status == "skipped"]
    ok_ = [r for r in results if r.status == "ok"]

    print()
    info(f"Total: {len(results)} | "
         f"{_c('OK', GREEN)}: {len(ok_)} | "
         f"{_c('PARCIAL', YELLOW)}: {len(parciais)} | "
         f"{_c('FALHA', RED)}: {len(falhas)} | "
         f"{_c('PULADO', GRAY)}: {len(pulados)}")

    if falhas:
        print(_c("\nDetalhe das falhas:", RED + BOLD))
        for r in falhas:
            print(_c(f"  ✘ {r.name}", RED))
            print(_c(f"    {r.detail}", RED))
        print(_c(
            "\n→ Cada falha emitiu um bloco DIAGNOSTIC <<<EOF ... EOF acima.\n"
            "  Peça ao Claude Code para investigar usando esses blocos.",
            GRAY,
        ))

    return 0 if not falhas else 1


# ════════════════════════════════════════════════════════════════════════════
# Main — ordem de execução é a ordem de declaração
# ════════════════════════════════════════════════════════════════════════════
def main() -> int:
    title("test_integration.py — fluxo end-to-end cp-collection-ms ↔ Core")
    info(f"config: {CFG_PATH}")
    info("Em falhas, é emitido um bloco DIAGNOSTIC <<<EOF para o Claude Code analisar.")
    info(f"warmup inicial: {WARMUP}s")
    time.sleep(WARMUP)

    pipeline = [
        # infraestrutura
        t_mongo, t_postgres, t_rabbit,
        t_core_http, t_ms_http,
        # autenticação
        t_core_auth, t_ms_auth,
        # fluxo Core → MS
        t_core_create_imovel, t_imoveis_queue,
        # fluxo MS → Core
        t_ms_create_coleta, t_coletas_queue,
        # verificação cruzada
        t_sync_status,
    ]

    for fn in pipeline:
        keep_going = fn()
        if not keep_going:
            warn("Etapa crítica falhou — interrompendo o pipeline.")
            break

    return imprimir_relatorio()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(_c("\nInterrompido pelo usuário.", YELLOW))
        sys.exit(130)
