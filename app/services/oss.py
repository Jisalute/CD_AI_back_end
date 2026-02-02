from __future__ import annotations

_OSS_STORE: dict[str, bytes] = {}


def upload_file_to_oss(filename: str, content: bytes) -> str:
    """Stub: upload content to OSS and return an oss_key."""
    # In production, call SDK to upload and return key. Here store in memory.
    key = f"oss://bucket/{filename}"
    _OSS_STORE[key] = content
    return key


def get_file_from_oss(oss_key: str) -> tuple[str, bytes]:
    """Stub: download content from OSS by oss_key and return filename + bytes."""
    if oss_key not in _OSS_STORE:
        raise KeyError("file not found")
    filename = oss_key.rsplit("/", 1)[-1] or "download.bin"
    return filename, _OSS_STORE[oss_key]
