"""Schutz vor Abrufen interner Netze (SSRF) und Beschränkung auf konfigurierte öffentliche Domains.

Jede URL – auch jedes Weiterleitungsziel – wird geprüft:
* Schema https (http nur, wenn die Quelle es ausdrücklich erlaubt; Standard: Upgrade auf https),
* Host muss zu den erlaubten Domains der Quelle gehören,
* aufgelöste IP-Adressen dürfen nicht privat, loopback, link-local (inkl. Metadatendienst 169.254.169.254),
  multicast oder reserviert sein.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlsplit, urlunsplit


class ForbiddenTarget(Exception):
    """Ziel liegt außerhalb der erlaubten öffentlichen Domains oder in einem internen Netz."""


def host_allowed(host: str, allowed_domains: tuple[str, ...] | list[str]) -> bool:
    host = host.lower().rstrip(".")
    for d in allowed_domains:
        d = d.lower().lstrip(".")
        if host == d or host.endswith("." + d):
            return True
    return False


def ip_is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
        or (isinstance(addr, ipaddress.IPv4Address) and addr in ipaddress.ip_network("100.64.0.0/10"))
    )


def _outbound_proxy_configured() -> bool:
    return bool(os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"))


def normalize_url(url: str) -> str:
    """Schema/Host klein, http→https, Fragment entfernen."""
    parts = urlsplit(url.strip())
    scheme = "https" if parts.scheme in ("http", "https") else parts.scheme
    return urlunsplit((scheme, parts.netloc.lower(), parts.path or "/", parts.query, ""))


def check_url(url: str, allowed_domains: tuple[str, ...] | list[str], *, resolve: bool = True) -> str:
    """Prüft eine URL und gibt die normalisierte Form zurück; wirft ``ForbiddenTarget``."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ForbiddenTarget(f"Schema nicht erlaubt: {parts.scheme!r}")
    if parts.username or parts.password:
        raise ForbiddenTarget("Zugangsdaten in URL nicht erlaubt")
    host = (parts.hostname or "").lower()
    if not host:
        raise ForbiddenTarget("kein Host")
    if parts.port not in (None, 80, 443):
        raise ForbiddenTarget(f"Port nicht erlaubt: {parts.port}")
    # IP-Literale sind nie erlaubt (nur konfigurierte Domainnamen)
    try:
        ipaddress.ip_address(host)
        raise ForbiddenTarget("IP-Adresse statt Domainname")
    except ValueError:
        pass
    if not host_allowed(host, allowed_domains):
        raise ForbiddenTarget(f"Host {host!r} gehört nicht zu den erlaubten Domains {list(allowed_domains)}")
    if resolve:
        try:
            infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            # Hinter einem ausgehenden Proxy löst dieser den Namen auf; dann bleibt die Domainprüfung.
            if not _outbound_proxy_configured():
                raise ForbiddenTarget(f"Host {host!r} nicht auflösbar") from exc
            infos = []
        for info in infos:
            ip = info[4][0]
            if not ip_is_public(ip):
                raise ForbiddenTarget(f"Host {host!r} löst auf nicht-öffentliche Adresse {ip} auf")
    return normalize_url(url)
