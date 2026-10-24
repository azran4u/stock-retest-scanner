"""positions.py supabase-sql: the SQL that mirrors positions.json into Supabase public.positions."""
import json
import re

import positions


def _d():
    return {"positions": [
        {"ticker": "abc", "exchange": "NYSE", "side": "long", "entry_date": "2026-01-02", "qty": 2, "entry_price": 10.5,
         "stop": 9.0, "target": 14.0, "zone": [10.9, 10.2], "status": "open", "note": "it's $pj$ tricky",
         "market": {"date": "2026-01-05", "close": 11.0}},
        {"ticker": "XYZ", "entry_date": "2025-05-01", "qty": 1, "entry_price": 5, "status": "closed", "exit_price": 6,
         "exit_date": "2025-06-01", "realized_pl": 1},
    ]}


def test_rows():
    r = positions.supabase_rows(_d())
    assert [x["id"] for x in r] == ["ABC:2026-01-02", "XYZ:2025-05-01"]
    assert r[0]["zone_bottom"] == 10.2 and r[0]["zone_top"] == 10.9 and r[0]["market"]["close"] == 11.0
    assert r[1]["status"] == "closed" and r[1]["stop"] is None and r[1]["zone_top"] is None and r[1]["exchange"] is None


def test_sql_quotes_and_shape():
    sql = positions.supabase_sql(_d())
    m = re.search(r"jsonb_to_recordset\((\$\w+\$)(.*)\1::jsonb\)", sql, re.S)
    assert m and m.group(1) != "$pj$"            # data contains $pj$ -> another dollar-quote tag
    assert json.loads(m.group(2))[0]["note"] == "it's $pj$ tricky"
    assert "delete from public.positions where id not in (select id from src)" in sql
    assert "on conflict (id) do update set" in sql and "updated_at = now()" in sql


def test_empty_file_clears_table():
    sql = positions.supabase_sql({"positions": []})
    assert "$pj$[]$pj$" in sql and "delete from public.positions" in sql
