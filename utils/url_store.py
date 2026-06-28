import hashlib
from typing import Optional

_store: dict[str, str] = {}

def store(url: str) -> str:
    key = hashlib.md5(url.encode()).hexdigest()[:8]
    _store[key] = url
    return key

def resolve(key: str) -> Optional[str]:
    return _store.get(key)
