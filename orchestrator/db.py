"""orchestrator/db.py: Database connection factory and SQL execution utilities for Exasol.

Provenance:
The Exasol Nano version patch and connection parameters are adapted from
`hackathons/Circe/exasol/connection.py`. Strips `-nano.N` suffixes so pyexasol
can parse valid PEP 440 versions and correctly engage TLS public-key pinning.
Never passes `schema=` at connect.
"""

from __future__ import annotations

import os
import re
import warnings
from pathlib import Path
from typing import Literal

try:
    import pyexasol
    _HAS_PYEXASOL = True
except ImportError:
    _HAS_PYEXASOL = False

if _HAS_PYEXASOL:
    # Circe patch: Exasol Nano reports releaseVersion like '2026.2.0-nano.3'.
    # pyexasol's exasol_db_version property parses this with packaging.version.Version,
    # raising InvalidVersion on the '-nano.3' suffix. We strip the suffix to leave '2026.2.0'.
    from packaging.version import InvalidVersion, Version

    _original_exasol_db_version = pyexasol.ExaConnection.exasol_db_version.fget

    def _safe_exasol_db_version(self):
        try:
            return _original_exasol_db_version(self)
        except InvalidVersion:
            release_version = self.login_info.get("releaseVersion", "")
            match = re.match(r"^\d+(\.\d+)*", release_version)
            if match:
                try:
                    return Version(match.group(0))
                except InvalidVersion:
                    pass
            return None

    pyexasol.ExaConnection.exasol_db_version = property(_safe_exasol_db_version)


REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SYS_CRED_PATH = Path.home() / ".exasol-starter-kit" / "credentials" / "nano_sys_password"
_DEFAULT_DSN = "127.0.0.1:8563"

Role = Literal["sys", "loader", "pipeline", "approver", "reader", "eval"]


def load_env_file(dotenv_path: str | Path | None = None) -> None:
    """Load variables from .env file into os.environ if not already set."""
    if dotenv_path is None:
        dotenv_path = REPO_ROOT / ".env"
    else:
        dotenv_path = Path(dotenv_path)
        if not dotenv_path.is_absolute() and not dotenv_path.is_file():
            alt = REPO_ROOT / dotenv_path
            if alt.is_file():
                dotenv_path = alt

    if not dotenv_path.is_file():
        return

    try:
        content = dotenv_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception:
        pass


def get_sys_password() -> str:
    """Resolve Exasol sys password from environment or credential file."""
    load_env_file()
    env_pass = os.environ.get("EXASOL_PASSWORD", "").strip()
    if env_pass and not env_pass.startswith("change_me_"):
        return env_pass

    cred_file_env = os.environ.get("EXASOL_SYS_PASSWORD_FILE")
    cred_path = Path(cred_file_env).expanduser() if cred_file_env else _DEFAULT_SYS_CRED_PATH

    if cred_path.is_file():
        return cred_path.read_text(encoding="utf-8").strip()

    raise FileNotFoundError(
        f"Exasol sys password not found. Looked in EXASOL_PASSWORD env and file {cred_path}."
    )


def get_role_password(role: Role) -> str:
    """Resolve password for a specific Talos database role."""
    load_env_file()
    if role == "sys":
        return get_sys_password()

    env_var = f"TALOS_{role.upper()}_PASSWORD"
    val = os.environ.get(env_var, "").strip()
    if val and not val.startswith("change_me_"):
        return val

    raise ValueError(
        f"Password for role '{role}' is not configured in {env_var}."
    )


def is_exasol_available() -> bool:
    """Check if pyexasol is installed and Exasol credentials are available."""
    if not _HAS_PYEXASOL:
        return False
    load_env_file()
    env_pass = os.environ.get("EXASOL_PASSWORD", "").strip()
    if env_pass and not env_pass.startswith("change_me_"):
        return True
    cred_file_env = os.environ.get("EXASOL_SYS_PASSWORD_FILE")
    cred_path = Path(cred_file_env).expanduser() if cred_file_env else _DEFAULT_SYS_CRED_PATH
    return cred_path.is_file()


def connect(
    role: Role = "sys",
    autocommit: bool = True,
) -> pyexasol.ExaConnection:
    """Connect to Exasol Nano using role credentials and Circe TLS patches.

    Enables fetch_dict=True and never passes schema= at connect.
    """
    if not _HAS_PYEXASOL:
        raise ImportError("pyexasol is not installed. Install with: pip install pyexasol")

    load_env_file()
    dsn = os.environ.get("EXASOL_DSN", _DEFAULT_DSN)

    if role == "sys":
        user = os.environ.get("EXASOL_USER", "sys")
        password = get_sys_password()
    else:
        user = f"TALOS_{role.upper()}"
        password = get_role_password(role)

    is_localhost = any(dsn.startswith(prefix) for prefix in ("127.0.0.1", "localhost", "::1"))
    insecure_tls = is_localhost or os.environ.get("EXASOL_INSECURE_TLS", "0") in ("1", "true", "True")
    if not is_localhost and insecure_tls:
        warnings.warn(
            f"Connecting to remote host {dsn} with TLS certificate validation disabled.",
            stacklevel=2,
        )
    sslopt = {"cert_reqs": 0} if insecure_tls else None

    try:
        conn = pyexasol.connect(
            dsn=dsn,
            user=user,
            password=password,
            # DO NOT pass schema= here; all names in Talos are fully qualified.
            encryption=True,
            websocket_sslopt=sslopt,
            autocommit=autocommit,
            fetch_dict=True,
            lower_ident=True,
        )
        return conn
    except Exception as e:
        raise ConnectionError(f"Failed to connect to Exasol at {dsn} as user {user}: {e}") from e


