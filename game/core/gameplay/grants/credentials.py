"""兑换码摘要和外部小游戏回执签名。"""

from __future__ import annotations

from hashlib import sha256
import hmac
import json
import re
import unicodedata

from .models import GrantProof


_CODE_PATTERN = re.compile(r"^[A-Z0-9]{6,64}$")


def normalize_grant_code(value: object) -> str:
    """统一人工输入差异；公开活动码允许从六位开始。"""

    text = unicodedata.normalize("NFKC", str(value or "")).upper()
    text = "".join(character for character in text if not character.isspace() and character != "-")
    if not _CODE_PATTERN.fullmatch(text):
        raise ValueError("兑换码必须是 6 到 64 位英文大写字母或数字")
    return text


def grant_code_digest(secret: bytes | str, campaign_id: str, code: object) -> str:
    """使用服务端密钥生成不可反查的兑换码摘要。"""

    key = _secret_bytes(secret)
    campaign = str(campaign_id or "").strip()
    if not campaign:
        raise ValueError("兑换码缺少 campaign_id")
    payload = f"grant-code.v1\0{campaign}\0{normalize_grant_code(code)}".encode("utf-8")
    return hmac.new(key, payload, sha256).hexdigest()


def sign_grant_proof(secret: bytes | str, proof: GrantProof) -> str:
    """签发绑定账号、场次摘要、nonce 和期限的外部回执。"""

    return hmac.new(_secret_bytes(secret), _proof_payload(proof), sha256).hexdigest()


def verify_grant_proof(secret: bytes | str, proof: GrantProof, signature: object) -> bool:
    candidate = str(signature or "").strip().lower()
    return len(candidate) == 64 and hmac.compare_digest(
        sign_grant_proof(secret, proof),
        candidate,
    )


def grant_proof_digest(proof: GrantProof) -> str:
    """得到不含密钥的稳定回执内容摘要，用于数据库唯一约束。"""

    return sha256(_proof_payload(proof)).hexdigest()


def _proof_payload(proof: GrantProof) -> bytes:
    payload = {
        "account_id": proof.account_id,
        "campaign_id": proof.campaign_id,
        "expires_at": proof.expires_at.isoformat(),
        "issued_at": proof.issued_at.isoformat(),
        "issuer_id": proof.issuer_id,
        "nonce": proof.nonce,
        "payload_digest": proof.payload_digest,
        "receipt_id": proof.receipt_id,
        "version": "grant-proof.v1",
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _secret_bytes(value: bytes | str) -> bytes:
    result = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    if len(result) < 16:
        raise ValueError("权益凭证密钥至少需要 16 字节")
    return result
