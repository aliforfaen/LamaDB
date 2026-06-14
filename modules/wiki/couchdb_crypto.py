"""LiveSync V2 HKDF decryption for Obsidian LiveSync CouchDB data.

Verified against the live obsidiannotes CouchDB database (2026-06-14).
Supports both HKDF (%= prefix, sync-salt) and HKDF ephemeral (%$ prefix,
embedded-salt) encryption variants.
"""
import base64
import json
import logging

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

PBKDF2_ITERATIONS = 310_000
KEY_LENGTH = 32  # AES-256


def decrypt_hkdf(encrypted_b64: str, passphrase: str, pbkdf2_salt: bytes) -> str:
    """Decrypt a %=-prefixed HKDF-encrypted LiveSync value.

    Format: %=<base64> -> decode -> IV[12] + hkdf_salt[32] + AES-GCM ciphertext+tag.
    """
    if not encrypted_b64.startswith("%="):
        raise ValueError(f"Expected %= prefix, got: {encrypted_b64[:4]}...")

    raw = base64.b64decode(encrypted_b64[2:])
    iv = raw[:12]
    hkdf_salt = raw[12:44]
    ciphertext = raw[44:]

    master_key = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_LENGTH,
        salt=pbkdf2_salt,
        iterations=PBKDF2_ITERATIONS,
    ).derive(passphrase.encode("utf-8"))

    chunk_key = HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_LENGTH,
        salt=hkdf_salt,
        info=b"",
    ).derive(master_key)

    plaintext = AESGCM(chunk_key).decrypt(iv, ciphertext, None)
    return plaintext.decode("utf-8")


def decrypt_hkdf_ephemeral(encrypted_b64: str, passphrase: str) -> str:
    """Decrypt a %$-prefixed HKDF-ephemeral LiveSync value.

    Format: %$<base64> -> decode -> pbkdf2_salt[32] + IV[12] + hkdf_salt[32] +
    AES-GCM ciphertext+tag.
    """
    if not encrypted_b64.startswith("%$"):
        raise ValueError(f"Expected %$ prefix, got: {encrypted_b64[:4]}...")

    raw = base64.b64decode(encrypted_b64[2:])
    pbkdf2_salt = raw[:32]
    iv = raw[32:44]
    hkdf_salt = raw[44:76]
    ciphertext = raw[76:]

    master_key = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_LENGTH,
        salt=pbkdf2_salt,
        iterations=PBKDF2_ITERATIONS,
    ).derive(passphrase.encode("utf-8"))

    chunk_key = HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_LENGTH,
        salt=hkdf_salt,
        info=b"",
    ).derive(master_key)

    plaintext = AESGCM(chunk_key).decrypt(iv, ciphertext, None)
    return plaintext.decode("utf-8")


def decrypt_meta(path_field: str, passphrase: str, pbkdf2_salt: bytes) -> dict:
    """Decrypt a LiveSync path metadata field (starts with /\\:)."""
    if not path_field.startswith("/\\:"):
        raise ValueError(f"Expected /\\: prefix, got: {path_field[:10]}...")

    encrypted = path_field[3:]  # strip /\:

    if encrypted.startswith("%="):
        return json.loads(decrypt_hkdf(encrypted, passphrase, pbkdf2_salt))
    elif encrypted.startswith("%$"):
        return json.loads(decrypt_hkdf_ephemeral(encrypted, passphrase))
    else:
        raise ValueError(f"Unknown encryption prefix in: {encrypted[:10]}...")


def decrypt_chunk(data_field: str, passphrase: str, pbkdf2_salt: bytes) -> bytes:
    """Decrypt a LiveSync chunk data field (%= or %$ prefix)."""
    if data_field.startswith("%="):
        return decrypt_hkdf(data_field, passphrase, pbkdf2_salt).encode("utf-8")
    elif data_field.startswith("%$"):
        return decrypt_hkdf_ephemeral(data_field, passphrase).encode("utf-8")
    else:
        return data_field.encode("utf-8")