def _is_comments_only(stmt: str) -> bool:
    """Check if statement contains only whitespace and SQL comments."""
    s = re.sub(r"--[^\n]*", "", stmt)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.DOTALL)
    return len(s.strip()) == 0


def split_sql(text: str) -> list[str]:
    """State-machine splitter that splits SQL on ';' outside quotes, comments, and UDF blocks.

    Rules:
    - Single quotes ('...') with '' escape
    - Double quotes (\"...\") with \"\" escape
    - Line comments (-- to newline)
    - Block comments (/* ... */)
    - Exasol UDF/script blocks (--/ ... /) where / is alone on a line (outside quotes/comments)
    """
    statements: list[str] = []
    current: list[str] = []
    i = 0
    n = len(text)

    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    in_udf = False

    while i < n:
        c = text[i]
        next_c = text[i + 1] if i + 1 < n else ""

        if in_single:
            current.append(c)
            if c == "'":
                if next_c == "'":
                    current.append(next_c)
                    i += 1
                else:
                    in_single = False
        elif in_double:
            current.append(c)
            if c == '"':
                if next_c == '"':
                    current.append(next_c)
                    i += 1
                else:
                    in_double = False
        elif in_line_comment:
            current.append(c)
            if c == "\n":
                in_line_comment = False
        elif in_block_comment:
            current.append(c)
            if c == "*" and next_c == "/":
                current.append(next_c)
                i += 1
                in_block_comment = False
        elif in_udf:
            current.append(c)
            # End of UDF is a slash '/' at the start of a line (or line with only whitespace before it)
            if c == "/":
                pos = len(current) - 2
                is_line_start = True
                while pos >= 0:
                    prev_char = current[pos]
                    if prev_char == "\n":
                        break
                    if prev_char not in (" ", "\t", "\r"):
                        is_line_start = False
                        break
                    pos -= 1

                if is_line_start:
                    j = i + 1
                    while j < n and text[j] in (" ", "\t", "\r"):
                        j += 1
                    if j < n and text[j] == ";":
                        current.append(";")
                        i = j
                    elif j < n and text[j] == "\n":
                        i = j
                    in_udf = False
                    stmt = "".join(current).strip()
                    if stmt and not _is_comments_only(stmt):
                        statements.append(stmt)
                    current = []
        else:
            # Check for starting --/ (UDF script block)
            if c == "-" and next_c == "-" and (i + 2 < n and text[i + 2] == "/"):
                in_udf = True
                current.extend(["-", "-", "/"])
                i += 2
            elif c == "-" and next_c == "-":
                in_line_comment = True
                current.extend(["-", "-"])
                i += 1
            elif c == "/" and next_c == "*":
                in_block_comment = True
                current.extend(["/", "*"])
                i += 1
            elif c == "'":
                in_single = True
                current.append(c)
            elif c == '"':
                in_double = True
                current.append(c)
            elif c == ";":
                stmt = "".join(current).strip()
                if stmt and not _is_comments_only(stmt):
                    statements.append(stmt)
                current = []
            else:
                current.append(c)

        i += 1

    stmt = "".join(current).strip()
    if stmt and not _is_comments_only(stmt):
        statements.append(stmt)

    return statements


def run_sql_file(conn: pyexasol.ExaConnection, path: str | Path, **params) -> list[int]:
    """Execute SQL file with pyexasol query_params and return statement row counts.

    Always passes a dictionary (even if empty) so pyexasol unescapes doubled braces {{...}}.
    """
    path = Path(path)
    if not path.is_file():
        alt = REPO_ROOT / path
        if alt.is_file():
            path = alt
        else:
            raise FileNotFoundError(f"Required SQL file not found at {path}")

    text = path.read_text(encoding="utf-8")
    statements = split_sql(text)
    row_counts: list[int] = []

    # Always pass dictionary to trigger formatting and unescape doubled braces {{5}} -> {5}
    query_params = dict(params)

    for stmt_sql in statements:
        if not stmt_sql.strip():
            continue
        stmt = conn.execute(stmt_sql, query_params=query_params)
        row_counts.append(stmt.rowcount())

    return row_counts
