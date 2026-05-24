from __future__ import annotations

import argparse
import json
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import run_validation as rv


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate(value: Any, limit: int = 240) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


class ObserverDiagnostics:
    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    def emit(self, level: str, event: str, message: str, **details: Any) -> None:
        payload = {
            "ts": _utc_now(),
            "level": level,
            "event": event,
            "message": message,
            "details": details,
        }
        self.events.append(payload)
        suffix = ""
        if details:
            compact = ", ".join(f"{key}={_truncate(value, 80)}" for key, value in details.items())
            suffix = f" | {compact}"
        rv._log(f"[observer/{level}] {event}: {message}{suffix}")

    def write(self, out_dir: Path) -> Dict[str, str]:
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / "observer_validation_diagnostics.json"
        log_path = out_dir / "observer_validation_diagnostics.log"
        with json_path.open("w", encoding="utf-8") as fh:
            json.dump(self.events, fh, ensure_ascii=False, indent=2)
        with log_path.open("w", encoding="utf-8") as fh:
            for item in self.events:
                details = item.get("details") or {}
                compact = " ".join(f"{key}={_truncate(value, 160)}" for key, value in details.items())
                line = f"{item['ts']} [{item['level']}] {item['event']} {item['message']}"
                if compact:
                    line += f" :: {compact}"
                fh.write(line + "\n")
        return {
            "diagnostics_json": str(json_path),
            "diagnostics_log": str(log_path),
        }


def _observer_result(
    validation_passed: bool,
    error: Optional[str],
    artifacts: Dict[str, str],
    diagnostics: ObserverDiagnostics,
    *,
    total_rows_checked: int = 0,
    plaintext_rows_detected: int = 0,
    plaintext_detection_rate: float = 0.0,
    errors: int = 0,
    access_path: str = "",
) -> Dict[str, Any]:
    return {
        "total_rows_checked": total_rows_checked,
        "plaintext_rows_detected": plaintext_rows_detected,
        "plaintext_detection_rate": plaintext_detection_rate,
        "validation_passed": validation_passed,
        "errors": errors,
        "access_path": access_path,
        "artifacts": artifacts,
        "error": error,
        "diagnostics_events": len(diagnostics.events),
    }


def _build_state(config: rv.ValidationConfig) -> rv.ValidationState:
    rng = rv.random.Random(config.seed)
    return rv.ValidationState(
        config=config,
        rng=rng,
        users=rv.load_seed_users(rv.DEFAULT_USERS_PATH),
        resources_by_type=rv.build_resources(rng),
        policies=rv.build_policies(),
    )


def _init_state_if_needed(config: Optional[rv.ValidationConfig] = None) -> rv.ValidationState:
    if rv.STATE is not None:
        return rv.STATE
    if config is None:
        raise RuntimeError("validation state not initialized")
    rv.STATE = _build_state(config)
    return rv.STATE


def _run_docker_psql_logged(diagnostics: ObserverDiagnostics, sql: str, purpose: str) -> Any:
    diagnostics.emit("info", "docker_psql_run", f"docker psql for {purpose}", sql=sql)
    result = rv._run_docker_psql(sql)
    diagnostics.emit(
        "info" if result.returncode == 0 else "error",
        "docker_psql_result",
        f"docker psql completed for {purpose}",
        purpose=purpose,
        returncode=result.returncode,
        stdout=_truncate(result.stdout, 400),
        stderr=_truncate(result.stderr, 400),
    )
    return result


def _resolve_entries_tables_fallback_logged(diagnostics: ObserverDiagnostics) -> List[str]:
    result = _run_docker_psql_logged(diagnostics, "SELECT to_regclass('fabeo.entries')::text;", "resolve_entries_table")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "docker psql lookup failed")
    table_name = result.stdout.strip()
    return [table_name] if table_name and table_name != "null" else []


def _fetch_entry_row_fallback_logged(
    diagnostics: ObserverDiagnostics,
    table_name: str,
    entry_id: str,
) -> Optional[Tuple[str, str, bytes]]:
    sql = (
        "SELECT entry_id::text, resource_type, encode(encrypted_payload, 'base64') "
        f"FROM {table_name} WHERE entry_id = '{entry_id}'::uuid;"
    )
    result = _run_docker_psql_logged(diagnostics, sql, f"fetch_entry_row:{entry_id}")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "docker psql row fetch failed")
    output = result.stdout.strip()
    if not output:
        return None
    parts = output.split("\t")
    if len(parts) != 3:
        raise RuntimeError(f"unexpected docker psql row format: {output}")
    return parts[0], parts[1], rv.base64.b64decode(parts[2].encode("ascii"))


