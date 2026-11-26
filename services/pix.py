"""Pix "copia e cola" (BR Code estático do Banco Central).

O atleta cola o código no app do banco e o Pix já vem com a chave, o nome de
quem recebe e o valor preenchidos. Não passa por banco nem tem taxa: é só um
texto no padrão EMV com um CRC16 no fim.
"""
import unicodedata
from typing import Optional


def _field(tag: str, value: str) -> str:
    return f"{tag}{len(value):02d}{value}"


def _plain(text: str, limit: int) -> str:
    """Sem acento e em maiúsculas (alguns bancos recusam acento no nome/cidade)."""
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return " ".join(t.upper().split())[:limit]


def _crc16(payload: str) -> str:
    crc = 0xFFFF
    for ch in payload.encode("utf-8"):
        crc ^= ch << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def pix_copia_e_cola(key: str, name: str, city: str, amount: Optional[float] = None, txid: str = "***") -> str:
    key = (key or "").strip()
    if not key:
        raise ValueError("Chave Pix vazia.")
    account = _field("00", "br.gov.bcb.pix") + _field("01", key)
    parts = [
        _field("00", "01"),
        _field("26", account),
        _field("52", "0000"),
        _field("53", "986"),
    ]
    if amount and amount > 0:
        parts.append(_field("54", f"{amount:.2f}"))
    parts += [
        _field("58", "BR"),
        _field("59", _plain(name, 25) or "COACH"),
        _field("60", _plain(city, 15) or "BRASIL"),
        _field("62", _field("05", txid)),
    ]
    payload = "".join(parts) + "6304"
    return payload + _crc16(payload)
