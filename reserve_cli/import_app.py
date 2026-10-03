"""Import the request-signing constant locally from the user's original APK."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
from zipfile import ZipFile


def import_signing_key(path: Path) -> tuple[str, str]:
    try:
        from hermes_dec.parsers.hbc_file_parser import HBCReader
        from hermes_dec.parsers.hbc_bytecode_parser import parse_hbc_bytecode
        from hermes_dec.parsers.hbc_opcodes.def_classes import OperandMeaning
    except ImportError:
        raise ValueError('Install the import dependency first: python -m pip install ".[import]"') from None
    raw = path.read_bytes()
    with ZipFile(BytesIO(raw)) as outer:
        if "assets/index.android.bundle" in outer.namelist():
            bundle = outer.read("assets/index.android.bundle")
        elif "app.progres.webetu.apk" in outer.namelist():
            with ZipFile(BytesIO(outer.read("app.progres.webetu.apk"))) as apk:
                bundle = apk.read("assets/index.android.bundle")
        else:
            raise ValueError("Expected the original Webetu APK or XAPK.")
    reader = HBCReader()
    with BytesIO(bundle) as source:
        reader.read_whole_file(source)
        if reader.header.version != 96:
            raise ValueError("This importer supports the bytecode used by Webetu 2.5.0 only.")
        candidates = set()
        for header in reader.function_headers:
            instructions = list(parse_hbc_bytecode(header, reader))
            references = []
            for instruction in instructions:
                values = [reader.strings[getattr(instruction, f"arg{index + 1}")]
                          for index, operand in enumerate(instruction.inst.operands)
                          if operand.operand_meaning == OperandMeaning.string_id]
                references.append((instruction.inst.name, values))
            strings = {value for _, values in references for value in values}
            if not {"HmacSHA256", "X-Timestamp", "X-Nonce", "X-Signature"} <= strings:
                continue
            for index, (_, values) in enumerate(references[:-1]):
                next_name, next_values = references[index + 1]
                if "HmacSHA256" in values and next_name.startswith("LoadConstString"):
                    candidates.update(v for v in next_values if re.fullmatch(r"[A-Za-z0-9]{32}", v))
        if len(candidates) != 1:
            raise ValueError("Could not uniquely recover the signing constant; the app may have changed.")
        return candidates.pop(), sha256(raw).hexdigest()