def run_db_observer_validation(diagnostics: Optional[ObserverDiagnostics] = None) -> Dict[str, Any]:
    state = _init_state_if_needed()
    diagnostics = diagnostics or ObserverDiagnostics()
    diagnostics.emit(
        "info",
        "observer_start",
        "db observer validation start",
        iterations=state.config.iterations,
        base_url=state.config.base_url,
        db_access="psql_only",
    )

    raw_metrics: List[Dict[str, Any]] = []
    rows_out: List[Dict[str, Any]] = []
    created_entries: List[Tuple[str, str]] = []
    attempt_context: Dict[str, Dict[str, Any]] = {}
    error_count = 0

    create_bar = rv.ProgressBar(state.config.iterations, "DB observer create")
    for i in range(state.config.iterations):
        attempt_id = f"db_observer-{i + 1:05d}"
        attempt_start = time.perf_counter()
        resource = state.rng.choice(state.resources_by_type["Patient"])
        entry_id = ""
        login_ms = None
        create_ms = None

        try:
            session, login_ms = rv._login_user(state.users["doctor_general_clinic"])
            policy = next(item for item in state.policies if item.name == "patient_demographics")
            create_t0 = time.perf_counter()
            create_resp = rv.create_entry(session, resource.resource, policy.expression)
            create_ms = (time.perf_counter() - create_t0) * 1000.0
            entry_id = create_resp.json()["entry_id"]
            created_entries.append((entry_id, resource.resource_type))
            attempt_context[entry_id] = {
                "attempt_id": attempt_id,
                "attempt_start": attempt_start,
                "login_ms": login_ms,
                "create_ms": create_ms,
                "original_payload_bytes": len(json.dumps(resource.resource, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
            }
            diagnostics.emit(
                "info",
                "entry_created",
                "observer seed entry created",
                attempt_id=attempt_id,
                entry_id=entry_id,
                resource_type=resource.resource_type,
                login_ms=round(login_ms or 0.0, 3),
                create_ms=round(create_ms, 3),
            )
        except Exception as exc:  # noqa: BLE001
            error_count += 1
            diagnostics.emit(
                "error",
                "entry_create_failed",
                "failed to create observer validation entry",
                attempt_id=attempt_id,
                error=str(exc),
                traceback=traceback.format_exc(),
            )
            raw_metrics.append({
                "attempt_id": attempt_id,
                "validation_stage": rv.STAGE_DB,
                "scenario": rv.STAGE_DB,
                "latency_login_ms": login_ms,
                "latency_create_ms": create_ms,
                "latency_search_ms": None,
                "latency_decrypt_ms": None,
                "latency_db_check_ms": None,
                "total_attempt_latency_ms": (time.perf_counter() - attempt_start) * 1000.0,
                "original_payload_bytes": len(json.dumps(resource.resource, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
                "encrypted_payload_bytes": None,
                "cipher_metadata_response_bytes": None,
                "decrypt_response_bytes": None,
            })
            rows_out.append({
                "table_name": "",
                "entry_id": entry_id,
                "resource_type": resource.resource_type,
                "encrypted_payload_size_bytes": None,
                "looks_like_json": False,
                "json_parse_success": False,
                "contains_fhir_markers": False,
                "plaintext_detected": False,
                "detected_markers": "",
                "check_latency_ms": None,
                "error_message": str(exc),
            })
        finally:
            create_bar.update(1)

    access_path = "docker_psql"
    try:
        tables = _resolve_entries_tables_fallback_logged(diagnostics)
        if not tables:
            diagnostics.emit("error", "entries_table_missing", "entries table not found via psql", access_path=access_path)
            artifacts = diagnostics.write(state.config.out_dir / "db_observer")
            return _observer_result(False, "entries table not found", artifacts, diagnostics, errors=error_count, access_path=access_path)

        table_name = tables[0]
        diagnostics.emit("info", "entries_table_selected", "using entries table", access_path=access_path, table_name=table_name)
        check_bar = rv.ProgressBar(len(created_entries), "DB observer check")
        for entry_id, resource_type in created_entries:
            context = attempt_context.get(entry_id, {})
            check_t0 = time.perf_counter()
            try:
                row = _fetch_entry_row_fallback_logged(diagnostics, table_name, entry_id)
                db_check_ms = (time.perf_counter() - check_t0) * 1000.0
                if not row:
                    error_count += 1
                    diagnostics.emit(
                        "error",
                        "entry_missing",
                        "observer row missing in database",
                        access_path=access_path,
                        table_name=table_name,
                        entry_id=entry_id,
                        resource_type=resource_type,
                    )
                    rows_out.append({
                        "table_name": table_name,
                        "entry_id": entry_id,
                        "resource_type": resource_type,
                        "encrypted_payload_size_bytes": None,
                        "looks_like_json": False,
                        "json_parse_success": False,
                        "contains_fhir_markers": False,
                        "plaintext_detected": False,
                        "detected_markers": "",
                        "check_latency_ms": db_check_ms,
                        "error_message": "entry not found in table",
                    })
                    raw_metrics.append({
                        "attempt_id": context.get("attempt_id", "db_observer-missing"),
                        "validation_stage": rv.STAGE_DB,
                        "scenario": rv.STAGE_DB,
                        "latency_login_ms": context.get("login_ms"),
                        "latency_create_ms": context.get("create_ms"),
                        "latency_search_ms": None,
                        "latency_decrypt_ms": None,
                        "latency_db_check_ms": db_check_ms,
                        "total_attempt_latency_ms": (time.perf_counter() - context.get("attempt_start", check_t0)) * 1000.0,
                        "original_payload_bytes": context.get("original_payload_bytes"),
                        "encrypted_payload_bytes": None,
                        "cipher_metadata_response_bytes": None,
                        "decrypt_response_bytes": None,
                    })
                    continue

                _, stored_type, payload = row
                payload_bytes_len = len(payload)
                detection = rv.detect_plaintext_json_in_encrypted_payload(payload)
                diagnostics.emit(
                    "info",
                    "row_checked",
                    "observer row inspected",
                    access_path=access_path,
                    table_name=table_name,
                    entry_id=entry_id,
                    resource_type=stored_type,
                    encrypted_payload_size_bytes=payload_bytes_len,
                    plaintext_detected=detection["plaintext_detected"],
                    detected_markers=detection["detected_markers"],
                )
                rows_out.append({
                    "table_name": table_name,
                    "entry_id": entry_id,
                    "resource_type": stored_type,
                    "encrypted_payload_size_bytes": payload_bytes_len,
                    "looks_like_json": detection["looks_like_json"],
                    "json_parse_success": detection["json_parse_success"],
                    "contains_fhir_markers": detection["contains_fhir_markers"],
                    "plaintext_detected": detection["plaintext_detected"],
                    "detected_markers": detection["detected_markers"],
                    "check_latency_ms": db_check_ms,
                    "error_message": "",
                })
                raw_metrics.append({
                    "attempt_id": context.get("attempt_id", f"db_observer-{entry_id}"),
                    "validation_stage": rv.STAGE_DB,
                    "scenario": rv.STAGE_DB,
                    "latency_login_ms": context.get("login_ms"),
                    "latency_create_ms": context.get("create_ms"),
                    "latency_search_ms": None,
                    "latency_decrypt_ms": None,
                    "latency_db_check_ms": db_check_ms,
                    "total_attempt_latency_ms": (time.perf_counter() - context.get("attempt_start", check_t0)) * 1000.0,
                    "original_payload_bytes": context.get("original_payload_bytes"),
                    "encrypted_payload_bytes": payload_bytes_len,
                    "cipher_metadata_response_bytes": None,
                    "decrypt_response_bytes": None,
                })
            except Exception as exc:  # noqa: BLE001
                error_count += 1
                db_check_ms = (time.perf_counter() - check_t0) * 1000.0
                diagnostics.emit(
                    "error",
                    "row_check_failed",
                    "observer row fetch failed",
                    access_path=access_path,
                    table_name=table_name,
                    entry_id=entry_id,
                    error=str(exc),
                    traceback=traceback.format_exc(),
                )
                rows_out.append({
                    "table_name": table_name,
                    "entry_id": entry_id,
                    "resource_type": resource_type,
                    "encrypted_payload_size_bytes": None,
                    "looks_like_json": False,
                    "json_parse_success": False,
                    "contains_fhir_markers": False,
                    "plaintext_detected": False,
                    "detected_markers": "",
                    "check_latency_ms": db_check_ms,
                    "error_message": str(exc),
                })
                raw_metrics.append({
                    "attempt_id": context.get("attempt_id", f"db_observer-{entry_id}"),
                    "validation_stage": rv.STAGE_DB,
                    "scenario": rv.STAGE_DB,
                    "latency_login_ms": context.get("login_ms"),
                    "latency_create_ms": context.get("create_ms"),
                    "latency_search_ms": None,
                    "latency_decrypt_ms": None,
                    "latency_db_check_ms": db_check_ms,
                    "total_attempt_latency_ms": (time.perf_counter() - context.get("attempt_start", check_t0)) * 1000.0,
                    "original_payload_bytes": context.get("original_payload_bytes"),
                    "encrypted_payload_bytes": None,
                    "cipher_metadata_response_bytes": None,
                    "decrypt_response_bytes": None,
                })
            finally:
                check_bar.update(1)
    except Exception as exc:  # noqa: BLE001
        diagnostics.emit(
            "error",
            "psql_access_failed",
            "psql access failed; aborting observer validation",
            access_path=access_path,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        artifacts = diagnostics.write(state.config.out_dir / "db_observer")
        return _observer_result(False, f"psql access failed: {exc}", artifacts, diagnostics, errors=error_count + 1, access_path=access_path)

    total_rows_checked = len(rows_out)
    plaintext_rows_detected = sum(1 for row in rows_out if row.get("plaintext_detected"))
    detection_rate = (plaintext_rows_detected / total_rows_checked * 100.0) if total_rows_checked else 0.0
    validation_passed = total_rows_checked > 0 and plaintext_rows_detected == 0 and error_count == 0

    base_dir = state.config.out_dir / "db_observer"
    rows_path = base_dir / "db_observer_rows.csv"
    summary_path = base_dir / "db_observer_summary.csv"
    row_fields = [
        "table_name",
        "entry_id",
        "resource_type",
        "encrypted_payload_size_bytes",
        "looks_like_json",
        "json_parse_success",
        "contains_fhir_markers",
        "plaintext_detected",
        "detected_markers",
        "check_latency_ms",
        "error_message",
    ]
    rv._write_csv(rows_path, row_fields, rows_out)
    rv._write_csv(
        summary_path,
        ["total_rows_checked", "plaintext_rows_detected", "plaintext_detection_rate", "validation_passed", "errors", "access_path"],
        [{
            "total_rows_checked": total_rows_checked,
            "plaintext_rows_detected": plaintext_rows_detected,
            "plaintext_detection_rate": detection_rate,
            "validation_passed": validation_passed,
            "errors": error_count,
            "access_path": access_path,
        }],
    )
    quant_artifacts = rv.write_quantitative_csv(state.config.out_dir, rv.STAGE_DB, None, raw_metrics)
    diagnostics.emit(
        "info" if validation_passed else "warning",
        "observer_finish",
        "db observer validation completed",
        total_rows_checked=total_rows_checked,
        plaintext_rows_detected=plaintext_rows_detected,
        errors=error_count,
        validation_passed=validation_passed,
        access_path=access_path,
    )
    diagnostic_artifacts = diagnostics.write(base_dir)
    return _observer_result(
        validation_passed,
        None if validation_passed else "observer validation failed; inspect diagnostics artifacts",
        {
            "rows_csv": str(rows_path),
            "summary_csv": str(summary_path),
            **quant_artifacts,
            **diagnostic_artifacts,
        },
        diagnostics,
        total_rows_checked=total_rows_checked,
        plaintext_rows_detected=plaintext_rows_detected,
        plaintext_detection_rate=detection_rate,
        errors=error_count,
        access_path=access_path,
    )


def parse_args(argv: Optional[List[str]] = None) -> rv.ValidationConfig:
    parser = argparse.ArgumentParser(description="Run only the MACHS2 database observer validation step")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--out-dir", default=str(rv.DEFAULT_OUT_DIR))
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args(argv)
    return rv.ValidationConfig(
        base_url=args.base_url,
        iterations=args.iterations,
        mode="fabeo",
        out_dir=Path(args.out_dir),
        seed=args.seed,
        db_dsn=None,
    )


def main(argv: Optional[List[str]] = None) -> int:
    try:
        rv.sys.stdout.reconfigure(encoding="utf-8")
        rv.sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    config = parse_args(argv)
    rv.STATE = _build_state(config)
    diagnostics = ObserverDiagnostics()
    try:
        diagnostics.emit("info", "smoke_start", "observer standalone smoke start")
        rv.STATE.smoke = rv.run_smoke_test(config)
        rv.STATE.revocation_enabled = bool(rv.STATE.smoke.get("health", {}).get("revocation_enabled", False))
        rv.STATE.current_epoch = str(rv.STATE.smoke.get("health", {}).get("current_epoch", ""))
        diagnostics.emit(
            "info",
            "smoke_ok",
            "observer standalone smoke ok",
            current_epoch=rv.STATE.current_epoch,
            revocation_enabled=rv.STATE.revocation_enabled,
        )
    except Exception as exc:  # noqa: BLE001
        diagnostics.emit("error", "smoke_failed", "observer standalone smoke failed", error=str(exc), traceback=traceback.format_exc())
        base_dir = config.out_dir / "db_observer"
        artifacts = diagnostics.write(base_dir)
        result = _observer_result(False, f"smoke test failed: {exc}", artifacts, diagnostics)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    result = run_db_observer_validation(diagnostics)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("validation_passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
