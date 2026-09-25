from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from socialtraff_crm import AssertionSigner, ConfigError, ValidationError

SUB = "3f2b8c1e-8f4a-4d0b-9a57-0c7e6f1d2a90"


def decode(token: str, public_pem: bytes) -> dict:
    return jwt.decode(
        token,
        public_pem,
        algorithms=["EdDSA"],
        audience="socialtraff-crm",
        issuer="socialtraff-bosslink",
        options={"require": ["iss", "aud", "sub", "iat", "exp", "jti"]},
    )


def test_assertion_verifies_with_public_key(ed25519_keys: tuple[bytes, bytes]) -> None:
    private_pem, public_pem = ed25519_keys
    signer = AssertionSigner(private_pem.decode(), kid="bosslink-2026-09")
    before = int(time.time())
    token = signer.sign(SUB, ["billing:read", "billing:write", "billing:read"], 42)

    header = jwt.get_unverified_header(token)
    assert header["alg"] == "EdDSA"
    assert header["kid"] == "bosslink-2026-09"

    claims = decode(token, public_pem)
    assert claims["sub"] == SUB
    assert claims["act"] == 42
    assert claims["scope"] == "billing:read billing:write"
    assert claims["exp"] - claims["iat"] == 60
    assert before <= claims["iat"] <= int(time.time())
    assert isinstance(claims["jti"], str) and claims["jti"]


def test_each_assertion_has_unique_jti(ed25519_keys: tuple[bytes, bytes]) -> None:
    private_pem, public_pem = ed25519_keys
    signer = AssertionSigner(private_pem, kid="k1")
    jtis = {decode(signer.sign(SUB, ["ai:read"], 1), public_pem)["jti"] for _ in range(20)}
    assert len(jtis) == 20


def test_custom_issuer_audience_lifetime(ed25519_keys: tuple[bytes, bytes]) -> None:
    private_pem, public_pem = ed25519_keys
    signer = AssertionSigner(
        private_pem, kid="k1", issuer="iss-x", audience="aud-x", lifetime_seconds=120
    )
    claims = jwt.decode(
        signer.sign(SUB, ["referrals:read"], 7),
        public_pem,
        algorithms=["EdDSA"],
        audience="aud-x",
        issuer="iss-x",
    )
    assert claims["exp"] - claims["iat"] == 120


def test_wrong_public_key_fails(ed25519_keys: tuple[bytes, bytes]) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_pem, _ = ed25519_keys
    other_public = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    token = AssertionSigner(private_pem, kid="k1").sign(SUB, ["ai:read"], 1)
    with pytest.raises(jwt.InvalidSignatureError):
        decode(token, other_public)


def test_config_validation(ed25519_keys: tuple[bytes, bytes]) -> None:
    private_pem, _ = ed25519_keys
    ec_pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    with pytest.raises(ConfigError):
        AssertionSigner(ec_pem, kid="k1")
    with pytest.raises(ConfigError):
        AssertionSigner(b"not a key", kid="k1")
    with pytest.raises(ConfigError):
        AssertionSigner(private_pem, kid="")
    with pytest.raises(ConfigError):
        AssertionSigner(private_pem, kid="k1", lifetime_seconds=121)
    with pytest.raises(ConfigError):
        AssertionSigner(private_pem, kid="k1", lifetime_seconds=0)


@pytest.mark.parametrize(
    ("sub", "scopes", "actor"),
    [
        ("", ["ai:read"], 1),
        (SUB, [], 1),
        (SUB, ["billing:read billing:write"], 1),
        (SUB, ["ai:read"], "1"),
        (SUB, ["ai:read"], True),
    ],
)
def test_sign_argument_validation(
    ed25519_keys: tuple[bytes, bytes], sub: str, scopes: list[str], actor: object
) -> None:
    signer = AssertionSigner(ed25519_keys[0], kid="k1")
    with pytest.raises(ValidationError):
        signer.sign(sub, scopes, actor)  # type: ignore[arg-type]
