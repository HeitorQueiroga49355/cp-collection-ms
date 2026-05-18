#!/usr/bin/env python3
"""
Ferramenta de teste interativo para as filas RabbitMQ do cp-collection-ms.

Filas cobertas:
  • coletas  — publicada por este serviço (coleta_id / imovel_id / peso_total_kg)
  • imoveis  — consumida por este serviço (dados do imóvel vindos de outro MS)
"""
import json
import sys
import threading
import uuid
from datetime import datetime

try:
    import pika
except ImportError:
    sys.exit("Instale o pika antes:  pip install pika")

# ─── Cores ANSI ───────────────────────────────────────────────────────────────

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):    print(f"{GREEN}✔  {msg}{RESET}")
def warn(msg):  print(f"{YELLOW}⚠  {msg}{RESET}")
def err(msg):   print(f"{RED}✘  {msg}{RESET}")
def info(msg):  print(f"{CYAN}→  {msg}{RESET}")
def title(msg): print(f"\n{BOLD}{msg}{RESET}")

# ─── Conexão ──────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "host":     "localhost",
    "port":     5672,
    "usuario":  "guest",
    "senha":    "guest",
}

config = dict(DEFAULT_CONFIG)


def _parametros():
    credentials = pika.PlainCredentials(config["usuario"], config["senha"])
    return pika.ConnectionParameters(
        host=config["host"],
        port=config["port"],
        credentials=credentials,
        heartbeat=60,
        blocked_connection_timeout=30,
        connection_attempts=2,
        retry_delay=1,
    )


def conectar():
    return pika.BlockingConnection(_parametros())

# ─── Helpers de input ─────────────────────────────────────────────────────────

def pedir(prompt, default=None):
    sufixo = f" [{default}]" if default is not None else ""
    valor = input(f"  {prompt}{sufixo}: ").strip()
    return valor if valor else default


def pedir_int(prompt, default):
    while True:
        raw = pedir(prompt, default)
        try:
            return int(raw)
        except (TypeError, ValueError):
            warn("Digite um número inteiro.")


def pedir_float(prompt, default=None):
    while True:
        raw = pedir(prompt, default)
        try:
            return float(raw)
        except (TypeError, ValueError):
            warn("Digite um número decimal (ex: 12.5).")


def pedir_bool(prompt, default=True):
    opcoes = "S/n" if default else "s/N"
    raw = pedir(f"{prompt} ({opcoes})", "").lower()
    if raw in ("", "s"):
        return True
    if raw == "n":
        return False
    return default

# ─── 1. Configuração de conexão ───────────────────────────────────────────────

def menu_configurar():
    title("Configuração da conexão")
    config["host"]    = pedir("Host RabbitMQ", config["host"])
    config["port"]    = pedir_int("Porta", config["port"])
    config["usuario"] = pedir("Usuário", config["usuario"])
    config["senha"]   = pedir("Senha", config["senha"])
    info(f"Configuração salva: {config['host']}:{config['port']} ({config['usuario']})")

# ─── 2. Teste de conexão ──────────────────────────────────────────────────────

def menu_testar_conexao():
    title("Testando conexão")
    info(f"Conectando em {config['host']}:{config['port']}...")
    try:
        conn = conectar()
        ok(f"Conexão estabelecida")
        ch = conn.channel()
        ok(f"Canal aberto (channel #{ch.channel_number})")
        conn.close()
        ok("Conexão encerrada com sucesso.")
    except pika.exceptions.AMQPConnectionError as e:
        err(f"Falha na conexão: {e}")
    except Exception as e:
        err(f"Erro inesperado: {e}")

# ─── 3. Publicar na fila 'coletas' ────────────────────────────────────────────

def menu_publicar_coleta():
    title("Publicar mensagem → fila 'coletas'")
    info("Preencha os campos (Enter = usar valor padrão):")

    coleta_id  = pedir("coleta_id (UUID)", str(uuid.uuid4()))
    imovel_id  = pedir("imovel_id", "imovel-001")
    peso       = pedir_float("peso_total_kg", 12.5)

    payload = {
        "coleta_id":    coleta_id,
        "imovel_id":    imovel_id,
        "peso_total_kg": peso,
    }

    print(f"\n  Payload: {json.dumps(payload, indent=4, ensure_ascii=False)}")
    if not pedir_bool("Confirmar envio?", True):
        warn("Cancelado.")
        return

    try:
        conn  = conectar()
        canal = conn.channel()
        canal.queue_declare(queue="coletas", durable=True)
        canal.basic_publish(
            exchange="",
            routing_key="coletas",
            body=json.dumps(payload, default=str),
            properties=pika.BasicProperties(delivery_mode=2),
        )
        conn.close()
        ok(f"Mensagem publicada em 'coletas'  [{datetime.now().strftime('%H:%M:%S')}]")
    except Exception as e:
        err(f"Erro ao publicar: {e}")

# ─── 4. Publicar na fila 'imoveis' ───────────────────────────────────────────

