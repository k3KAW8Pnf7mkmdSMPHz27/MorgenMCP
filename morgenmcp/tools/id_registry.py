"""Virtual ID registry for mapping short IDs to real Morgen UUIDs."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from key_value.aio.stores.filetree import FileTreeStore

logger = logging.getLogger(__name__)


class IDNotFoundError(Exception):
    """Raised when a virtual ID cannot be resolved."""

    def __init__(self, virtual_id: str):
        self.virtual_id = virtual_id
        super().__init__(
            f"ID '{virtual_id}' not found. Call list_accounts, list_calendars, list_events, or list_tasks first."
        )


# Bidirectional mappings
_virtual_to_real: dict[str, str] = {}  # "a1b2c3" -> "640a62c9aa5b7e06cf420000"
_real_to_virtual: dict[str, str] = {}  # "640a62c9aa5b7e06cf420000" -> "a1b2c3"

# Persistent store (set during server lifespan, None in tests)
_store: FileTreeStore | None = None
_pending_tasks: set[asyncio.Task[None]] = set()


def set_store(store: FileTreeStore | None) -> None:
    """Set the persistent store for write-through persistence."""
    global _store
    _store = store


def _generate_virtual_id(real_id: str) -> str:
    """Generate a 7-char Base64url virtual ID from a real ID using MD5 hash."""
    hash_bytes = hashlib.md5(real_id.encode()).digest()[:6]  # 6 bytes = 48 bits
    # Base64url encode (no padding) and take first 7 chars for ~42 bits entropy
    return base64.urlsafe_b64encode(hash_bytes).decode().rstrip("=")[:7]


def _schedule_persist(virtual_id: str, real_id: str) -> None:
    """Fire-and-forget async write to the persistent store."""
    if _store is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_persist(virtual_id, real_id))
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


async def _persist(virtual_id: str, real_id: str) -> None:
    """Write a single mapping to the persistent store."""
    try:
        await _store.put(virtual_id, {"real_id": real_id})  # type: ignore[union-attr]
    except Exception:
        logger.warning("Failed to persist ID mapping %s", virtual_id, exc_info=True)


async def flush_pending() -> None:
    """Await all in-flight persist tasks. Used by tests."""
    if _pending_tasks:
        await asyncio.gather(*_pending_tasks, return_exceptions=True)


async def load_from_store(data_dir: Path, collection: str) -> int:
    """Load all persisted mappings into memory.

    Enumerates the store's collection directory and bulk-loads all entries.

    Returns:
        Number of mappings loaded.
    """
    if _store is None:
        return 0

    col_path = data_dir / collection
    if not col_path.is_dir():
        return 0

    keys = [f.stem for f in col_path.glob("*.json")]
    if not keys:
        return 0

    values = await _store.get_many(keys)
    count = 0
    for key, value in zip(keys, values, strict=True):
        if value is not None and "real_id" in value:
            real_id = value["real_id"]
            _virtual_to_real[key] = real_id
            _real_to_virtual[real_id] = key
            count += 1

    return count


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

    _schedule_persist(virtual_id, real_id)

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
