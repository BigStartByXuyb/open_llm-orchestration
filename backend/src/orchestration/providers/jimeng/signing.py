"""
火山引擎 HMAC-SHA256 请求签名工具（纯函数，无副作用）
Volcengine HMAC-SHA256 request signing utilities (pure functions, no side effects).

算法参考 / Algorithm reference:
  - 类 AWS Signature V4 结构 / AWS Signature V4-like structure
  - Header: Authorization: HMAC-SHA256 Credential={ak}/{scope}, SignedHeaders={...}, Signature={...}
  - Header: X-Date: 20060102T150405Z

此模块不依赖任何外部包，仅使用 Python 标准库。
This module has no external dependencies — standard library only.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# 内部辅助函数 / Internal helpers
# ---------------------------------------------------------------------------

def _hmac_sha256_bytes(key: bytes, msg: str) -> bytes:
    """用 HMAC-SHA256 对消息签名，返回原始字节。"""
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _sha256_hex(data: bytes) -> str:
    """返回数据的 SHA-256 十六进制摘要。"""
    return hashlib.sha256(data).hexdigest()


def _derive_signing_key(
    secret_key: str,
    short_date: str,
    region: str,
    service: str,
) -> bytes:
    """
    派生签名密钥（四轮 HMAC-SHA256）
    Derive the signing key (four rounds of HMAC-SHA256).

    SigningKey = HMAC(HMAC(HMAC(HMAC(secret_key, date), region), service), "request")
    """
    k_date = _hmac_sha256_bytes(secret_key.encode("utf-8"), short_date)
    k_region = _hmac_sha256_bytes(k_date, region)
    k_service = _hmac_sha256_bytes(k_region, service)
    return _hmac_sha256_bytes(k_service, "request")


# ---------------------------------------------------------------------------
# 公共 API / Public API
# ---------------------------------------------------------------------------

def build_volcano_auth_headers(
    method: str,
    path: str,
    body: bytes,
    access_key: str,
    secret_key: str,
    *,
    query_string: str = "",
    service: str = "cv",
    region: str = "cn-north-1",
    now: datetime | None = None,
) -> dict[str, str]:
    """
    构建火山引擎 API 请求签名头（HMAC-SHA256）
    Build Volcengine API request signing headers (HMAC-SHA256).

    Args / 参数:
        method:       HTTP 方法，如 "POST"
        path:         URL 路径，如 "/"
        body:         请求体原始字节（用于计算 body hash）
        access_key:   火山引擎 Access Key
        secret_key:   火山引擎 Secret Key
        query_string: URL 查询字符串（不含 "?"），如 "Action=CVProcess&Version=2022-08-31"
        service:      服务名，默认 "cv"（计算机视觉）
        region:       区域，默认 "cn-north-1"
        now:          请求时间（UTC），默认为当前时间；测试时传入固定值以保证确定性

    Returns / 返回:
        包含 "X-Date"、"Authorization"、"Content-Type" 的 dict
        Dict with "X-Date", "Authorization", "Content-Type" keys.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # 时间格式 / Time formats
    x_date = now.strftime("%Y%m%dT%H%M%SZ")
    short_date = now.strftime("%Y%m%d")

    # 规范化请求头（必须按字母序，小写键名）/ Canonical headers (sorted, lowercase keys)
    canonical_headers = f"content-type:application/json\nx-date:{x_date}\n"
    signed_headers = "content-type;x-date"

    # 规范化请求 / Canonical request
    canonical_request = "\n".join([
        method.upper(),
        path,
        query_string,
        canonical_headers,
        signed_headers,
        _sha256_hex(body),
    ])

    # 凭证范围 / Credential scope
    credential_scope = f"{short_date}/{region}/{service}/request"

    # 待签字符串 / String to sign
    string_to_sign = "\n".join([
        "HMAC-SHA256",
        x_date,
        credential_scope,
        _sha256_hex(canonical_request.encode("utf-8")),
    ])

    # 派生签名密钥并计算签名 / Derive key and compute signature
    signing_key = _derive_signing_key(secret_key, short_date, region, service)
    signature = hmac.new(
        signing_key,
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # 组装 Authorization 头 / Assemble Authorization header
    authorization = (
        f"HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )

    return {
        "Content-Type": "application/json",
        "X-Date": x_date,
        "Authorization": authorization,
    }