def menu_publicar_imovel():
    title("Publicar mensagem → fila 'imoveis'  (simula outro MS)")
    info("Preencha os campos (Enter = usar valor padrão):")

    payload = {
        "id_externo":       pedir("id_externo",       "EXT-0001"),
        "iptu":             pedir("iptu",              "1234567890"),
        "logradouro":       pedir("logradouro",        "Rua das Flores"),
        "numero":           pedir("numero",            "42"),
        "complemento":      pedir("complemento",       ""),
        "bairro":           pedir("bairro",            "Centro"),
        "morador":          pedir("morador",           "João Silva"),
        "telefone":         pedir("telefone",          "(11) 91234-5678"),
        "elegivel":         pedir_bool("elegivel?",    True),
        "motivo_inelegivel":pedir("motivo_inelegivel", ""),
        "ativo":            pedir_bool("ativo?",       True),
    }

    print(f"\n  Payload:\n{json.dumps(payload, indent=4, ensure_ascii=False)}")
    if not pedir_bool("Confirmar envio?", True):
        warn("Cancelado.")
        return

    try:
        conn  = conectar()
        canal = conn.channel()
        canal.queue_declare(queue="imoveis", durable=True)
        canal.basic_publish(
            exchange="",
            routing_key="imoveis",
            body=json.dumps(payload, default=str, ensure_ascii=False),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
            ),
        )
        conn.close()
        ok(f"Mensagem publicada em 'imoveis'  [{datetime.now().strftime('%H:%M:%S')}]")
    except Exception as e:
        err(f"Erro ao publicar: {e}")

# ─── 5. Escutar uma fila ──────────────────────────────────────────────────────

_stop_event = threading.Event()


def _callback_escuta(canal, method, properties, body):
    ts = datetime.now().strftime("%H:%M:%S")
    try:
        dados = json.loads(body)
        corpo = json.dumps(dados, indent=4, ensure_ascii=False)
    except Exception:
        corpo = body.decode(errors="replace")

    print(f"\n{CYAN}{'─'*60}{RESET}")
    print(f"{BOLD}[{ts}] Mensagem recebida  (tag={method.delivery_tag}){RESET}")
    print(corpo)

    canal.basic_ack(delivery_tag=method.delivery_tag)

    if _stop_event.is_set():
        canal.stop_consuming()


def menu_escutar():
    title("Escutar fila (modo passivo)")
    fila = pedir("Nome da fila", "imoveis")
    info(f"Conectando e aguardando mensagens em '{fila}'...")
    info("Pressione Ctrl+C para parar.\n")

    _stop_event.clear()

    try:
        conn  = conectar()
        canal = conn.channel()
        canal.queue_declare(queue=fila, durable=True)
        canal.basic_qos(prefetch_count=1)
        canal.basic_consume(queue=fila, on_message_callback=_callback_escuta)
        canal.start_consuming()
    except KeyboardInterrupt:
        _stop_event.set()
        warn("Consumo interrompido pelo usuário.")
        try:
            canal.stop_consuming()
            conn.close()
        except Exception:
            pass
    except Exception as e:
        err(f"Erro ao escutar: {e}")

# ─── 6. Inspecionar filas ─────────────────────────────────────────────────────

def menu_inspecionar():
    title("Inspecionar filas")
    filas = ["coletas", "imoveis"]
    try:
        conn  = conectar()
        canal = conn.channel()
        print(f"\n  {'Fila':<20} {'Mensagens':>12} {'Consumidores':>14}")
        print(f"  {'─'*20} {'─'*12} {'─'*14}")
        for fila in filas:
            ok_fila = canal.queue_declare(queue=fila, durable=True, passive=True)
            msgs  = ok_fila.method.message_count
            conns = ok_fila.method.consumer_count
            print(f"  {fila:<20} {msgs:>12} {conns:>14}")
        conn.close()
    except Exception as e:
        err(f"Erro ao inspecionar: {e}")

# ─── Menu principal ───────────────────────────────────────────────────────────

MENU = [
    ("Configurar conexão",                       menu_configurar),
    ("Testar conexão",                            menu_testar_conexao),
    ("Publicar coleta  → fila 'coletas'",         menu_publicar_coleta),
    ("Publicar imóvel  → fila 'imoveis'",         menu_publicar_imovel),
    ("Escutar fila (aguarda mensagens)",           menu_escutar),
    ("Inspecionar filas (contagem de mensagens)", menu_inspecionar),
    ("Sair",                                      None),
]


def exibir_menu():
    title("cp-collection-ms  |  Teste de Mensageria RabbitMQ")
    info(f"Broker: {config['host']}:{config['port']}  ({config['usuario']})")
    print()
    for i, (label, _) in enumerate(MENU, 1):
        print(f"  {BOLD}{i}.{RESET} {label}")
    print()


def main():
    while True:
        exibir_menu()
        raw = input("Escolha uma opção: ").strip()
        if not raw.isdigit():
            warn("Digite o número da opção.")
            continue

        idx = int(raw) - 1
        if idx < 0 or idx >= len(MENU):
            warn("Opção inválida.")
            continue

        label, func = MENU[idx]
        if func is None:
            ok("Até logo!")
            break

        func()
        input(f"\n{YELLOW}[ Enter para voltar ao menu ]{RESET}")


if __name__ == "__main__":
    main()
