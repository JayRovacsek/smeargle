import hashlib

from support.schemas import SCHEMA_DIR

EXPECTED = {
    "oscal_catalog_schema.json": "ab95836e9e8dfeb6fde80007f6cc76fa3192f595d427c751a3f3923c3f474fc2",
    "oscal_profile_schema.json": "7c5ff5a92683b6a80ce6a3474dea04e0ea8680a4ecb60702ffa08ebfc677e6cb",
    "oscal_mapping_schema.json": "ed28b68c8e56cc7d39f0c6076a5d7da3e8100fbe25abf5bb731120bd34f8817e",
}


def test_vendored_schemas_are_hash_pinned():
    for name, digest in EXPECTED.items():
        data = (SCHEMA_DIR / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, name
