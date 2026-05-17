"""Active Directory LDAP client (Phase C-3, Issue #230).

Thin wrapper around ldap3 for querying AD user accounts.
All network I/O is isolated here to enable easy mocking in tests.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_ATTRS = [
    "sAMAccountName",
    "displayName",
    "mail",
    "distinguishedName",
    "userAccountControl",
]

# Bit flag: account disabled in AD
_UAC_ACCOUNT_DISABLE = 0x2


def _is_disabled(entry) -> bool:
    """Return True if the AD userAccountControl flag marks the account disabled."""
    try:
        uac = int(entry.userAccountControl.value)
        return bool(uac & _UAC_ACCOUNT_DISABLE)
    except Exception:
        return False


def search_ad_users(
    *,
    host: str,
    port: int = 389,
    bind_dn: str,
    bind_password: str,
    base_dn: str,
    user_filter: str = "(&(objectClass=user)(objectCategory=person))",
    use_ssl: bool = False,
    timeout: int = 5,
    attributes: Optional[list[str]] = None,
) -> list[dict]:
    """Connect to AD, run a search, and return a list of user dicts.

    Returns an empty list on connection or search error (caller surfaces 503).
    """
    try:
        import ldap3
    except ImportError:
        logger.error("ldap3 is not installed; AD sync is unavailable")
        return []

    if not host or not bind_dn or not base_dn:
        return []

    attrs = attributes or _DEFAULT_ATTRS

    try:
        server = ldap3.Server(
            host,
            port=port,
            use_ssl=use_ssl,
            connect_timeout=timeout,
        )
        with ldap3.Connection(
            server,
            user=bind_dn,
            password=bind_password,
            auto_bind=ldap3.AUTO_BIND_TLS_BEFORE_BIND
            if not use_ssl
            else ldap3.AUTO_BIND_NO_TLS,
        ) as conn:
            conn.search(
                search_base=base_dn,
                search_filter=user_filter,
                attributes=attrs,
            )
            users = []
            for entry in conn.entries:
                users.append(
                    {
                        "dn": str(entry.entry_dn),
                        "username": str(entry.sAMAccountName.value)
                        if entry.sAMAccountName
                        else "",
                        "display_name": str(entry.displayName.value)
                        if entry.displayName
                        else "",
                        "email": str(entry.mail.value) if entry.mail else "",
                        "disabled": _is_disabled(entry),
                    }
                )
            logger.info("AD search returned %d users from %s", len(users), host)
            return users
    except Exception as exc:
        logger.warning("AD search failed: %s", exc)
        return []


def test_ad_connection(
    *,
    host: str,
    port: int = 389,
    bind_dn: str,
    bind_password: str,
    use_ssl: bool = False,
    timeout: int = 5,
) -> tuple[bool, str]:
    """Test bind-only connection. Returns (success, message)."""
    try:
        import ldap3
    except ImportError:
        return False, "ldap3 not installed"

    if not host:
        return False, "AD host not configured"

    try:
        server = ldap3.Server(host, port=port, use_ssl=use_ssl, connect_timeout=timeout)
        with ldap3.Connection(
            server,
            user=bind_dn,
            password=bind_password,
            auto_bind=ldap3.AUTO_BIND_TLS_BEFORE_BIND
            if not use_ssl
            else ldap3.AUTO_BIND_NO_TLS,
        ):
            return True, "Connected successfully"
    except Exception as exc:
        return False, str(exc)
