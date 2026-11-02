"""Addresses written into records people share (proof packages, packs, the call log)."""

from __future__ import annotations

import re

# scheme://authority/path, then an optional ?query or #fragment that ends at a space or quote, not at the punctuation
# of the sentence around it ("see https://h/docs#x), then")
_URL = re.compile(r"""(?<![A-Za-z0-9+.-])([A-Za-z][A-Za-z0-9+.-]*://)([^/?#\s"'<>]*)([^?#\s"'<>]*)"""
                  r"""(?:[?#][^\s"'<>]*?)?(?=[.,;:!?)\]}]*(?:[\s"'<>]|$))""")


def strip_url_secrets(text: str) -> str:
    """`text` with every URL in it reduced to scheme, host, port and path. Keys travel in the userinfo
    (`https://user:key@host/v1`), the query (`?api_key=...`) and sometimes the fragment, none of which belongs in a
    file that is shared. Works on one address or on a message that quotes addresses."""
    return _URL.sub(lambda m: m[1] + m[2].rpartition("@")[2] + m[3], text)
