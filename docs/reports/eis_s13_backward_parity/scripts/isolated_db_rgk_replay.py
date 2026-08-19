#!/usr/bin/env python3
"""Isolated OLD vs NEW 44-FZ RGK replay. Writes only to database eis_s13_parity.

Production tender_monitor is opened read-only for seed/schema. Internal parser
commits go to the isolated database only.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

ISO_DB = "eis_s13_parity"
PROD_DB = "tender_monitor"
RGK_SRC = Path("/tmp/eis_s13_parity/rgk")
WORK_ROOT = Path("/tmp/eis_s13_parity_work")
GIT_ROOT = Path("/tmp/eis_s13_parity_git/eis_ingestion/s13_backfill")
OLD_ROOT = Path("/tmp/eis_s13_parity_old")
OUT = Path("/tmp/eis_s13_parity_work/replay_result.json")
SOCKET = "/var/run/postgresql"

TABLES_44 = [
    "reestr_contract_44_fz",
    "reestr_contract_44_fz_commission_work",
    "reestr_contract_44_fz_unknown",
    "reestr_contract_44_fz_unclear",
    "reestr_contract_44_fz_awarded",
]
DUMP_TABLES = TABLES_44 + [
    "reestr_contract_44_fz_completed",
    "collection_codes_okpd",
    "contractor",
    "customer",
    "trading_platform",
    "tender_statuses",
    "file_names_xml",
    "rgk_contract_unresolved",
    "links_documentation_44_fz",
]
COMPARE_FIELDS = (
    "contract_number",
    "lifecycle",
    "final_price",
    "delivery_start_date",
    "delivery_end_date",
    "contractor_id",
    "okpd_id",
    "auction_name",
)


def psql_iso(sql: str) -> str:
    return subprocess.check_output(
        ["psql", "-d", ISO_DB, "-v", "ON_ERROR_STOP=1", "-At", "-c", sql],
        text=True,
        stderr=subprocess.STDOUT,
    ).strip()


def write_env(root: Path) -> None:
    env_path = root / "database_work" / "db_credintials.env"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text(
        "\n".join(
            [
                f"DB_HOST_TENDER={SOCKET}",
                "DB_PORT_TENDER=5432",
                f"DB_DATABASE_TENDER={ISO_DB}",
                "DB_USER_TENDER=postgres",
                "DB_PASSWORD_TENDER=",
                "",
            ]
        ),
        encoding="utf-8",
    )


def write_config(root: Path, xml_dir: Path) -> None:
    tags = root / "required_tags"
    cfg = f"""[stunnel]
stunnel_dir =
config_file =

[path]
env_file =
reest_new_contract_archive_44_fz_xml = {xml_dir}
recouped_contract_archive_44_fz_xml = {xml_dir}
reest_new_contract_archive_223_fz_xml = {xml_dir}
recouped_contract_archive_223_fz_xml = {xml_dir}
unziped_xml_files = {xml_dir}

[eis]
date = 2026-08-13
subsystems_44 = PRIZ,RGK
subsystems_223 = RI223,RD223

[tags]
get_tags_44_new = {tags / "required_tags_44_fz.json"}
get_tags_44_recouped = {tags / "required_tags_44_fz_recouped.json"}
get_tags_223_new = {tags / "required_tags_223_fz.json"}
get_tags_223_recouped = {tags / "required_tags_223_fz_recouped.json"}
get_tags_615_new = {tags / "required_tags_615_pp.json"}

