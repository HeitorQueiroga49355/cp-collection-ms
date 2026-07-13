#!/usr/bin/env python3
"""
Relatorio periodico de monitoramento do MongoDB (cp-collection-ms).

Consulta serverStatus, currentOp, dbStats, collecionStats e replicaSet status
para gerar um relatorio com as metricas mais relevantes do MongoDB.

Uso:
    python mongo_monitoring_report.py                  # stdout (texto)
    python mongo_monitoring_report.py --json           # saida JSON
    python mongo_monitoring_report.py --json --output /tmp/report.json
    python mongo_monitoring_report.py --slow-ms 200    # operacoes > 200ms

Agendamento via cron (exemplo):
    0 7 * * * python /scripts/mongo_monitoring_report.py --json --output /var/log/reports/mongo_$(date +\%Y\%m\%d).json

Dependencias: pymongo
    pip install pymongo
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

try:
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError
except ImportError:
    print("ERRO: pymongo nao encontrado. Instale com: pip install pymongo", file=sys.stderr)
    sys.exit(1)


def get_env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def connect() -> MongoClient:
    """Conecta ao MongoDB usando variaveis de ambiente."""
    host = get_env("MONGO_HOST", "ms-db")
    port = int(get_env("MONGO_PORT", "27017"))
    user = get_env("MONGO_USER", "")
    password = get_env("MONGO_PASSWORD", "")
    db_name = get_env("MONGO_DB", get_env("MONGO_INITDB_DATABASE", "coleta_db"))
    auth_db = get_env("MONGO_AUTH_DB", "admin")

    if user and password:
        uri = f"mongodb://{user}:{password}@{host}:{port}/{db_name}?authSource={auth_db}"
    else:
        uri = f"mongodb://{host}:{port}/{db_name}"

    return MongoClient(uri, serverSelectionTimeoutMS=10000)


# ─── Funcoes de coleta ────────────────────────────────────────────────────────

def collect_server_status(client: MongoClient) -> dict:
    """Metricas gerais do servidor MongoDB."""
    admin_db = client.admin
    status = admin_db.command("serverStatus")

    return {
        "host": status.get("host", ""),
        "version": status.get("version", ""),
        "uptime_seconds": status.get("uptime", 0),
        "uptime_days": round(status.get("uptime", 0) / 86400, 1),
        "connections": {
            "current": status.get("connections", {}).get("current", 0),
            "available": status.get("connections", {}).get("available", 0),
            "active": status.get("connections", {}).get("active", 0),
            "total_created": status.get("connections", {}).get("totalCreated", 0),
        },
        "operations": {
            "inserts": status.get("opcounters", {}).get("insert", 0),
            "queries": status.get("opcounters", {}).get("query", 0),
            "updates": status.get("opcounters", {}).get("update", 0),
            "deletes": status.get("opcounters", {}).get("delete", 0),
            "commands": status.get("opcounters", {}).get("command", 0),
        },
        "memory": {
            "resident_mb": status.get("mem", {}).get("resident", 0),
            "virtual_mb": status.get("mem", {}).get("virtual", 0),
        },
        "network": {
            "bytes_in": status.get("network", {}).get("bytesIn", 0),
            "bytes_out": status.get("network", {}).get("bytesOut", 0),
            "requests_total": status.get("network", {}).get("numRequests", 0),
        },
        "locks": _parse_locks(status.get("locks", {})),
        "wired_tiger": {
            "cache_used_mb": round(
                status.get("wiredTiger", {})
                .get("cache", {})
                .get("bytes currently in the cache", 0) / (1024 * 1024), 1
            ),
            "cache_max_mb": round(
                status.get("wiredTiger", {})
                .get("cache", {})
                .get("maximum bytes configured", 0) / (1024 * 1024), 1
            ),
        },
        "oplog": _parse_oplog(status),
    }


def _parse_locks(locks: dict) -> dict:
    """Extrai metricas simplificadas dos locks."""
    global_lock = locks.get("Global", {})
    return {
        "global_acquire_count": global_lock.get("acquireCount", {}).get("r", 0)
                                + global_lock.get("acquireCount", {}).get("w", 0),
    }


def _parse_oplog(status: dict) -> dict:
    """Extrai informacoes do oplog (se disponivel)."""
    repl = status.get("repl", {})
    rbid = repl.get("rbid")
    return {"rbid": rbid if isinstance(rbid, int) else None}


def collect_current_operations(client: MongoClient, slow_ms: int = 100) -> list[dict]:
    """Operacoes atualmente em execucao (currentOp)."""
    admin_db = client.admin
    ops = admin_db.command("currentOp", {"active": True, "secs_running": {"$gte": 0}})

    result = []
    for op in ops.get("inprog", []):
        secs_running = op.get("secs_running", 0)
        if secs_running * 1000 < slow_ms:
            continue
        result.append({
            "opid": op.get("opid"),
            "type": op.get("type", "?"),
            "ns": op.get("ns", ""),
            "secs_running": secs_running,
            "microsecs_running": op.get("microsecs_running", 0),
            "desc": str(op.get("command", op.get("query", "")))[:300],
            "client": op.get("client", ""),
            "waiting_for_lock": op.get("waitingForLock", False),
            "lock_type": op.get("lockStats", {}).get("Global", {}),
        })
    result.sort(key=lambda x: x["secs_running"], reverse=True)
    return result


def collect_connections_detail(client: MongoClient) -> list[dict]:
    """Detalhes das conexoes ativas."""
    admin_db = client.admin
    try:
        ops = admin_db.command("currentOp", {"allUsers": True, "idleConnections": True})
        conns = []
        for op in ops.get("inprog", []):
            conns.append({
                "opid": op.get("opid"),
                "active": op.get("active", False),
                "client": op.get("client", ""),
                "ns": op.get("ns", ""),
                "secs_running": op.get("secs_running", 0),
                "application": op.get("appName", "?"),
            })
        return conns
    except PyMongoError:
        return []


def collect_db_stats(client: MongoClient, db_name: str) -> dict:
    """Estatisticas de um banco especifico."""
    db = client[db_name]
    stats = db.command("dbStats")
    return {
        "db": db_name,
        "collections": stats.get("collections", 0),
        "objects": stats.get("objects", 0),
        "data_size_mb": round(stats.get("dataSize", 0) / (1024 * 1024), 1),
        "storage_size_mb": round(stats.get("storageSize", 0) / (1024 * 1024), 1),
        "index_size_mb": round(stats.get("indexSize", 0) / (1024 * 1024), 1),
        "total_size_mb": round(stats.get("totalSize", 0) / (1024 * 1024), 1),
        "indexes": stats.get("indexes", 0),
    }


def collect_collection_stats(client: MongoClient, db_name: str) -> list[dict]:
    """Estatisticas das colecoes (top por tamanho)."""
    db = client[db_name]
    names = db.list_collection_names()

    result = []
    for name in names:
        # Pula colecoes de sistema
        if name.startswith("system."):
            continue
        try:
            stats = db.command("collStats", name)
            result.append({
                "collection": name,
                "count": stats.get("count", 0),
                "size_mb": round(stats.get("size", 0) / (1024 * 1024), 1),
                "storage_size_mb": round(stats.get("storageSize", 0) / (1024 * 1024), 1),
                "total_index_size_mb": round(stats.get("totalIndexSize", 0) / (1024 * 1024), 1),
                "nindexes": stats.get("nindexes", 0),
                "avg_obj_size": stats.get("avgObjSize", 0),
                "fragmentation_pct": round(
                    100
                    * (1 - stats.get("size", 0) / max(stats.get("storageSize", 1), 1))
                )
                if stats.get("storageSize", 0) > 0
                else 0,
            })
        except PyMongoError:
            continue

    result.sort(key=lambda x: x["storage_size_mb"], reverse=True)
    return result


def collect_replication_status(client: MongoClient) -> dict | None:
    """Status da replicacao (se for replica set)."""
    admin_db = client.admin
    try:
        repl_status = admin_db.command("replSetGetStatus")
        members = []
        for m in repl_status.get("members", []):
            members.append({
                "name": m.get("name", ""),
                "state": m.get("stateStr", m.get("state", "?")),
                "health": m.get("health", 0),
                "uptime_seconds": m.get("uptime", 0),
                "optime_ts": str(m.get("optime", {}).get("ts", "")),
                "ping_ms": m.get("pingMs", 0),
            })
        return {
            "set_name": repl_status.get("set", ""),
            "members": members,
        }
    except PyMongoError:
        return None


def collect_server_info(client: MongoClient) -> dict:
    """Informacoes basicas do servidor."""
    admin_db = client.admin
    build_info = admin_db.command("buildInfo")
    host_info = admin_db.command("hostInfo")

    return {
        "mongodb_version": build_info.get("version", ""),
        "os_type": host_info.get("os", {}).get("type", ""),
        "os_name": host_info.get("os", {}).get("name", ""),
        "cpu_cores": host_info.get("system", {}).get("numCores", 0),
        "total_ram_gb": round(
            host_info.get("system", {}).get("memSizeMB", 0) / 1024, 1
        ),
    }


# ─── Formatacao ───────────────────────────────────────────────────────────────

def _format_bytes(b: int) -> str:
    """Formata bytes para leitura humana."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def format_text_report(data: dict) -> str:
    """Formata os dados como relatorio de texto."""
    lines: list[str] = []
    sep = "=" * 78

    lines.append(sep)
    lines.append("  RELATORIO DE MONITORAMENTO — MongoDB (cp-collection-ms)")
    lines.append(f"  Gerado em: {data['collected_at']}")
    lines.append(sep)

    # ── Info do servidor ──
    info = data.get("server_info", {})
    lines.append(f"\n── SERVIDOR: MongoDB {info.get('mongodb_version', '?')}")
    lines.append(f"  OS: {info.get('os_name', '?')} | CPUs: {info.get('cpu_cores', '?')} | RAM: {info.get('total_ram_gb', '?')} GB")

    # ── Status ──
    srv = data.get("server_status", {})
    lines.append(f"\n── STATUS GERAL (uptime: {srv.get('uptime_days', 0)} dias)")

    conn = srv.get("connections", {})
    conn_pct = round(100 * conn.get("current", 0) / max(conn.get("available", 1), 1))
    lines.append(f"  Conexoes: {conn.get('current', 0)} ativas / {conn.get('available', 0)} disponiveis ({conn_pct}%)")
    lines.append(f"  Total criadas desde o inicio: {conn.get('total_created', 0)}")

    ops = srv.get("operations", {})
    lines.append(f"  Operacoes (total): inserts={ops.get('inserts', 0)} queries={ops.get('queries', 0)} updates={ops.get('updates', 0)} deletes={ops.get('deletes', 0)}")

    mem = srv.get("memory", {})
    lines.append(f"  Memoria: resident={mem.get('resident_mb', 0)} MB virtual={mem.get('virtual_mb', 0)} MB")

    wt = srv.get("wired_tiger", {})
    if wt.get("cache_max_mb", 0) > 0:
        cache_pct = round(100 * wt["cache_used_mb"] / wt["cache_max_mb"], 1)
        lines.append(f"  WiredTiger cache: {wt['cache_used_mb']} MB / {wt['cache_max_mb']} MB ({cache_pct}%)")

    # ── Banco ──
    db_stats = data.get("db_stats", {})
    lines.append(f"\n── BANCO: {db_stats.get('db', '?')}")
    lines.append(f"  Colecoes: {db_stats.get('collections', 0)} | Objetos: {db_stats.get('objects', 0)}")
    lines.append(f"  Dados: {db_stats.get('data_size_mb', 0)} MB | Armazenamento: {db_stats.get('storage_size_mb', 0)} MB")
    lines.append(f"  Indices: {db_stats.get('index_size_mb', 0)} MB ({db_stats.get('indexes', 0)} indices)")

    # ── Colecoes ──
    lines.append(f"\n── COLECOES (top 20 por tamanho)")
    lines.append(f"  {'Colecao':<35} {'Docs':>8} {'Tamanho':>10} {'Indices':>10} {'Frag%':>6}")
    lines.append("  " + "-" * 72)
    for c in data.get("collections", [])[:20]:
        frag_warn = " ⚠" if c["fragmentation_pct"] > 30 else ""
        lines.append(
            f"  {c['collection']:<35} {c['count']:>8} {c['storage_size_mb']:>8.1f} MB"
            f" {c['total_index_size_mb']:>8.1f} MB {c['fragmentation_pct']:>5}%{frag_warn}"
        )

    # ── Operacoes em execucao ──
    slow_ops = data.get("current_operations", [])
    if slow_ops:
        lines.append(f"\n── OPERACOES EM EXECUCAO (> {data.get('slow_threshold_ms', 100)}ms) — {len(slow_ops)} encontradas")
        for op in slow_ops[:10]:
            lines.append(
                f"  opid={op['opid']} | {op['type']} | {op['secs_running']}s"
                f" | ns={op['ns']} | lock={op['waiting_for_lock']}"
            )

    # ── Replicacao ──
    repl = data.get("replication")
    if repl:
        lines.append(f"\n── REPLICA SET: {repl.get('set_name', '?')}")
        for m in repl.get("members", []):
            health = "✓" if m["health"] == 1 else "✗"
            lines.append(
                f"  {health} {m['name']} | {m['state']} | uptime={m['uptime_seconds']}s"
                f" | ping={m['ping_ms']}ms"
            )
    else:
        lines.append("\n── REPLICA SET: standalone (sem replicacao)")

    lines.append(f"\n{sep}")
    lines.append("  FIM DO RELATORIO")
    lines.append(sep)
    return "\n".join(lines)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Relatorio de monitoramento MongoDB (cp-collection-ms)",
    )
    parser.add_argument("--json", action="store_true", help="Saida em JSON")
    parser.add_argument("--output", "-o", type=str, help="Arquivo de saida (stdout se omitido)")
    parser.add_argument("--slow-ms", type=int, default=100, help="Threshold de operacoes lentas em ms (default: 100)")
    args = parser.parse_args()

    db_name = get_env("MONGO_DB", get_env("MONGO_INITDB_DATABASE", "coleta_db"))

    try:
        client = connect()
        client.admin.command("ping")
    except PyMongoError as e:
        print(f"ERRO: Falha ao conectar ao MongoDB: {e}", file=sys.stderr)
        sys.exit(2)

    try:
        data: dict[str, Any] = {
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "server_info": collect_server_info(client),
            "server_status": collect_server_status(client),
            "db_stats": collect_db_stats(client, db_name),
            "collections": collect_collection_stats(client, db_name),
            "current_operations": collect_current_operations(client, slow_ms=args.slow_ms),
            "connections_detail": collect_connections_detail(client),
            "replication": collect_replication_status(client),
            "slow_threshold_ms": args.slow_ms,
        }
    except PyMongoError as e:
        print(f"ERRO: Falha ao coletar metricas: {e}", file=sys.stderr)
        client.close()
        sys.exit(3)
    finally:
        client.close()

    if args.json:
        output = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    else:
        output = format_text_report(data)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Relatorio salvo em: {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
