"""Certified fetch engine for imagery/calibration source adapters."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .core import AdapterPolicy, CertifiedFetchResult, PayloadRequest


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class PayloadValidator:
    @staticmethod
    def sha256_bytes(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def looks_like_html(payload: bytes) -> bool:
        head = payload[:256].lstrip().lower()
        return head.startswith((b"<!doctype html", b"<html", b"<head", b"<body"))

    @staticmethod
    def matches_expected(payload: bytes, content_type: str, expected: str) -> bool:
        expected = (expected or "").lower()
        if PayloadValidator.looks_like_html(payload):
            return False
        if not expected:
            return True
        ctype = (content_type or "").lower()
        if expected == "image":
            return ctype.startswith("image/") or payload.startswith((b"\xff\xd8\xff", b"\x89PNG", b"II*\x00", b"MM\x00*"))
        if expected == "json":
            return "json" in ctype
        if expected == "zip":
            return payload.startswith(b"PK\x03\x04") or "zip" in ctype
        return expected in ctype


class CertifiedFetchEngine:
    """Fetch to staging, hash, cache immutably, then atomically promote raw bytes.

    A failed refresh never deletes or overwrites an existing active manifestation.
    Cache identity is content SHA256, not URL/name identity.
    """

    def __init__(self, policy: AdapterPolicy, timeout: int = 120) -> None:
        policy.validate_runtime_paths()
        self.policy = policy
        self.timeout = timeout

    def dry_run(self, req: PayloadRequest) -> CertifiedFetchResult:
        req.validate()
        return self._result(req, review_status="dry_run", change_state="NOT_FETCHED")

    def fetch(self, req: PayloadRequest, *, previous_sha256: str = "") -> CertifiedFetchResult:
        req.validate()
        for root in (self.policy.raw_payload_root, self.policy.staging_root, self.policy.cache_root):
            root.mkdir(parents=True, exist_ok=True)

        if req.expected_sha256:
            cached = self.policy.cache_root / req.expected_sha256
            if cached.exists():
                raw_path = self.policy.raw_payload_root / self._raw_name(req, req.expected_sha256)
                if not raw_path.exists():
                    self._atomic_copy(cached, raw_path)
                return self._result(
                    req,
                    final_url=req.endpoint.url,
                    filename=str(raw_path),
                    sha256=req.expected_sha256,
                    byte_count=cached.stat().st_size,
                    review_status="cache_hit",
                    previous_sha256=previous_sha256,
                    change_state=self._change_state(req.expected_sha256, previous_sha256),
                )

        method = req.endpoint.method.upper()
        params = tuple((str(k), str(v)) for k, v in req.params.items())
        encoded_text = urlencode(params)
        url = req.endpoint.url
        body = None
        if method == "POST":
            body = encoded_text.encode("utf-8")
        elif encoded_text:
            url += ("&" if "?" in url else "?") + encoded_text

        request = Request(
            url,
            data=body,
            headers={"User-Agent": "skywatcher-pr-source-adapter/1.0", **dict(req.headers)},
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - declared source adapter endpoint
                payload = response.read()
                status = getattr(response, "status", "")
                content_type = response.headers.get("Content-Type", "")
                etag = response.headers.get("ETag", "")
                last_modified = response.headers.get("Last-Modified", "")
                final_url = response.geturl()
        except (HTTPError, URLError, TimeoutError) as exc:
            return self._result(req, http_status=getattr(exc, "code", ""), review_status="failed", error=str(exc), previous_sha256=previous_sha256)

        digest = PayloadValidator.sha256_bytes(payload)
        staged = self.policy.staging_root / f"{req.request_id}.{digest}.part"
        staged.write_bytes(payload)

        if not PayloadValidator.matches_expected(payload, content_type, req.expected_content):
            hold = staged.with_suffix(".hold")
            os.replace(staged, hold)
            return self._result(req, final_url=final_url, http_status=status, content_type=content_type, etag=etag, last_modified=last_modified, filename=str(hold), sha256=digest, byte_count=len(payload), review_status="hold", previous_sha256=previous_sha256, change_state=self._change_state(digest, previous_sha256), error="unexpected_payload_type")

        if req.expected_sha256 and digest != req.expected_sha256:
            hold = staged.with_suffix(".hash_mismatch.hold")
            os.replace(staged, hold)
            return self._result(req, final_url=final_url, http_status=status, content_type=content_type, etag=etag, last_modified=last_modified, filename=str(hold), sha256=digest, byte_count=len(payload), review_status="hold", previous_sha256=previous_sha256, change_state="HASH_MISMATCH", error="expected_sha256_mismatch")

        cache_path = self.policy.cache_root / digest
        if not cache_path.exists():
            os.replace(staged, cache_path)
        else:
            staged.unlink(missing_ok=True)
        raw_path = self.policy.raw_payload_root / self._raw_name(req, digest)
        if not raw_path.exists():
            self._atomic_copy(cache_path, raw_path)
        return self._result(req, final_url=final_url, http_status=status, content_type=content_type, etag=etag, last_modified=last_modified, filename=str(raw_path), sha256=digest, byte_count=len(payload), review_status="raw", previous_sha256=previous_sha256, change_state=self._change_state(digest, previous_sha256))

    def _raw_name(self, req: PayloadRequest, digest: str) -> str:
        hint = req.filename_hint or req.request_id
        safe = "".join(c if c.isalnum() or c in {"-", "_", "."} else "_" for c in hint)
        return f"{safe}.{digest[:12]}"

    def _atomic_copy(self, source: Path, target: Path) -> None:
        tmp = target.with_suffix(target.suffix + ".part")
        tmp.write_bytes(source.read_bytes())
        os.replace(tmp, target)

    @staticmethod
    def _change_state(current: str, previous: str) -> str:
        if not previous:
            return "NEW_MANIFESTATION"
        return "UNCHANGED" if current == previous else "BYTE_CHANGED"

    def _result(self, req: PayloadRequest, *, final_url: str = "", http_status: int | str = "", content_type: str = "", etag: str = "", last_modified: str = "", filename: str = "", sha256: str = "", byte_count: int = 0, review_status: str, previous_sha256: str = "", change_state: str = "UNKNOWN", error: str = "") -> CertifiedFetchResult:
        result = CertifiedFetchResult(
            request_id=req.request_id,
            source_id=req.endpoint.source_id,
            source_lineage_id=req.endpoint.source_lineage_id,
            source_url=req.endpoint.url,
            final_url=final_url,
            request_method=req.endpoint.method.upper(),
            request_params=json.dumps(tuple((str(k), str(v)) for k, v in req.params.items()), ensure_ascii=False),
            retrieval_utc=utc_now(),
            http_status=http_status,
            content_type=content_type,
            etag=etag,
            last_modified=last_modified,
            filename=filename,
            sha256=sha256,
            bytes=byte_count,
            review_status=review_status,
            previous_sha256=previous_sha256,
            change_state=change_state,
            error=error,
        )
        result.validate()
        return result
