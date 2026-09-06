"""Tests for the ES256 JWT we mint for App Store Connect."""

from __future__ import annotations

import pytest

from custom_components.asc_app_store.jwt import (
    JWT_AUDIENCE,
    JWT_LIFETIME_SECONDS,
    JwtError,
    create_asc_jwt,
    decode_jwt_segment,
)

from .conftest import TEST_ISSUER_ID, TEST_KEY_ID, TEST_PRIVATE_KEY


def test_jwt_shape_is_what_apple_documents() -> None:
    """Header, audience and lifetime must match Apple's token recipe.

    A wrong ``aud`` or an ``exp`` over twenty minutes is a 401 that looks
    like a revoked key. These claims are the whole contract.
    """
    issued_at = 1_700_000_000
    token = create_asc_jwt(
        key_id=TEST_KEY_ID,
        issuer_id=TEST_ISSUER_ID,
        private_key_pem=TEST_PRIVATE_KEY,
        now=issued_at,
    )

    header_seg, payload_seg, signature_seg = token.split(".")
    header = decode_jwt_segment(header_seg)
    payload = decode_jwt_segment(payload_seg)

    assert header == {"alg": "ES256", "kid": TEST_KEY_ID, "typ": "JWT"}
    assert payload["iss"] == TEST_ISSUER_ID
    assert payload["aud"] == JWT_AUDIENCE == "appstoreconnect-v1"
    assert payload["iat"] == issued_at
    lifetime = payload["exp"] - payload["iat"]
    assert 18 * 60 <= lifetime <= 20 * 60
    assert lifetime == JWT_LIFETIME_SECONDS
    # ES256 JOSE signature is r||s, 64 bytes → 86 or 87 chars of b64url.
    assert 80 <= len(signature_seg) <= 90


def test_garbage_pem_is_a_jwt_error() -> None:
    """A mistyped paste must not become a cryptography traceback in the UI."""
    with pytest.raises(JwtError):
        create_asc_jwt(
            key_id=TEST_KEY_ID,
            issuer_id=TEST_ISSUER_ID,
            private_key_pem="not-a-key",
        )


def test_literal_escaped_newlines_are_accepted() -> None:
    """Some password managers paste the .p8 as a single line with ``\\n``."""
    escaped = TEST_PRIVATE_KEY.strip().replace("\n", "\\n")
    token = create_asc_jwt(
        key_id=TEST_KEY_ID,
        issuer_id=TEST_ISSUER_ID,
        private_key_pem=escaped,
    )
    assert token.count(".") == 2
