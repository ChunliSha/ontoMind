"""End-to-end smoke test against a running KnowMind API."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000/api/v1"
PASS = 0
FAIL = 0


def req(method: str, path: str, body: dict | None = None, files: bool = False):
    url = BASE + path if path.startswith("/") else f"{BASE}/{path}"
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw
        return e.code, payload


def check(name: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[ OK ] {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"[FAIL] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    # health
    with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=10) as r:
        health = json.loads(r.read().decode())
    check("health", health.get("status") == "ok", str(health))

    # dashboard
    code, summary = req("GET", "/dashboard/summary")
    check("dashboard summary", code == 200, str(summary))

    code, activity = req("GET", "/dashboard/activity")
    check("dashboard activity", code == 200)

    # schema create
    code, schema = req("POST", "/schemas", {"name": f"Smoke Schema {int(time.time())}"})
    check("create schema", code in (200, 201), str(schema))
    schema_id = schema["id"]

    # class + property
    code, cls = req(
        "POST",
        f"/schemas/{schema_id}/classes",
        {"label": "设备", "description": "smoke class"},
    )
    check("create class", code in (200, 201), str(cls))
    class_id = cls["id"]

    code, prop = req(
        "POST",
        f"/classes/{class_id}/properties",
        {"label": "设备编号", "kind": "data", "datatype": "xsd:string", "required": True},
    )
    check("create property", code in (200, 201), str(prop))

    # publish
    code, published = req("POST", f"/schemas/{schema_id}/publish", {"change_log": "smoke"})
    check("publish schema", code == 200, f"v{published.get('version')}")

    # export ttl
    url = f"{BASE}/schemas/{schema_id}/export-ttl"
    with urllib.request.urlopen(url, timeout=20) as r:
        ttl = r.read().decode("utf-8")
    check("export ttl", "owl:Class" in ttl or "设备" in ttl, ttl[:120].replace("\n", " "))

    # file upload via multipart
    boundary = "----SmokeBoundary"
    content = b"# smoke doc\ntransformer GY-01 oil temp 90C\n"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="smoke.txt"\r\n'
        f"Content-Type: text/plain\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"storage_backend\"\r\n\r\nlocal\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        f"{BASE}/files",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as resp:
        file_obj = json.loads(resp.read().decode())
    check("upload file", "id" in file_obj, file_obj.get("status"))
    file_id = file_obj["id"]

    # wait ready
    ready = False
    for _ in range(20):
        time.sleep(0.3)
        code, f = req("GET", f"/files/{file_id}")
        if f and f.get("status") == "ready":
            ready = True
            break
    check("file parse ready", ready, f.get("status") if f else "n/a")

    # unstructured extraction
    code, task = req(
        "POST",
        "/extraction/instances/unstructured",
        {"schema_id": schema_id, "file_ids": [file_id]},
    )
    check("start unstructured extract", code in (200, 202), str(task))
    task_id = task["task_id"]

    succeeded = False
    last = None
    for _ in range(40):
        time.sleep(0.4)
        code, last = req("GET", f"/extraction/tasks/{task_id}")
        if last and last.get("status") in ("succeeded", "failed"):
            succeeded = last["status"] == "succeeded"
            break
    check("extraction finished", succeeded, str(last))

    # graph
    code, graph = req("GET", f"/graph?schema_id={schema_id}&mode=mixed")
    check("graph mixed", code == 200 and "nodes" in graph, f"nodes={len(graph.get('nodes', []))}")

    # biz logic dependency — should work if instances exist, else BIZLOGIC_001
    code, biz = req(
        "POST",
        "/extraction/business-logic",
        {"schema_id": schema_id, "file_ids": [file_id]},
    )
    check(
        "business logic extract",
        code in (200, 202) or (code == 400 and isinstance(biz, dict) and biz.get("error", {}).get("code") == "BIZLOGIC_001"),
        str(biz)[:160],
    )

    print()
    print(f"Passed {PASS}, failed {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
