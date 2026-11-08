"""Display-metadata writes kept out of ``hermes_state_messages`` so that file stays under its line cap."""

from __future__ import annotations


def merge_latest_message_display_metadata(db, session_id: str, patch: dict) -> bool:
    """Merge *patch* into the newest active user/assistant/tool row. Content stays unchanged."""
    if not session_id or not isinstance(patch, dict) or not patch:
        return False
    from hermes_state_messages import _SET_DISPLAY_META_SQL

    def _do(conn):
        row = conn.execute(
            "SELECT id, display_metadata FROM messages WHERE session_id = ? AND active = 1 "
            "AND role NOT IN ('session_meta', 'system') ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if row is None:
            return False
        meta = db._decode_display_metadata(row[1]) or {}
        meta.update(patch)
        conn.execute(_SET_DISPLAY_META_SQL, (db._encode_display_metadata(meta), row[0]))
        return True

    return bool(db._execute_write(_do))
