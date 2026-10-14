"""orchestrator/policy.py: Policy events and active policy evaluation."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pyexasol import ExaConnection


def load_thresholds(path: str | Path | None = None) -> dict[str, float]:
    """Load matching thresholds from policy/thresholds.json."""
    if path is None:
        path = Path("policy/thresholds.json")
    else:
        path = Path(path)

    if not path.is_file():
        # Fallback to defaults
        return {
            "ID_NAME_MIN_SIM": 0.60,
            "T1_MAX_DIST": 2.0,
            "T2_LOW": 0.70,
            "T2_HIGH": 0.95,
            "W_NAME": 0.60,
            "W_PHON": 0.15,
            "W_PIN": 0.15,
            "W_STATE": 0.10,
            "JUDGE_MIN_CONF": 0.80,
        }

    return json.loads(path.read_text(encoding="utf-8"))


def policy_in_force(
    conn: ExaConnection,
    business_date: date | str,
    known_at: datetime | str,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Retrieve the policies in force as of business_date known at known_at.

    Returns:
        tuple of (values_dict, event_ids_dict)
    """
    if isinstance(business_date, date):
        bd_str = business_date.isoformat()
    else:
        bd_str = str(business_date)

    if isinstance(known_at, datetime):
        known_str = known_at.strftime("%Y-%m-%d %H:%M:%S")
    else:
        known_str = str(known_at)

    query = """
    SELECT policy_key, value_num, value_text, event_id
    FROM GOV.POLICY_EVENT
    WHERE recorded_at <= {known_at}
      AND effective_from <= {business_date}
      AND {business_date} < effective_to
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY policy_key
        ORDER BY recorded_at DESC, event_id DESC
    ) = 1
    """

    stmt = conn.execute(query, query_params={"business_date": bd_str, "known_at": known_str})
    rows = stmt.fetchall()

    values_dict: dict[str, Any] = {}
    event_ids_dict: dict[str, str] = {}

    for row in rows:
        # row can be tuple or dict depending on fetch mode
        if isinstance(row, dict):
            key = row["policy_key"]
            val_num = row["value_num"]
            val_txt = row["value_text"]
            eid = row["event_id"]
        else:
            key, val_num, val_txt, eid = row[0], row[1], row[2], row[3]

        event_ids_dict[key] = str(eid)
        if val_num is not None:
            # Cast whole floats/Decimals to int if appropriate or float
            f_val = float(val_num)
            values_dict[key] = int(f_val) if f_val.is_integer() else f_val
        else:
            values_dict[key] = val_txt

    return values_dict, event_ids_dict
