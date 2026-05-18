"""Tests for persistent virtual ID registry."""

import pytest
from key_value.aio.stores.filetree import FileTreeStore

from morgenmcp.tools.id_registry import (
    IDNotFoundError,
    clear_registry,
    flush_pending,
    load_from_store,
    register_id,
    resolve_id,
    set_store,
)

_COLLECTION = "id_mappings"


@pytest.fixture()
def store(tmp_path):
    """Create a FileTreeStore backed by a temp directory."""
    return FileTreeStore(
        data_directory=tmp_path,
        default_collection=_COLLECTION,
    )


@pytest.fixture(autouse=True)
def _clean_registry():
    """Clear the in-memory registry before and after each test."""
    clear_registry()
    yield
    clear_registry()
    set_store(None)


class TestPersistenceWithFileTreeStore:
    async def test_register_persists_to_store(self, store, tmp_path):
        """register_id writes through to the FileTreeStore."""
        await store.setup()
        set_store(store)

        real_id = "507f1f77bcf86cd799439011"
        virtual_id = register_id(real_id)

        # Let the fire-and-forget task complete
        await flush_pending()

        result = await store.get(virtual_id)
        assert result is not None
        assert result["real_id"] == real_id

    async def test_load_restores_mappings(self, store, tmp_path):
        """load_from_store populates in-memory dicts from persisted data."""
        await store.setup()
        set_store(store)

        real_id = "507f1f77bcf86cd799439011"
        virtual_id = register_id(real_id)
        await flush_pending()

        # Wipe in-memory state
        clear_registry()
        with pytest.raises(IDNotFoundError):
            resolve_id(virtual_id)

        # Load from store
        count = await load_from_store(tmp_path, _COLLECTION)
        assert count == 1
        assert resolve_id(virtual_id) == real_id

    async def test_cross_session_persistence(self, tmp_path):
        """IDs survive a full store teardown and recreation."""
        # Session 1: register an ID
        store1 = FileTreeStore(
            data_directory=tmp_path,
            default_collection=_COLLECTION,
        )
        await store1.setup()
        set_store(store1)

        real_id = "640a62c9aa5b7e06cf420000"
        virtual_id = register_id(real_id)
        await flush_pending()

        # Tear down completely
        set_store(None)
        clear_registry()

        # Session 2: new store on same directory
        store2 = FileTreeStore(
            data_directory=tmp_path,
            default_collection=_COLLECTION,
        )
        await store2.setup()
        set_store(store2)

        count = await load_from_store(tmp_path, _COLLECTION)
        assert count == 1
        assert resolve_id(virtual_id) == real_id

    async def test_duplicate_registration_no_extra_writes(self, store, tmp_path):
        """Registering the same real ID twice doesn't create duplicate entries."""
        await store.setup()
        set_store(store)

        real_id = "507f1f77bcf86cd799439011"
        vid1 = register_id(real_id)
        await flush_pending()

        # Register again — should be a no-op (early return)
        vid2 = register_id(real_id)
        assert vid1 == vid2

        # Only one file in the collection
        col_path = tmp_path / _COLLECTION
        files = list(col_path.glob("*.json"))
        assert len(files) == 1

    async def test_multiple_ids_persist(self, store, tmp_path):
        """Multiple distinct IDs are all persisted and loadable."""
        await store.setup()
        set_store(store)

        ids = {
            "aaaa00000000000000000001": None,
            "bbbb00000000000000000002": None,
            "cccc00000000000000000003": None,
        }
        for real_id in ids:
            ids[real_id] = register_id(real_id)
        await flush_pending()

        clear_registry()
        count = await load_from_store(tmp_path, _COLLECTION)
        assert count == 3

        for real_id, virtual_id in ids.items():
            assert resolve_id(virtual_id) == real_id


class TestWithoutStore:
    def test_register_works_without_store(self):
        """In-memory registration works when no store is configured."""
        set_store(None)
        real_id = "507f1f77bcf86cd799439011"
        virtual_id = register_id(real_id)
        assert resolve_id(virtual_id) == real_id

    async def test_load_returns_zero_without_store(self, tmp_path):
        """load_from_store is a graceful no-op when store is None."""
        set_store(None)
        count = await load_from_store(tmp_path, _COLLECTION)
        assert count == 0

    async def test_load_returns_zero_for_missing_directory(self, store, tmp_path):
        """load_from_store returns 0 when the collection directory doesn't exist."""
        await store.setup()
        set_store(store)
        count = await load_from_store(tmp_path, "nonexistent_collection")
        assert count == 0


class TestVirtualIdGoldenVectors:
    """Lock the virtual-ID hash output and the published HASH_SPEC.

    Any failure here means a change to _generate_virtual_id has
    invalidated every persisted virtual ID on disk. Do not update the
    expected values to make this test pass — bump HASH_SCHEME_VERSION
    and plan a consumer migration first.
    """

    @pytest.mark.parametrize(
        ("real_id", "expected_virtual_id"),
        [
            ("507f1f77bcf86cd799439011", "6bieWxP"),
            ("640a62c9aa5b7e06cf420000", "pNWDB7P"),
            ("aaaa00000000000000000001", "x5n3Afl"),
            (
                "WyI1MDdmMWY3N2JjZjg2Y2Q3OTk0MzkwMTEiLCJ1c2VyQGV4YW1wbGUuY29tIl0",
                "zd-btns",
            ),
            (
                "WyJ1c2VyQGV4YW1wbGUuY29tIiwiZXZ0LXVpZC0xIiwiNTA3ZjFmNzdiY2Y4NmNkNzk5NDM5MDExIl0",
                "ea1iUuG",
            ),
            ("café", "BxF_5KH"),
            ("", "1B2M2Y8"),
        ],
    )
    def test_known_vectors(self, real_id, expected_virtual_id):
        from morgenmcp.tools.id_registry import _generate_virtual_id

        assert _generate_virtual_id(real_id) == expected_virtual_id

    def test_output_charset_is_base64url(self):
        """Output must use only the Base64url alphabet (A-Za-z0-9-_)."""
        import string

        from morgenmcp.tools.id_registry import _generate_virtual_id

        allowed = set(string.ascii_letters + string.digits + "-_")
        for sample in ["507f1f77bcf86cd799439011", "x", "x" * 100, "/+=", "☃"]:
            vid = _generate_virtual_id(sample)
            assert set(vid) <= allowed, (
                f"Virtual ID {vid!r} contains chars outside Base64url"
            )

    def test_output_length_is_fixed(self):
        from morgenmcp.tools.id_registry import (
            _VIRTUAL_ID_LENGTH,
            _generate_virtual_id,
        )

        for sample in ["", "a", "x" * 1000, "café"]:
            assert len(_generate_virtual_id(sample)) == _VIRTUAL_ID_LENGTH

    def test_hash_spec_matches_implementation(self):
        """HASH_SPEC's published test_vectors must all verify against the
        actual function. Guards against the spec drifting from the code."""
        from morgenmcp.tools.id_registry import HASH_SPEC, _generate_virtual_id

        for real_id, expected in HASH_SPEC["test_vectors"].items():
            assert _generate_virtual_id(real_id) == expected

    def test_hash_scheme_version_is_one(self):
        """HASH_SCHEME_VERSION must only be bumped intentionally. If you
        bumped it, you should also be updating the golden vectors above
        because the output has changed."""
        from morgenmcp.tools.id_registry import HASH_SCHEME_VERSION

        assert HASH_SCHEME_VERSION == 1
