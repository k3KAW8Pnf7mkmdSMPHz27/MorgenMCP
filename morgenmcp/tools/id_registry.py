"""Virtual ID registry for mapping short IDs to real Morgen UUIDs."""

import base64
import hashlib
from typing import Any


class IDNotFoundError(Exception):
    """Raised when a virtual ID cannot be resolved."""

    def __init__(self, virtual_id: str):
        self.virtual_id = virtual_id
        super().__init__(
            f"ID '{virtual_id}' not found. Call list_accounts, list_calendars, or list_events first."
        )


# Bidirectional mappings
_virtual_to_real: dict[str, str] = {}  # "a1b2c3" -> "640a62c9aa5b7e06cf420000"
_real_to_virtual: dict[str, str] = {}  # "640a62c9aa5b7e06cf420000" -> "a1b2c3"


def _generate_virtual_id(real_id: str) -> str:
    """Generate a 7-char Base64url virtual ID from a real ID using MD5 hash."""
    hash_bytes = hashlib.md5(real_id.encode()).digest()[:6]  # 6 bytes = 48 bits
    # Base64url encode (no padding) and take first 7 chars for ~42 bits entropy
    return base64.urlsafe_b64encode(hash_bytes).decode().rstrip("=")[:7]


def register_id(real_id: str) -> str:
    """Register a real ID and return its virtual ID.

    If the real ID is already registered, returns the existing virtual ID.

    Args:
        real_id: The real Morgen UUID.

    Returns:
        The 7-character Base64url virtual ID.
    """
    if real_id in _real_to_virtual:
        return _real_to_virtual[real_id]

    virtual_id = _generate_virtual_id(real_id)
    _virtual_to_real[virtual_id] = real_id
    _real_to_virtual[real_id] = virtual_id

    return virtual_id


def resolve_id(virtual_id: str) -> str:
    """Resolve a virtual ID to its real Morgen UUID.

    Args:
        virtual_id: The 7-character Base64url virtual ID.

    Returns:
        The real Morgen UUID.

    Raises:
        IDNotFoundError: If the virtual ID is not registered.
    """
    if virtual_id not in _virtual_to_real:
        raise IDNotFoundError(virtual_id)
    return _virtual_to_real[virtual_id]


def resolve_ids(virtual_ids: list[str]) -> list[str]:
    """Resolve multiple virtual IDs to real IDs.

    Args:
        virtual_ids: List of virtual IDs.

    Returns:
        List of real Morgen UUIDs.

    Raises:
        IDNotFoundError: If any virtual ID is not registered.
    """
    return [resolve_id(vid) for vid in virtual_ids]


def clear_registry() -> None:
    """Clear all ID mappings. Useful for testing."""
    _virtual_to_real.clear()
    _real_to_virtual.clear()


def virtualize_dict(data: dict[str, Any], id_fields: list[str]) -> dict[str, Any]:
    """Replace real IDs with virtual IDs in a dictionary.

    Registers any real IDs found and replaces them with virtual IDs.

    Args:
        data: Dictionary potentially containing real IDs.
        id_fields: List of field names that contain IDs to virtualize.

    Returns:
        New dictionary with real IDs replaced by virtual IDs.
    """
    result = data.copy()
    for field in id_fields:
        if field in result and result[field] is not None:
            real_id = result[field]
            result[field] = register_id(real_id)
    return result
