from app.services.api_key_service import generate_api_key


class TestGenerateApiKey:
    def test_generates_valid_key(self) -> None:
        raw_key, key_hash, key_prefix = generate_api_key()
        assert raw_key.startswith("sk-parry-")
        assert len(key_hash) == 64  # SHA256 hex
        assert key_prefix == raw_key[:16]

    def test_generates_unique_keys(self) -> None:
        keys = {generate_api_key()[0] for _ in range(10)}
        assert len(keys) == 10

    def test_hash_is_deterministic(self) -> None:
        import hashlib

        raw_key, key_hash, _ = generate_api_key()
        assert hashlib.sha256(raw_key.encode()).hexdigest() == key_hash
