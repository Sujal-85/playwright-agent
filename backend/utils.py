from urllib.parse import urlparse, urljoin, urlunparse
import re

SKIP_EXTENSIONS = {
    '.pdf', '.zip', '.tar', '.gz', '.rar', '.7z',
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.webp', '.ico',
    '.mp4', '.mp3', '.avi', '.mov', '.wmv', '.flv',
    '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.exe', '.dmg', '.pkg', '.deb', '.rpm',
    '.css', '.js', '.woff', '.woff2', '.ttf', '.eot',
    '.xml', '.rss', '.atom',
}

SKIP_SCHEMES = {'mailto:', 'tel:', 'javascript:', 'ftp:', 'data:'}


def normalize_url(url: str, base: str) -> str:
    """Convert relative URL to absolute and normalize."""
    try:
        absolute = urljoin(base, url.strip())
        parsed = urlparse(absolute)
        # Remove fragment
        cleaned = urlunparse((
            parsed.scheme,
            parsed.netloc.lower(),
            parsed.path,
            parsed.params,
            parsed.query,
            ''  # Remove fragment
        ))
        return cleaned.rstrip('/')
    except Exception:
        return ''


def is_same_domain(url: str, base_url: str) -> bool:
    """Check if URL belongs to the same domain as base_url."""
    try:
        url_parsed = urlparse(url)
        base_parsed = urlparse(base_url)
        url_host = url_parsed.netloc.lower().lstrip('www.')
        base_host = base_parsed.netloc.lower().lstrip('www.')
        return url_host == base_host
    except Exception:
        return False


def should_skip_url(url: str) -> bool:
    """Return True if URL should be skipped."""
    if not url:
        return True
    url_lower = url.lower()
    for scheme in SKIP_SCHEMES:
        if url_lower.startswith(scheme):
            return True
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return True
        path = parsed.path.lower()
        _, ext = path.rsplit('.', 1) if '.' in path.split('/')[-1] else ('', '')
        if f'.{ext}' in SKIP_EXTENSIONS:
            return True
    except Exception:
        return True
    return False


def clean_url(url: str) -> str:
    """Remove fragment and normalize."""
    try:
        parsed = urlparse(url)
        return urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path, parsed.params, parsed.query, ''))
    except Exception:
        return url
