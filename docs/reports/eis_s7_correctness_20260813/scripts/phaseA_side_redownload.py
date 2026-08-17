#!/usr/bin/env python3
"""Forensic re-download of 2026-08-13 notices into /tmp. No production writes."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

os.chdir("/opt/tendermonitor")
sys.path.insert(0, "/opt/tendermonitor")

import requests
from eis_download_fix import rewrite_eis_url_via_stunnel
from secondary_functions import load_config, load_token
from database_work.database_requests import get_region_codes
from utils.xml_extractor import XMLParser, clean_archive_url

ROOT = Path("/tmp/eis_correctness_20260813")
DATE = "2026-08-13"
SOAP_URL = "http://localhost:8080/eis-integration/services/getDocsIP"
PROGRESS = ROOT / "progress.jsonl"
SUMMARY = ROOT / "download_summary.json"


def emit(obj: dict) -> None:
    obj = {"ts": datetime.now().astimezone().isoformat(timespec="seconds"), **obj}
    ROOT.mkdir(parents=True, exist_ok=True)
    with PROGRESS.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(obj, ensure_ascii=False) + "\n")


def soap_body(token: str, region: str, subsystem: str, doc_type: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
        <soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                          xmlns:ws="http://zakupki.gov.ru/fz44/get-docs-ip/ws">
            <soapenv:Header>
                <individualPerson_token>{token}</individualPerson_token>
            </soapenv:Header>
            <soapenv:Body>
                <ws:getDocsByOrgRegionRequest>
                    <index>
                        <id>{uuid.uuid4()}</id>
                        <createDateTime>{datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}</createDateTime>
                        <mode>PROD</mode>
                    </index>
                    <selectionParams>
                        <orgRegion>{region}</orgRegion>
                        <subsystemType>{subsystem}</subsystemType>
                        <documentType44>{doc_type}</documentType44>
                        <periodInfo>
                            <exactDate>{DATE}</exactDate>
                        </periodInfo>
                    </selectionParams>
                </ws:getDocsByOrgRegionRequest>
            </soapenv:Body>
        </soapenv:Envelope>
        """


def soap_once(token: str, region: str, subsystem: str, doc_type: str) -> tuple[str | None, str | None]:
    headers = {"Content-Type": "text/xml", "Authorization": f"Bearer {token}"}
    last_err = None
    for attempt in range(1, 4):
        try:
            response = requests.post(
                SOAP_URL,
                data=soap_body(token, region, subsystem, doc_type).encode("utf-8"),
                headers=headers,
                verify=False,
                timeout=(10, 120),
            )
            response.raise_for_status()
            return response.text, None
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            time.sleep(min(10 * attempt, 30))
    return None, last_err


def download_zip(token: str, url: str, dest: Path) -> tuple[bool, str | None]:
    url = clean_archive_url(url)
    parsed = urlparse(url)
    name = os.path.basename(parsed.path) or f"file_{uuid.uuid4().hex[:8]}.zip"
    if not name.lower().endswith(".zip"):
        name = f"{name}.zip"
    path = dest / name
    headers = {"individualPerson_token": token}
    try:
        rewritten = rewrite_eis_url_via_stunnel(url)
        response = requests.get(rewritten, stream=True, headers=headers, timeout=120, verify=False)
        response.raise_for_status()
        with path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    handle.write(chunk)
        return True, str(path)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def unzip_keep(zip_path: Path, xml_dir: Path) -> int:
    count = 0
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(xml_dir)
            count = sum(1 for info in zf.infolist() if info.filename.lower().endswith(".xml"))
    except Exception:
        return 0
    return count


def load_done() -> set[str]:
    done = set()
    if not PROGRESS.exists():
        return done
    for raw in PROGRESS.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(raw)
        except Exception:
            continue
        if rec.get("event") == "contour_done":
            done.add(f"{rec.get('region')}|{rec.get('subsystem')}|{rec.get('doc_type')}")
    return done


def main() -> None:
    requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]
    ROOT.mkdir(parents=True, exist_ok=True)
    config = load_config()
    token = load_token(config)
    if not token:
        raise SystemExit("token missing")
    regions = [str(r) for r in get_region_codes()]
    priz_types = [d.strip() for d in config.get("eis", "documentType44_PRIZ").split(",") if d.strip()]
    ri223_types = [d.strip() for d in config.get("eis", "documentType223_RI223").split(",") if d.strip()]
    enabled_615 = False
    regions_615: set[str] = set()
    doctypes_615: list[str] = []
    subsystem_615 = "RD615"
    if config.has_section("eis_615"):
        enabled_615 = config.getboolean("eis_615", "enabled", fallback=False)
        subsystem_615 = config.get("eis_615", "subsystem", fallback="RD615")
        doctypes_615 = [d.strip() for d in config.get("eis_615", "documenttypes", fallback="").split(",") if d.strip()]
        regions_615 = {r.strip() for r in config.get("eis_615", "regions", fallback="77,50").split(",") if r.strip()}

    jobs: list[tuple[str, str, str, str]] = []
    for region in regions:
        for doc_type in priz_types:
            jobs.append((region, "PRIZ", doc_type, "44_NOTICE"))
        for doc_type in ri223_types:
            jobs.append((region, "RI223", doc_type, "223_NOTICE"))
        if enabled_615 and region in regions_615:
            for doc_type in doctypes_615:
                jobs.append((region, subsystem_615, doc_type, "615"))

    done = load_done()
    emit({"event": "start", "jobs": len(jobs), "already_done": len(done), "regions": len(regions)})
    errors = 0
    archives = 0
    xml_count = 0
    extractor = XMLParser()
    for region, subsystem, doc_type, contour in jobs:
        key = f"{region}|{subsystem}|{doc_type}"
        if key in done:
            continue
        xml, err = soap_once(token, region, subsystem, doc_type)
        if err:
            errors += 1
            emit({"event": "soap_error", "region": region, "subsystem": subsystem, "doc_type": doc_type, "error": err})
            emit({"event": "contour_done", "region": region, "subsystem": subsystem, "doc_type": doc_type, "ok": False})
            continue
        urls = [clean_archive_url(u) for u in extractor.extract_archive_urls(xml or "") if u]
        zip_dir = ROOT / "archives" / contour / region / subsystem / doc_type
        xml_dir = ROOT / "xml" / contour / region
        zip_dir.mkdir(parents=True, exist_ok=True)
        xml_dir.mkdir(parents=True, exist_ok=True)
        got = 0
        xmls = 0
        for url in urls:
            ok, detail = download_zip(token, url, zip_dir)
            if not ok:
                errors += 1
                emit({"event": "download_error", "region": region, "contour": contour, "error": detail})
                continue
            archives += 1
            got += 1
            xmls += unzip_keep(Path(detail), xml_dir)
        xml_count += xmls
        emit(
            {
                "event": "contour_done",
                "region": region,
                "subsystem": subsystem,
                "doc_type": doc_type,
                "contour": contour,
                "urls": len(urls),
                "zips": got,
                "xml": xmls,
                "ok": True,
            }
        )
        time.sleep(0.4)

    summary = {
        "date": DATE,
        "regions": len(regions),
        "jobs": len(jobs),
        "errors": errors,
        "archives": archives,
        "xml_extracted": xml_count,
        "root": str(ROOT),
        "production_writes": "NONE",
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    emit({"event": "finished", **summary})
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
