import re
from typing import Iterable

READ_ONLY_PREFIXES = (
    "select",
    "show",
    "describe",
    "explain",
)

FORBIDDEN = (
    "insert",
    "update",
    "delete",
    "alter",
    "drop",
    "truncate",
    "create",
    "replace",
    "grant",
    "revoke",
)


def sanitize_sql(sql: str, allowed_tables: Iterable[str]) -> tuple[bool, str | None, str | None]:
    """간단한 정적 검사로 읽기 전용/허용 테이블만 사용했는지 확인합니다.

    Returns:
        (ok, normalized_sql, error_message)
    """
    if not sql:
        return False, None, "빈 SQL"

    s = sql.strip().strip(";")
    s_lower = re.sub(r"\s+", " ", s.lower())

    # 단일 문장만 허용
    if ";" in s:
        return False, None, "세미콜론을 포함한 다중 문장은 허용되지 않습니다."

    # 읽기 전용 접두사 검사
    if not any(s_lower.startswith(pfx) for pfx in READ_ONLY_PREFIXES):
        return False, None, "읽기 전용 쿼리만 허용됩니다. (SELECT/SHOW/DESCRIBE/EXPLAIN)"

    # 금지어 포함 검사
    if any(tok in s_lower for tok in FORBIDDEN):
        return False, None, "쓰기/DDL 문은 금지되어 있습니다."

    # 허용된 테이블만 참조했는지 간단 검사 (정확한 파서는 아님)
    table_pattern = re.compile(r"\bfrom\s+([`\w\.]+)|\bjoin\s+([`\w\.]+)")
    print('table_pattern: ', table_pattern)
    for m in table_pattern.finditer(s_lower):
        tbl = (m.group(1) or m.group(2) or "").strip("` ")
        print('table_pattern.finditer(s_lower): ', table_pattern.finditer(s_lower))
        print('m: ', m)
        print('tbl: ', tbl)
        print('allowed_tables: ', allowed_tables)

        if "." in tbl:
            _, tbl = tbl.split(".", 1)
        if tbl and tbl not in set(allowed_tables):
            return False, None, f"허용되지 않은 테이블 참조: {tbl}"

    return True, s, None 