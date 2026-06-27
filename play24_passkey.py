"""
Software'owy autentykator WebAuthn/FIDO2 dla klienta Play24.

Odtwarza dokładnie to, co robi apka Play24 (play.fido2.*), ale klucz prywatny trzymamy
w pliku PEM zamiast w Android Keystore. Format zweryfikowany z dekompilatu:
  - attestation = "none"  (RegisterStartRequest.attestation, hardcoded)
  - attestationObject = CBOR { "authData": <bytes>, "fmt": "none", "attStmt": {} }
  - authData = rpIdHash(32) || flags(1) || signCount(4 BE) || attestedCredentialData
  - attestedCredentialData = AAGUID(16×0) || credIdLen(2 BE) || credId || COSE_pubkey
  - COSE_pubkey (ES256/EC2/P-256) = { 1:2, 3:-7, -1:1, -2:x(32), -3:y(32) }
  - clientDataJSON = { "type": "...", "challenge": <echo>, "origin": <rpId> }
  - klucz: secp256r1, podpis SHA256withECDSA (ES256 = alg -7)
  - base64 pól = STANDARD (Android Base64.NO_WRAP, z paddingiem, bez url-safe)
"""
import base64
import hashlib
import json
import os
import struct

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils as asym_utils


# ----------------------------------------------------------------- mini-CBOR (encode)
def _cbor_head(major, n):
    if n < 24:
        return bytes([(major << 5) | n])
    if n < 256:
        return bytes([(major << 5) | 24, n])
    if n < 65536:
        return bytes([(major << 5) | 25]) + struct.pack(">H", n)
    if n < 2**32:
        return bytes([(major << 5) | 26]) + struct.pack(">I", n)
    return bytes([(major << 5) | 27]) + struct.pack(">Q", n)


def cbor(v):
    if isinstance(v, bool):
        return bytes([0xF5 if v else 0xF4])
    if isinstance(v, int):
        return _cbor_head(0, v) if v >= 0 else _cbor_head(1, -1 - v)
    if isinstance(v, bytes):
        return _cbor_head(2, len(v)) + v
    if isinstance(v, str):
        b = v.encode()
        return _cbor_head(3, len(b)) + b
    if isinstance(v, list):
        return _cbor_head(4, len(v)) + b"".join(cbor(x) for x in v)
    if isinstance(v, dict):
        # zachowujemy kolejność wstawiania (jak LinkedHashMap w apce)
        out = _cbor_head(5, len(v))
        for k, val in v.items():
            out += cbor(k) + cbor(val)
        return out
    raise TypeError(f"CBOR: nieobsługiwany typ {type(v)}")


# ----------------------------------------------------------------- base64 (standard, jak Android NO_WRAP)
def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def b64d(s: str) -> bytes:
    s = s.strip()
    pad = (-len(s)) % 4
    # toleruj zarówno standard jak i url-safe wejście
    s2 = s.replace("-", "+").replace("_", "/") + ("=" * pad)
    return base64.b64decode(s2)


# ----------------------------------------------------------------- klucz / przechowywanie
class Passkey:
    """Para kluczy EC P-256 + credentialId + licznik podpisów, trzymane w pliku."""

    def __init__(self, private_key, cred_id: bytes, sign_count: int = 0):
        self.private_key = private_key
        self.cred_id = cred_id
        self.sign_count = sign_count

    @classmethod
    def create(cls):
        return cls(ec.generate_private_key(ec.SECP256R1()), os.urandom(32), 0)

    def save(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {
            "private_key": self.private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode(),
            "cred_id": b64(self.cred_id),
            "sign_count": self.sign_count,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        os.chmod(path, 0o600)

    @classmethod
    def load(cls, path):
        with open(path) as f:
            d = json.load(f)
        pk = serialization.load_pem_private_key(d["private_key"].encode(), password=None)
        return cls(pk, b64d(d["cred_id"]), int(d.get("sign_count", 0)))

    # --- COSE public key (ES256 / EC2 / P-256) ---
    def cose_key(self) -> bytes:
        nums = self.private_key.public_key().public_numbers()
        x = nums.x.to_bytes(32, "big")
        y = nums.y.to_bytes(32, "big")
        return cbor({1: 2, 3: -7, -1: 1, -2: x, -3: y})

    def sign(self, data: bytes) -> bytes:
        # ECDSA-SHA256, podpis w formacie DER (jak Java SHA256withECDSA / WebAuthn)
        return self.private_key.sign(data, ec.ECDSA(hashes.SHA256()))


# ----------------------------------------------------------------- WebAuthn operacje
def _client_data(typ: str, challenge: str, origin: str) -> bytes:
    # kolejność pól jak w play.fido2.client.model.a: type, challenge, origin
    return json.dumps(
        {"type": typ, "challenge": challenge, "origin": origin},
        separators=(",", ":"),
    ).encode()


def _auth_data(rp_id: str, flags: int, sign_count: int, attested: bytes = b"") -> bytes:
    rp_id_hash = hashlib.sha256(rp_id.encode()).digest()
    return rp_id_hash + bytes([flags]) + struct.pack(">I", sign_count) + attested


# flagi authenticatorData: UP=0x01, UV=0x04, AT=0x40
FLAGS_REGISTER = 0x45  # UP | UV | AT
FLAGS_ASSERT = 0x05    # UP | UV


def make_credential(options: dict, rp_id: str, origin: str) -> tuple[Passkey, dict]:
    """Rejestracja: z RegisterOptions buduje nowy passkey + RegisterServerPublicKeyCredential."""
    pk = Passkey.create()
    challenge = options["challenge"]
    client_data = _client_data("webauthn.create", challenge, origin)

    attested = (
        b"\x00" * 16                                   # AAGUID
        + struct.pack(">H", len(pk.cred_id))           # credIdLen
        + pk.cred_id                                    # credId
        + pk.cose_key()                                 # COSE pubkey
    )
    auth_data = _auth_data(rp_id, FLAGS_REGISTER, pk.sign_count, attested)
    attestation_object = cbor({"authData": auth_data, "fmt": "none", "attStmt": {}})

    cid_b64 = b64(pk.cred_id)
    credential = {
        "nonce": options.get("nonce"),
        "id": cid_b64,
        "rawId": cid_b64,
        "response": {
            "clientDataJSON": b64(client_data),
            "attestationObject": b64(attestation_object),
        },
        "type": "public-key",
    }
    return pk, credential


def get_assertion(options: dict, pk: Passkey, rp_id: str, origin: str) -> dict:
    """Logowanie: z AuthenticateOptions buduje podpisaną asercję."""
    challenge = options["challenge"]
    client_data = _client_data("webauthn.get", challenge, origin)
    pk.sign_count += 1
    auth_data = _auth_data(rp_id, FLAGS_ASSERT, pk.sign_count)
    signature = pk.sign(auth_data + hashlib.sha256(client_data).digest())

    cid_b64 = b64(pk.cred_id)
    return {
        "nonce": options.get("nonce"),
        "id": cid_b64,
        "rawId": cid_b64,
        "response": {
            "clientDataJSON": b64(client_data),
            "authenticatorData": b64(auth_data),
            "signature": b64(signature),
            "userHandle": None,
        },
        "type": "public-key",
    }
