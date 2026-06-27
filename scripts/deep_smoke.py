import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from app.repositories import (  # noqa: E402
    SQLiteRepository,
    backup_database,
    restore_database,
)


def available_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


PORT = int(os.environ.get("DEEP_SMOKE_PORT", "0")) or available_port()
BASE_URL = f"http://127.0.0.1:{PORT}"
ORIGIN = "https://frontend.example"
TOKEN = "deep-smoke-token-" + "x" * 32
MODEL_LIMIT = 30


class SmokeFailure(RuntimeError):
    pass


def http_request(method, path, *, body=None, headers=None, timeout=10):
    request_headers = dict(headers or {})
    data = None
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            request_headers.setdefault(
                "Content-Type", "application/json; charset=utf-8"
            )
        elif isinstance(body, str):
            data = body.encode("utf-8")
    request = Request(
        BASE_URL + path, data=data, headers=request_headers, method=method
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = response.status
            response_headers = dict(response.headers.items())
    except HTTPError as error:
        raw = error.read()
        status = error.code
        response_headers = dict(error.headers.items())
    payload = None
    if raw:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            payload = raw.decode("utf-8", errors="replace")
    return status, response_headers, payload


def header(headers, name):
    return next(
        (value for key, value in headers.items() if key.lower() == name.lower()), None
    )


def require(condition, message):
    if not condition:
        raise SmokeFailure(message)


def main():
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_dir = ROOT / "reports" / "smoke"
    report_dir.mkdir(parents=True, exist_ok=True)
    database = ROOT / "data" / f"deep-smoke-{uuid4()}.db"
    backup = report_dir / f"deep-smoke-{timestamp}.db"
    log_path = report_dir / f"deep-smoke-{timestamp}.log"
    results = []
    failures = []
    state = {}
    process = None

    def run_case(name, operation):
        started = time.perf_counter()
        try:
            details = operation() or "ok"
            status = "passed"
        except Exception as error:
            details = str(error)
            status = "failed"
            failures.append(f"{name}: {error}")
        results.append(
            {
                "scenario": name,
                "status": status,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "details": details,
            }
        )

    auth_headers = {
        "X-Demo-Token": TOKEN,
        "CF-Connecting-IP": "203.0.113.10",
        "Origin": ORIGIN,
    }
    environment = os.environ.copy()
    environment.update(
        {
            "APP_MODE": "demo",
            "ANSWER_PATH": "advanced",
            "STORAGE_MODE": "sqlite",
            "DATABASE_PATH": str(database),
            "PUBLIC_DEMO": "true",
            "DEMO_API_TOKEN": TOKEN,
            "MODEL_RATE_LIMIT_PER_MINUTE": str(MODEL_LIMIT),
            "CORS_ORIGINS": ORIGIN,
            "PYTHONIOENCODING": "utf-8",
        }
    )

    log_file = log_path.open("w", encoding="utf-8")
    try:
        creation_flags = 0x08000000 if os.name == "nt" else 0
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(PORT),
            ],
            cwd=ROOT,
            env=environment,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
        )

        def wait_for_health():
            for _ in range(80):
                try:
                    status, _, payload = http_request("GET", "/health", timeout=1)
                    if status == 200 and payload == {"status": "ok"}:
                        return "server ready"
                except OSError:
                    pass
                time.sleep(0.25)
            raise SmokeFailure("server did not become healthy")

        run_case("startup", wait_for_health)

        def authentication():
            require(http_request("GET", "/health")[0] == 200, "health must be public")
            require(http_request("GET", "/ready")[0] == 401, "ready accepted no token")
            require(
                http_request("GET", "/ready", headers={"X-Demo-Token": "bad"})[0]
                == 401,
                "ready accepted an invalid token",
            )
            require(
                http_request("GET", "/ready", headers=auth_headers)[0] == 200,
                "ready rejected the valid token",
            )
            for path in ("/docs", "/redoc", "/openapi.json"):
                require(http_request("GET", path)[0] == 404, f"{path} is public")
            return "public health, protected API, hidden docs"

        run_case("authentication", authentication)

        def strict_cors():
            allowed = http_request(
                "OPTIONS",
                "/ask",
                headers={
                    "Origin": ORIGIN,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "x-demo-token,content-type",
                },
            )
            denied = http_request(
                "OPTIONS",
                "/ask",
                headers={
                    "Origin": "https://attacker.example",
                    "Access-Control-Request-Method": "POST",
                },
            )
            require(
                header(allowed[1], "Access-Control-Allow-Origin") == ORIGIN,
                "allowed origin missing",
            )
            require(
                header(denied[1], "Access-Control-Allow-Origin") is None,
                "unknown origin allowed",
            )
            return "exact frontend origin only"

        run_case("strict_cors", strict_cors)

        def utf8_json():
            status, headers, payload = http_request(
                "GET",
                "/faq",
                headers={**auth_headers, "X-Request-ID": "deep-smoke-request"},
            )
            require(status == 200, "FAQ failed")
            require(
                "charset=utf-8" in (header(headers, "Content-Type") or ""),
                "UTF-8 charset missing",
            )
            require(
                payload["items"][0]["q"].startswith("研究室"), "Japanese text corrupted"
            )
            require(
                header(headers, "X-Request-ID") == "deep-smoke-request",
                "request ID not preserved",
            )
            return "Japanese JSON and request IDs verified"

        run_case("utf8_json", utf8_json)

        def happy_endpoints():
            known = http_request(
                "POST",
                "/ask",
                headers=auth_headers,
                body={
                    "message": "輝度つまみはどこですか？",
                    "session_id": "deep-session",
                },
            )
            require(known[0] == 200 and not known[2]["is_gap"], "known fixture failed")
            require(bool(known[2]["citations"]), "known fixture has no citations")
            first_gap = http_request(
                "POST",
                "/ask",
                headers=auth_headers,
                body={"message": "未登録の手順", "session_id": "deep-session"},
            )
            require(
                first_gap[0] == 200 and first_gap[2]["is_gap"], "gap fixture failed"
            )
            gaps = http_request("GET", "/gaps", headers=auth_headers)[2]["gaps"]
            state["first_seen"] = next(
                item["first_seen"]
                for item in gaps
                if item["question"] == "未登録の手順"
            )
            onboarding = http_request(
                "POST",
                "/onboarding",
                headers=auth_headers,
                body={"role": "M1", "field": "光学"},
            )
            require(
                onboarding[0] == 200 and onboarding[2]["guide"], "onboarding failed"
            )
            feedback = http_request(
                "POST",
                "/feedback",
                headers=auth_headers,
                body={
                    "session_id": "deep-session",
                    "message": "answer",
                    "rating": "up",
                },
            )
            require(feedback[0] == 200 and feedback[2]["ok"], "feedback failed")
            return "all public endpoints"

        run_case("happy_endpoints", happy_endpoints)

        def validation_errors():
            cases = [
                ("/ask", {"message": "   "}),
                (
                    "/ask",
                    {
                        "message": "question",
                        "current_state": {"active_figure_id": "unknown"},
                    },
                ),
                ("/onboarding", {"role": "M2"}),
                (
                    "/feedback",
                    {"session_id": "s", "message": "a", "rating": "sideways"},
                ),
            ]
            for path, body in cases:
                require(
                    http_request("POST", path, headers=auth_headers, body=body)[0]
                    == 422,
                    f"{path} accepted invalid input",
                )
            require(
                http_request(
                    "POST",
                    "/ask",
                    headers={**auth_headers, "Content-Type": "application/json"},
                    body="{not-json",
                )[0]
                == 422,
                "malformed JSON accepted",
            )
            return "invalid values and malformed JSON rejected"

        run_case("validation_errors", validation_errors)

        def gap_deduplication():
            second = http_request(
                "POST",
                "/ask",
                headers=auth_headers,
                body={"message": "未登録の手順", "session_id": "deep-session"},
            )
            require(second[0] == 200 and second[2]["is_gap"], "second gap failed")
            gaps = http_request("GET", "/gaps", headers=auth_headers)[2]["gaps"]
            item = next(item for item in gaps if item["question"] == "未登録の手順")
            require(item["count"] == 2, "gap count was not incremented")
            require(item["first_seen"] == state["first_seen"], "first_seen changed")
            return "count=2 and first_seen stable"

        run_case("gap_deduplication", gap_deduplication)

        def concurrent_requests():
            def ask(number):
                return http_request(
                    "POST",
                    "/ask",
                    headers=auth_headers,
                    body={
                        "message": "輝度つまみはどこですか？",
                        "session_id": f"concurrent-{number}",
                    },
                )[0]

            with ThreadPoolExecutor(max_workers=10) as pool:
                statuses = list(pool.map(ask, range(10)))
            require(statuses == [200] * 10, f"concurrent statuses: {statuses}")
            return "10 concurrent fixture requests"

        run_case("concurrent_requests", concurrent_requests)

        def bounded_history():
            statuses = [
                http_request(
                    "POST",
                    "/ask",
                    headers=auth_headers,
                    body={
                        "message": "輝度つまみはどこですか？",
                        "session_id": "history-session",
                    },
                )[0]
                for _ in range(12)
            ]
            require(statuses == [200] * 12, f"history requests failed: {statuses}")
            return "12 turns written for 10-turn retention check"

        run_case("bounded_history", bounded_history)

        def rate_limit():
            status, headers, _ = http_request(
                "POST",
                "/ask",
                headers=auth_headers,
                body={"message": "輝度つまみはどこですか？"},
            )
            require(status == 429, f"expected 429, got {status}")
            require(header(headers, "Retry-After"), "Retry-After missing")
            return "31st model request rejected"

        run_case("rate_limit", rate_limit)
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        log_file.close()

    def persistence_checks():
        with closing(sqlite3.connect(database)) as connection:
            feedback_count = connection.execute(
                "SELECT COUNT(*) FROM feedback"
            ).fetchone()[0]
            history_count = connection.execute(
                "SELECT COUNT(*) FROM interactions WHERE session_id = 'history-session'"
            ).fetchone()[0]
        require(feedback_count == 1, f"feedback count={feedback_count}")
        require(history_count == 10, f"history count={history_count}")
        return "feedback persisted and history pruned to 10"

    run_case("persistence", persistence_checks)

    def backup_restore():
        backup_database(database, backup)
        repository = SQLiteRepository(database, history_limit=10)
        repository.log_gap("after-backup mutation")
        restore_database(backup, database, overwrite=True)
        restored = SQLiteRepository(database, history_limit=10)
        questions = [item.question for item in restored.list_gaps()]
        require("未登録の手順" in questions, "baseline gap missing after restore")
        require(
            "after-backup mutation" not in questions,
            "post-backup mutation survived restore",
        )
        return "integrity-checked backup restored"

    run_case("backup_restore", backup_restore)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "offline-public-demo",
        "scenarios": results,
        "passed": len(results) - len(failures),
        "failed": len(failures),
    }
    json_path = report_dir / f"deep-smoke-{timestamp}.json"
    markdown_path = report_dir / f"deep-smoke-{timestamp}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Deep Smoke Report",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Passed: {report['passed']}",
        f"- Failed: {report['failed']}",
        "",
        "| Scenario | Status | Latency (ms) | Details |",
        "|---|---:|---:|---|",
    ]
    lines.extend(
        "| {scenario} | {status} | {latency_ms} | {details} |".format(**item)
        for item in results
    )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cleanup_paths = [database, Path(f"{database}-wal"), Path(f"{database}-shm"), backup]
    cleanup_paths.extend(database.parent.glob(f"{database.stem}.pre-restore-*.db"))
    for path in cleanup_paths:
        path.unlink(missing_ok=True)

    print(f"Deep smoke: {report['passed']} passed, {report['failed']} failed")
    print(f"Report: {markdown_path}")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
