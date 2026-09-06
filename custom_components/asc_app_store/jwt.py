"""ES256 JWT for App Store Connect, using Home Assistant's bundled cryptography.

PyJWT is deliberately not a dependency. Home Assistant already ships
``cryptography``, which is what Apple's ES256 signature actually needs, and
adding PyJWT would force a ``requirements`` entry in the manifest for no gain.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

JWT_AUDIENCE = "appstoreconnect-v1"
JWT_ALGORITHM = "ES256"
# Apple rejects tokens whose exp is more than 20 minutes after iat. Thirty
# seconds of headroom covers clock skew without shrinking the useful life.
JWT_LIFETIME_SECONDS = 20 * 60 - 30


class JwtError(Exception):
    """The private key could not be used to sign a token."""


def _b64url(data: bytes) -> str:
    """Return URL-safe base64 without padding, as JOSE requires."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_json(payload: dict[str, Any]) -> str:
    """Encode a JWT segment with stable separators so tests can assert the shape."""
    return _b64url(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode()
    )


def decode_jwt_segment(segment: str) -> dict[str, Any]:
    """Decode one JWT header or payload segment.

    Used by tests (and diagnostics) so we can inspect claims without pulling
    in PyJWT just to read them back.
    """
    padding = "=" * (-len(segment) % 4)
    raw = base64.urlsafe_b64decode(segment + padding)
    body = json.loads(raw.decode())
    if not isinstance(body, dict):
        raise JwtError("JWT segment was not a JSON object")
    return body


def normalise_pem(raw: str) -> str:
    """Accept a .p8 pasted with Windows newlines or literal ``\\n`` escapes."""
    text = raw.strip().replace("\r\n", "\n")
    if "BEGIN " in text and "\n" not in text:
        text = text.replace("\\n", "\n")
    return text


def create_asc_jwt(
    *,
    key_id: str,
    issuer_id: str,
    private_key_pem: str,
    now: int | None = None,
) -> str:
    """Return a Bearer token Apple will accept for about twenty minutes."""
    issued_at = int(time.time() if now is None else now)
    header = {"alg": JWT_ALGORITHM, "kid": key_id, "typ": "JWT"}
    claims = {
        "iss": issuer_id,
        "iat": issued_at,
        "exp": issued_at + JWT_LIFETIME_SECONDS,
        "aud": JWT_AUDIENCE,
    }
    signing_input = f"{_b64url_json(header)}.{_b64url_json(claims)}"

    try:
        key = serialization.load_pem_private_key(
            normalise_pem(private_key_pem).encode(),
            password=None,
        )
    except ValueError as err:
        raise JwtError("Private key is not a valid PEM") from err

    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise JwtError("Private key must be an EC key for ES256")

    der_signature = key.sign(
        signing_input.encode("ascii"),
        ec.ECDSA(hashes.SHA256()),
    )
    r_int, s_int = decode_dss_signature(der_signature)
    jose_signature = r_int.to_bytes(32, "big") + s_int.to_bytes(32, "big")
    return f"{signing_input}.{_b64url(jose_signature)}"
