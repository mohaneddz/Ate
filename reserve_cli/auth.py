"""Read local account details without echoing or copying the source file."""
import json
from pathlib import Path


_KEYS = {
    "student": "student", "studentid": "student", "studentnumber": "student",
    "matricule": "student", "username": "student",
    "password": "password", "pass": "password", "pwd": "password",
    "dorm": "dorm_id", "dormid": "dorm_id", "residenceid": "dorm_id",
    "main": "main_id", "mainid": "main_id", "restaurantid": "main_id",
    "days": "days", "bookingdays": "days", "horizon": "days",
}


def _canonical(value: str) -> str | None:
    normalized = "".join(ch for ch in value.lower() if ch.isalnum())
    return _KEYS.get(normalized)


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'", "`"):
        return value[1:-1]
    return value


def load_credentials(path: Path) -> dict[str, str]:
    """Accept dotenv/YAML-style lines, Markdown lists/tables, or a JSON object."""
    try:
        if path.stat().st_size > 65536:
            raise ValueError("Credential file is too large; use a small account file.")
        content = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise ValueError("Credential file was not found.") from exc
    except UnicodeError as exc:
        raise ValueError("Could not read the credential file as UTF-8 text.") from exc
    except OSError as exc:
        raise ValueError("Could not read the credential file.") from exc

    values: dict[str, str] = {}

    def add(key: str, value: object) -> None:
        field = _canonical(key)
        if field is None:
            return
        if not isinstance(value, (str, int)):
            raise ValueError(f"The {field} field must be text.")
        cleaned = _unquote(str(value))
        if field in values and values[field] != cleaned:
            raise ValueError(f"The credential file has conflicting {field} fields.")
        values[field] = cleaned

    if content.lstrip().startswith("{"):
        try:
            document = json.loads(content)
        except ValueError as exc:
            raise ValueError("Credential JSON could not be parsed.") from exc
        if not isinstance(document, dict):
            raise ValueError("Credential JSON must be an object.")
        for key, value in document.items():
            add(str(key), value)
    else:
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith(("#", ";", "<!--")):
                continue
            if line.startswith("|") and line.endswith("|"):
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                if len(cells) == 2:
                    add(cells[0].strip("`* "), cells[1])
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            line = line.removeprefix("- ").removeprefix("* ")
            separators = [(line.index(mark), mark) for mark in ("=", ":") if mark in line]
            if separators:
                index, separator = min(separators)
                key, value = line[:index], line[index + 1:]
                add(key.strip("`* "), value)

    if not values.get("student") or not values.get("password"):
        raise ValueError("Credential file needs student and password fields.")
    values["student"] = values["student"].strip()
    if not values["student"] or "\n" in values["password"] or "\r" in values["password"]:
        raise ValueError("Credential file has invalid student or password fields.")
    return values
