import json
import uuid
from typing import Any, Dict, List, Optional

from psycopg2.extras import Json

from app.db.database import get_cursor


SCHEMA_BY_MODE = {
    "fabeo": "fabeo",
}


def ensure_mode(mode: str) -> str:
    if mode not in SCHEMA_BY_MODE:
        raise ValueError("invalid mode")
    return SCHEMA_BY_MODE[mode]


def get_user(username: str) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, username, full_name, role, password_hash, attributes, is_active FROM public.users WHERE username = %s",
            (username,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def upsert_usk(session_id: str, username: str, usk_ref: str, expires_at_epoch_seconds: int) -> None:
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO public.session_usk (session_id, username, usk_ref, expires_at)
            VALUES (%s, %s, %s, to_timestamp(%s))
            ON CONFLICT (session_id)
            DO UPDATE SET username = EXCLUDED.username, usk_ref = EXCLUDED.usk_ref, expires_at = EXCLUDED.expires_at
            """,
            (session_id, username, usk_ref, expires_at_epoch_seconds),
        )


def get_usk(session_id: str) -> Optional[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            "SELECT session_id, username, usk_ref, expires_at FROM public.session_usk WHERE session_id = %s",
            (session_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def insert_entry(mode: str, payload: Dict[str, Any]) -> str:
    schema = ensure_mode(mode)
    entry_id = str(uuid.uuid4())
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO {schema}.entries (
              entry_id, resource_type, policy_expression, epoch_label, owner_username,
              bidx_name, bidx_cpf, bidx_birthdate, encrypted_payload,
              iv, auth_tag, wrapped_key, wrapped_key_meta, mode_meta
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """.format(schema=schema),
            (
                entry_id,
                payload["resource_type"],
                payload["policy_expression"],
                payload["epoch_label"],
                payload["owner_username"],
                payload.get("bidx_name", ""),
                payload.get("bidx_cpf", ""),
                payload.get("bidx_birthdate", ""),
                payload["encrypted_payload"],
                payload.get("iv", b""),
                payload.get("auth_tag", b""),
                payload.get("wrapped_key", b""),
                Json(payload.get("wrapped_key_meta", {})),
                Json(payload.get("mode_meta", {})),
            ),
        )
    return entry_id


def search_entries(mode: str, bidx_name: str, bidx_cpf: str, bidx_birthdate: str) -> List[Dict[str, Any]]:
    schema = ensure_mode(mode)
    clauses = []
    params = []

    if bidx_name:
        clauses.append("bidx_name = %s")
        params.append(bidx_name)
    if bidx_cpf:
        clauses.append("bidx_cpf = %s")
        params.append(bidx_cpf)
    if bidx_birthdate:
        clauses.append("bidx_birthdate = %s")
        params.append(bidx_birthdate)

    if not clauses:
        return []

    where = " OR ".join(clauses)
    sql = "SELECT entry_id, resource_type, policy_expression, epoch_label, owner_username, mode_meta, created_at FROM {schema}.entries WHERE {where} ORDER BY created_at DESC".format(
        schema=schema,
        where=where,
    )

    with get_cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_entry(mode: str, entry_id: str) -> Optional[Dict[str, Any]]:
    schema = ensure_mode(mode)
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM {schema}.entries WHERE entry_id = %s".format(schema=schema),
            (entry_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def clear_all_entries() -> None:
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM fabeo.entries")
        cur.execute("DELETE FROM public.session_usk")


def upsert_user(username: str, full_name: str, role: str, password_hash: str, attributes: list[str]) -> None:
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO public.users (username, full_name, role, password_hash, attributes)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (username)
            DO UPDATE SET
                full_name = EXCLUDED.full_name,
                role = EXCLUDED.role,
                password_hash = EXCLUDED.password_hash,
                attributes = EXCLUDED.attributes,
                is_active = TRUE
            """,
            (username, full_name, role, password_hash, json.dumps(attributes)),
        )


def get_policy_examples() -> List[Dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            "SELECT policy_name, resource_type, policy_expression, description FROM public.policy_examples ORDER BY policy_name"
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]
