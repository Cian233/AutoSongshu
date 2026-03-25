from __future__ import annotations

from urllib.parse import urljoin, urlparse


class ScopeViolationError(RuntimeError):
    pass


class ScopePolicy:
    def __init__(
        self,
        start_url: str = "",
        allowed_hosts: list[str] | None = None,
        allow_subdomains: bool = True,
        allowed_schemes: tuple[str, ...] = ("http", "https"),
    ) -> None:
        self.start_url = start_url
        self.allowed_hosts = [item.lower() for item in (allowed_hosts or [])]
        self.allow_subdomains = allow_subdomains
        self.allowed_schemes = allowed_schemes

    @property
    def is_unrestricted(self) -> bool:
        return len(self.allowed_hosts) == 0

    def describe(self) -> str:
        if self.is_unrestricted:
            return "unrestricted (no authorization scope defined)"
        return (
            f"start_url={self.start_url}, "
            f"allowed_hosts={self.allowed_hosts}, "
            f"allow_subdomains={self.allow_subdomains}"
        )

    def is_host_allowed(self, host: str | None) -> bool:
        if not host:
            return False
        if self.is_unrestricted:
            return True
        host = host.lower()
        for pattern in self.allowed_hosts:
            if pattern.startswith("*."):
                suffix = pattern[2:]
                if host == suffix or host.endswith(f".{suffix}"):
                    return True
                continue
            if host == pattern:
                return True
            if self.allow_subdomains and host.endswith(f".{pattern}"):
                return True
        return False

    def normalize_url(self, url: str, current_url: str | None = None) -> str:
        base_url = current_url or self.start_url
        resolved = urljoin(base_url, url) if base_url else url
        parsed = urlparse(resolved)
        if parsed.scheme not in self.allowed_schemes:
            raise ScopeViolationError(
                f"URL scheme '{parsed.scheme}' is not allowed. Allowed schemes: {self.allowed_schemes}",
            )
        if not self.is_host_allowed(parsed.hostname):
            raise ScopeViolationError(
                f"URL host '{parsed.hostname}' is outside the authorized scope.",
            )
        return resolved

    def assert_in_scope(self, url: str, current_url: str | None = None) -> str:
        return self.normalize_url(url, current_url=current_url)


__all__ = ["ScopePolicy", "ScopeViolationError"]