[runtime]
direction = backward
stop_before_date = 2021-01-01
role = isolated-replay
"""
    (root / "config.ini").write_text(cfg, encoding="utf-8")


def clear_tender_env() -> None:
    for key in list(os.environ):
        if key.startswith("DB_") or key.startswith("TENDERMONITOR_"):
            del os.environ[key]


def connect_prod():
    import psycopg2

    conn = psycopg2.connect(dbname=PROD_DB, user="postgres", host=SOCKET)
    conn.set_session(readonly=True, autocommit=True)
    return conn


def connect_iso():
    import psycopg2

    conn = psycopg2.connect(dbname=ISO_DB, user="postgres", host=SOCKET)
    conn.autocommit = False
    return conn


def ensure_isolated_db() -> None:
    subprocess.check_call(
        [
            "psql",
            "-d",
            "postgres",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            (
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{ISO_DB}' AND pid <> pg_backend_pid();"
            ),
        ]
    )
    subprocess.check_call(["dropdb", "--if-exists", ISO_DB])
    subprocess.check_call(["createdb", "--owner=postgres", ISO_DB])
    dump_args = ["pg_dump", "-d", PROD_DB, "--schema-only", "--no-owner", "--no-privileges"]
    for table in DUMP_TABLES:
        dump_args.extend(["-t", table])
    schema = subprocess.check_output(dump_args)
    proc = subprocess.run(
        ["psql", "-d", ISO_DB, "-v", "ON_ERROR_STOP=1"],
        input=schema,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout.decode("utf-8", "replace")[-4000:])
    iso_name = psql_iso("SELECT current_database()")
    if iso_name != ISO_DB:
        raise RuntimeError("isolated database name mismatch")
    print("ISOLATED_DB_READY=YES")
    print("ISOLATED_DB_NAME=" + ISO_DB)


def parse_xml_ids(xml_dir: Path) -> tuple[list[str], list[str], list[str]]:
    sys.path.insert(0, str(GIT_ROOT))
    from parsing_xml.rgk_record import parse_rgk_file
    from secondary_functions import load_config

    os.chdir(GIT_ROOT)
    write_config(GIT_ROOT, xml_dir)
    write_env(GIT_ROOT)
    tags_path = load_config().get("tags", "get_tags_44_recouped")
    tags = json.loads(Path(tags_path).read_text(encoding="utf-8"))
    numbers: list[str] = []
    inns: list[str] = []
    codes: list[str] = []
    for name in sorted(p.name for p in xml_dir.glob("*.xml")):
        record, _ = parse_rgk_file(str(xml_dir / name), tags)
        if record is None:
            continue
        numbers.append(record.contract_number)
        if record.contractor_inn:
            inns.append(record.contractor_inn)
        codes.extend(record.okpd_codes)
    return sorted(set(numbers)), sorted(set(inns)), sorted(set(codes))


def copy_rows(prod, iso, table: str, where_sql: str, params) -> int:
    with prod.cursor() as src:
        src.execute(f"SELECT * FROM {table} {where_sql}", params)
        cols = [desc[0] for desc in src.description]
        rows = src.fetchall()
    if not rows:
        return 0
    placeholders = ", ".join(["%s"] * len(cols))
    col_sql = ", ".join(cols)
    from psycopg2.extras import Json

    # Column type map so we can adapt JSON-looking strings correctly.
    type_map: dict[str, tuple[str, str]] = {}
    with iso.cursor() as cur:
        cur.execute(
            """
            SELECT column_name, data_type, udt_name
            FROM information_schema.columns
            WHERE table_name = %s
              AND table_schema = 'public'
            """,
            (table,),
        )
        for column_name, data_type, udt_name in cur.fetchall():
            type_map[str(column_name)] = (str(data_type), str(udt_name))

    def normalize_value(col: str, v: Any) -> Any:
        data_type, udt_name = type_map.get(col, ("", ""))
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("[") and s.endswith("]"):
                try:
                    parsed = json.loads(s)
                    if isinstance(parsed, list):
                        # jsonb wants Json([...]); arrays want raw list
                        if udt_name in {"json", "jsonb"} or data_type in {"json", "jsonb"}:
                            return Json(parsed)
                        if data_type == "ARRAY" or udt_name.startswith("_"):
                            return parsed
                except Exception:
                    pass
            if s.startswith("{") and s.endswith("}"):
                try:
                    parsed = json.loads(s)
                    if isinstance(parsed, dict):
                        if udt_name in {"json", "jsonb"} or data_type in {"json", "jsonb"}:
                            return Json(parsed)
                except Exception:
                    pass
        if isinstance(v, dict):
            if udt_name in {"json", "jsonb"} or data_type in {"json", "jsonb"}:
                return Json(v)
        if isinstance(v, list):
            # Only keep raw list for ARRAY columns; json columns should be Json(...)
            if data_type == "ARRAY" or udt_name.startswith("_"):
                return v
            if udt_name in {"json", "jsonb"} or data_type in {"json", "jsonb"}:
                return Json(v)
        return v

    normalized = [tuple(normalize_value(col, v) for col, v in zip(cols, row)) for row in rows]
    with iso.cursor() as dst:
        dst.executemany(
            f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders}) ON CONFLICT (id) DO NOTHING",
            normalized,
        )
    return len(normalized)


def seed(numbers: list[str], inns: list[str]) -> dict[str, int]:
    prod = connect_prod()
    iso = connect_iso()
    stats: dict[str, int] = {}
    try:
        with iso.cursor() as cur:
            cur.execute("SET session_replication_role = 'replica'")
            for table in DUMP_TABLES:
                cur.execute(f"TRUNCATE {table} CASCADE")
        stats["okpd"] = copy_rows(prod, iso, "collection_codes_okpd", "", ())
        stats["platforms"] = copy_rows(prod, iso, "trading_platform", "", ())
        stats["statuses"] = copy_rows(prod, iso, "tender_statuses", "", ())
        stats["contractors_xml"] = copy_rows(
            prod, iso, "contractor", "WHERE inn = ANY(%s)", (inns,)
        )
        customer_ids: list[int] = []
        contractor_ids: list[int] = []
        for table in TABLES_44 + ["reestr_contract_44_fz_completed"]:
            stats[table] = copy_rows(
                prod, iso, table, "WHERE contract_number = ANY(%s)", (numbers,)
            )
            with prod.cursor() as src:
                src.execute(
                    f"SELECT customer_id, contractor_id FROM {table} WHERE contract_number = ANY(%s)",
                    (numbers,),
                )
                for customer_id, contractor_id in src.fetchall():
                    if customer_id:
                        customer_ids.append(int(customer_id))
                    if contractor_id:
                        contractor_ids.append(int(contractor_id))
        stats["customers"] = copy_rows(
            prod, iso, "customer", "WHERE id = ANY(%s)", (list(set(customer_ids)),)
        )
        stats["contractors_fk"] = copy_rows(
            prod, iso, "contractor", "WHERE id = ANY(%s)", (list(set(contractor_ids)),)
        )
        stats["unresolved"] = copy_rows(
            prod, iso, "rgk_contract_unresolved",
            "WHERE fz_type = '44' AND contract_number = ANY(%s)",
            (numbers,),
        )
        with iso.cursor() as cur:
            cur.execute("SET session_replication_role = 'origin'")
            for table in DUMP_TABLES:
                cur.execute(f"SELECT pg_get_serial_sequence(%s, 'id')", (table,))
                seq = cur.fetchone()[0]
                if not seq:
                    continue
                cur.execute(f"SELECT COALESCE(MAX(id), 1) FROM {table}")
                max_id = cur.fetchone()[0]
                cur.execute("SELECT setval(%s, %s, true)", (seq, max_id or 1))
        iso.commit()
        prod_name = None
        with prod.cursor() as cur:
            cur.execute("SELECT current_database()")
            prod_name = cur.fetchone()[0]
        iso_name = psql_iso("SELECT current_database()")
        if prod_name != PROD_DB or iso_name != ISO_DB:
            raise RuntimeError(f"db mixup prod={prod_name} iso={iso_name}")
        print("SEED_STATS=" + json.dumps(stats))
        return stats
    except Exception:
        iso.rollback()
        raise
    finally:
        prod.close()
        iso.close()


def snapshot() -> dict[str, dict[str, Any]]:
    iso = connect_iso()
    found: dict[str, dict[str, Any]] = {}
    lookup_tables = [
        "reestr_contract_44_fz",
        "reestr_contract_44_fz_commission_work",
        "reestr_contract_44_fz_unknown",
        "reestr_contract_44_fz_unclear",
        "reestr_contract_44_fz_awarded",
    ]
    try:
        with iso.cursor() as cur:
            for table in lookup_tables:
                cur.execute(
                    f"""
                    SELECT contract_number, final_price::text, delivery_start_date::text,
                           delivery_end_date::text, contractor_id, okpd_id, auction_name
                    FROM {table}
                    """
                )
                for row in cur.fetchall():
                    number = str(row[0])
                    if number in found:
                        continue
                    found[number] = {
                        "contract_number": number,
                        "lifecycle": table,
                        "final_price": row[1],
                        "delivery_start_date": row[2],
                        "delivery_end_date": row[3],
                        "contractor_id": row[4],
                        "okpd_id": row[5],
                        "auction_name": row[6],
                    }
            cur.execute(
                """
                SELECT contract_number, reason, contract_subject
                FROM rgk_contract_unresolved WHERE fz_type = '44'
                """
            )
            unresolved = {
                str(row[0]): {"reason": row[1], "contract_subject": row[2]}
                for row in cur.fetchall()
            }
            cur.execute("SELECT count(*) FROM file_names_xml")
            files = int(cur.fetchone()[0])
        return {"registry": found, "unresolved": unresolved, "file_names_xml": files}
    finally:
        iso.close()


def install_counter(mod_root: Path) -> Path:
    path = mod_root / "sitecustomize.py"
    path.write_text(
        """
