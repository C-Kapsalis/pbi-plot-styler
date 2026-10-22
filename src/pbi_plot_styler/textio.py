"""Text files as Windows tools save them.

Power BI Desktop, editors and git on Windows leave project files with or
without a UTF-8 byte-order mark and with CRLF or LF line endings. Every
reader in this package goes through :func:`read_text` (or the JSON / TOML
helpers built on it), so all four variants parse the same. Every writer
that changes an existing file goes through :class:`Layout`, so the file
keeps the conventions it already had.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib

BOM = b"\xef\xbb\xbf"


def decode(raw: bytes) -> str:
    """UTF-8 text with any leading byte-order mark dropped."""
    return raw.decode("utf-8-sig")


def read_text(path: Path) -> str:
    """The text of ``path``; a BOM is dropped, line endings are kept."""
    return decode(Path(path).read_bytes())


def load_json(path: Path) -> Any:
    """Parse a JSON file saved with or without a BOM."""
    return json.loads(read_text(path))


def load_toml(path: Path) -> dict[str, Any]:
    """Parse a TOML file saved with or without a BOM, CRLF or LF."""
    return tomllib.loads(read_text(path).replace("\r\n", "\n"))


@dataclass(frozen=True)
class Layout:
    """The byte conventions of one text file."""

    bom: bool = False
    crlf: bool = False
    final_newline: bool = True

    @classmethod
    def of(cls, raw: bytes) -> Layout:
        text = decode(raw)
        return cls(raw.startswith(BOM), "\r\n" in text, text.endswith("\n"))

    @classmethod
    def of_file(cls, path: Path) -> Layout:
        """The layout of ``path``, or the default (LF, no BOM) when absent."""
        try:
            return cls.of(Path(path).read_bytes())
        except FileNotFoundError:
            return cls()

    def encode(self, text: str) -> bytes:
        """``text`` (any line endings) as bytes in this layout."""
        body = text.replace("\r\n", "\n").rstrip("\n")
        if self.final_newline:
            body += "\n"
        if self.crlf:
            body = body.replace("\n", "\r\n")
        return (BOM if self.bom else b"") + body.encode("utf-8")


def dump_json(data: Any) -> str:
    """The 2-space JSON text every writer in this package produces."""
    return json.dumps(data, indent=2, ensure_ascii=False)