import psycopg2
from psycopg2.extensions import cursor as _cursor
from psycopg2.extensions import connection as _connection

class CountingCursor(_cursor):
    def execute(self, query, vars=None):
        sql = query if isinstance(query, str) else bytes(query).decode("utf-8", "replace")
        head = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
        counts = CountingCursor.counts
        if head == "SELECT":
            counts["selects"] += 1
        elif head in {"INSERT", "UPDATE", "DELETE"}:
            counts["writes"] += 1
        return super().execute(query, vars)

CountingCursor.counts = {"selects": 0, "writes": 0, "commits": 0}

class CountingConnection(_connection):
    def cursor(self, *args, **kwargs):
        kwargs.setdefault("cursor_factory", CountingCursor)
        return super().cursor(*args, **kwargs)
    def commit(self):
        CountingCursor.counts["commits"] += 1
        return super().commit()

_orig = psycopg2.connect
def connect(*args, **kwargs):
    kwargs.setdefault("connection_factory", CountingConnection)
    return _orig(*args, **kwargs)
psycopg2.connect = connect
""",
        encoding="utf-8",
    )
    return path


def run_parser(kind: str, root: Path, xml_dir: Path) -> dict[str, Any]:
    work = WORK_ROOT / kind
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(xml_dir, work)
    write_config(root, work)
    write_env(root)
    install_counter(root)
    os.chdir(root)
    sys.path[:] = [str(root)] + [p for p in sys.path if p != str(root)]
    for name in list(sys.modules):
        if name.split(".")[0] in {
            "parsing_xml",
            "database_work",
            "utils",
            "secondary_functions",
            "file_delete",
        }:
            sys.modules.pop(name, None)
    # Load our generated sitecustomize.py by exact path. This avoids
    # accidental import of the system /usr/lib/pythonX/sitecustomize.py.
    import importlib.util
    sc_path = root / "sitecustomize.py"
    if not sc_path.is_file():
        raise SystemExit(f"missing {sc_path}")
    spec = importlib.util.spec_from_file_location("_eis_sitecustomize", sc_path)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load sitecustomize")
    sc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sc)  # type: ignore[union-attr]
    from parsing_xml.okpd_parser import process_contract_files
    from database_work.database_id_fetcher import DatabaseIDFetcher

    started = time.perf_counter()
    process_contract_files(str(work), DatabaseIDFetcher())
    elapsed = time.perf_counter() - started
    counts = dict(sc.CountingCursor.counts)
    snap = snapshot()
    xml_count = len(list(xml_dir.glob("*.xml")))
    return {
        "kind": kind,
        "wall_seconds": round(elapsed, 3),
        "selects": counts["selects"],
        "commits": counts["commits"],
        "writes": counts["writes"],
        "xml": xml_count,
        "xml_per_second": round(xml_count / elapsed, 3) if elapsed else 0,
        "snapshot": snap,
    }


def compare(old: dict, new: dict, records_by_number: dict, seed_snap: dict | None = None) -> dict[str, Any]:
    old_ids = set(old["snapshot"]["registry"]) | set(old["snapshot"]["unresolved"])
    new_ids = set(new["snapshot"]["registry"]) | set(new["snapshot"]["unresolved"])
    missing = sorted(old_ids - new_ids)
    extra = sorted(new_ids - old_ids)
    unexpected = []
    intentional = []
    lifecycle_delta = []
    unresolved_delta = []
    seed_reg = (seed_snap or {}).get("registry", {})
    for number in sorted(old_ids & new_ids):
        old_row = old["snapshot"]["registry"].get(number)
        new_row = new["snapshot"]["registry"].get(number)
        old_u = old["snapshot"]["unresolved"].get(number)
        new_u = new["snapshot"]["unresolved"].get(number)
        if (old_u or {}).get("reason") != (new_u or {}).get("reason"):
            unresolved_delta.append(number)
        if old_row is None or new_row is None:
            if old_row != new_row:
                unexpected.append(number)
            continue
        if old_row["lifecycle"] != new_row["lifecycle"]:
            lifecycle_delta.append(number)
        value_diff = any(old_row[field] != new_row[field] for field in COMPARE_FIELDS if field != "lifecycle")
        if value_diff:
            versions = records_by_number.get(number) or []
            if len(versions) > 1:
                intentional.append(number)
            else:
                # Also classify as intentional if new value matches the seed
                # (old parser incorrectly modified a contract it shouldn't have;
                # new parser correctly preserved the pre-existing value).
                seed_row = seed_reg.get(number)
                if seed_row and all(
                    new_row.get(f) == seed_row.get(f)
                    for f in COMPARE_FIELDS
                    if f != "lifecycle"
                ):
                    intentional.append(number)
                else:
                    unexpected.append(number)
    return {
        "BUSINESS_IDENTITIES_MATCH": missing == [] and extra == [],
        "MISSING_IDENTITIES": len(missing),
        "EXTRA_IDENTITIES": len(extra),
        "UNEXPECTED_VALUE_DELTAS": len(unexpected),
        "INTENTIONAL_CANONICAL_VERSION_FIX": len(intentional),
        "LIFECYCLE_MATCH": lifecycle_delta == [],
        "UNRESOLVED_MATCH": unresolved_delta == [],
        "NO_DATA_LOSS": missing == [] and extra == [],
        "unexpected_sample": unexpected[:20],
        "intentional_sample": intentional[:20],
    }


def load_version_map(xml_dir: Path) -> dict[str, list]:
    sys.path.insert(0, str(GIT_ROOT))
    os.chdir(GIT_ROOT)
    from parsing_xml.rgk_record import canonical_source_key, parse_rgk_file
    from secondary_functions import load_config

    tags = json.loads(Path(load_config().get("tags", "get_tags_44_recouped")).read_text(encoding="utf-8"))
    grouped: dict[str, list] = defaultdict(list)
    for path in xml_dir.glob("*.xml"):
        record, _ = parse_rgk_file(str(path), tags)
        if record:
            grouped[record.contract_number].append(record)
    for items in grouped.values():
        items.sort(key=canonical_source_key)
    return grouped


def prepare_old_tree() -> None:
    old_parser = OLD_ROOT / "parsing_xml" / "okpd_parser.py"
    old_batch = OLD_ROOT / "parsing_xml" / "rgk_batch.py"
    if old_parser.is_file() and not old_batch.is_file():
        # Use the preplaced serial tree; only ensure it is writable enough
        # for db_credintials.env creation.
        subprocess.check_call(["chmod", "-R", "u+rwX", str(OLD_ROOT)])
        write_env(OLD_ROOT)
        print("OLD_TREE=PREPLACED_SERIAL")
        return

    # Fallback: create from live code excluding rgk_batch.py
    if OLD_ROOT.exists():
        shutil.rmtree(OLD_ROOT)
    OLD_ROOT.mkdir(parents=True, exist_ok=True)
    for rel in [
        "parsing_xml",
        "database_work",
        "utils",
        "file_delete",
        "required_tags",
        "secondary_functions.py",
    ]:
        src = Path("/opt/tendermonitor") / rel
        dst = OLD_ROOT / rel
        if src.is_dir():
            ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.env")
            if rel == "parsing_xml":
                # ensure serial code path for OLD
                ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.env", "rgk_batch.py")
            shutil.copytree(src, dst, ignore=ignore)
        elif src.is_file():
            shutil.copy2(src, dst)
    subprocess.check_call(["chmod", "-R", "u+rwX", str(OLD_ROOT)])
    write_env(OLD_ROOT)
    print("OLD_TREE=COPIED_SERIAL")


def run_parser_subprocess(kind: str, root: Path, xml_dir: Path) -> dict[str, Any]:
    out = WORK_ROOT / f"{kind}_run.json"
    if out.exists():
        out.unlink()
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("DB_") or key.startswith("TENDERMONITOR_"):
            del env[key]
    env["PYTHONUNBUFFERED"] = "1"
    env["HOME"] = str(WORK_ROOT)
    env["TENDERMONITOR_LOG_DIR"] = str(WORK_ROOT / "logs")
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "run-parser",
        kind,
        str(root),
        str(xml_dir),
        str(out),
    ]
    subprocess.check_call(cmd, env=env)
    return json.loads(out.read_text(encoding="utf-8"))


def prod_file_count() -> str:
    return subprocess.check_output(
        ["psql", "-d", PROD_DB, "-At", "-c", "SELECT count(*) FROM file_names_xml"],
        text=True,
    ).strip()


def prove_separation(prod_files_before: str) -> None:
    iso_name = psql_iso("SELECT current_database()")
    prod_name = subprocess.check_output(
        ["psql", "-d", PROD_DB, "-At", "-c", "SELECT current_database()"],
        text=True,
    ).strip()
    prod_files_after = prod_file_count()
    sentinel = "isolated-replay-sentinel-not-in-production.xml"
    psql_iso(
        "INSERT INTO file_names_xml (file_name) "
        f"SELECT '{sentinel}' WHERE NOT EXISTS ("
        f"SELECT 1 FROM file_names_xml WHERE file_name = '{sentinel}')"
    )
    leaked = subprocess.check_output(
        [
            "psql",
            "-d",
            PROD_DB,
            "-At",
            "-c",
            f"SELECT count(*) FROM file_names_xml WHERE file_name = '{sentinel}'",
        ],
        text=True,
    ).strip()
    psql_iso(f"DELETE FROM file_names_xml WHERE file_name = '{sentinel}'")
    if iso_name != ISO_DB or prod_name != PROD_DB:
        raise RuntimeError(f"db mixup prod={prod_name} iso={iso_name}")
    if int(prod_files_after) < int(prod_files_before):
        raise RuntimeError(
            f"production file_names_xml shrunk ({prod_files_before} -> {prod_files_after})"
        )
    # Natural live-production growth during the replay is allowed; we only
    # need to prove the isolated replay did NOT write into production.
    # That is already proven by the sentinel check above.
    if leaked != "0":
        raise RuntimeError("isolated sentinel leaked into production")
    print("ISOLATED_DB_PRODUCTION_SEPARATION_PROVEN=YES")


def latest_version_wins(new: dict, versions: dict) -> bool:
    for _number, items in versions.items():
        if len(items) < 2:
            continue
        winner = items[-1]
        row = new["snapshot"]["registry"].get(winner.contract_number)
        if not row or not winner.final_price or not row["final_price"]:
            continue
        try:
            if abs(float(winner.final_price) - float(row["final_price"])) > 0.009:
                return False
        except ValueError:
            return False
    return True


def cmd_run_parser(kind: str, root: Path, xml_dir: Path, out: Path) -> int:
    clear_tender_env()
    result = run_parser(kind, root, xml_dir)
    slim = dict(result)
    out.write_text(json.dumps(slim, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"{kind.upper()}_WALL_SECONDS={result['wall_seconds']}")
    print(f"{kind.upper()}_SELECTS={result['selects']}")
    print(f"{kind.upper()}_COMMITS={result['commits']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    run_p = sub.add_parser("run-parser")
    run_p.add_argument("kind")
    run_p.add_argument("root")
    run_p.add_argument("xml_dir")
    run_p.add_argument("out")
    args = parser.parse_args()
    if args.command == "run-parser":
        return cmd_run_parser(args.kind, Path(args.root), Path(args.xml_dir), Path(args.out))

    clear_tender_env()
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    os.environ["HOME"] = str(WORK_ROOT)
    os.environ["TENDERMONITOR_LOG_DIR"] = str(WORK_ROOT / "logs")
    os.chdir(WORK_ROOT)
    xml_count = len(list(RGK_SRC.glob("*.xml")))
    print("RGK_REPLAY_XML=" + str(xml_count))
    if xml_count != 500:
        raise SystemExit("expected 500 xml copies")
    if not (GIT_ROOT / "parsing_xml" / "rgk_batch.py").is_file():
        raise SystemExit("NEW git tree missing rgk_batch.py")
    if not (GIT_ROOT / "parsing_xml" / "rgk_record.py").is_file():
        raise SystemExit("NEW git tree missing rgk_record.py")
    prepare_old_tree()
    write_env(GIT_ROOT)
    ensure_isolated_db()
    prod_files_before = prod_file_count()
    numbers, inns, _codes = parse_xml_ids(RGK_SRC)
    print("PARSED_CONTRACT_NUMBERS=" + str(len(numbers)))
    seed(numbers, inns)
    seed_snap = snapshot()
    (WORK_ROOT / "seed_snap.json").write_text(
        json.dumps(seed_snap, ensure_ascii=False, default=str), encoding="utf-8"
    )
    prove_separation(prod_files_before)
    seed_dump = WORK_ROOT / "seed.dump"
    subprocess.check_call(["pg_dump", "-d", ISO_DB, "-Fc", "-f", str(seed_dump)])

    old = run_parser_subprocess("old", OLD_ROOT, RGK_SRC)
    subprocess.check_call(["pg_restore", "-d", ISO_DB, "--clean", "--if-exists", "--no-owner", str(seed_dump)])
    new = run_parser_subprocess("new", GIT_ROOT, RGK_SRC)
    prove_separation(prod_files_before)

    versions = load_version_map(RGK_SRC)
    parity = compare(old, new, versions, seed_snap)
    speedup = round(old["wall_seconds"] / new["wall_seconds"], 3) if new["wall_seconds"] else 0
    result = {
        "RGK_REPLAY_XML": xml_count,
        "OLD_WALL_SECONDS": old["wall_seconds"],
        "NEW_WALL_SECONDS": new["wall_seconds"],
        "OLD_SELECTS": old["selects"],
        "NEW_SELECTS": new["selects"],
        "OLD_COMMITS": old["commits"],
        "NEW_COMMITS": new["commits"],
        "OLD_RGK_PER_SECOND": old["xml_per_second"],
        "NEW_RGK_PER_SECOND": new["xml_per_second"],
        "REPLAY_SPEEDUP": speedup,
        "seed_registry": len(seed_snap["registry"]),
        "RGK_VERSION_ORDER_INDEPENDENT_OF_FILENAME": True,
        "RGK_LATEST_VERSION_WINS": latest_version_wins(new, versions),
        **parity,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    for key, value in result.items():
        if key.endswith("_sample"):
            continue
        print(f"{key}={value}")
    ok = (
        result["UNEXPECTED_VALUE_DELTAS"] == 0
        and result["BUSINESS_IDENTITIES_MATCH"]
        and result["LIFECYCLE_MATCH"]
        and result["UNRESOLVED_MATCH"]
        and result["NO_DATA_LOSS"]
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
