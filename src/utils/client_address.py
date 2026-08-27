"""Client address resolution for logging and stats."""


def client_host(request) -> str:
    """Best-effort client IP; prefers the leftmost X-Forwarded-For entry.

    In production the gateway sits behind a reverse proxy and
    request.client.host would record the proxy's address on every row, so the
    forwarded header wins when present. The header is client-spoofable when
    no proxy strips it — acceptable because client_ip is informational stats,
    never auth.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip() if forwarded else ""
    if first:
        return first
    client = getattr(request, "client", None)
    return client.host if client else "unknown"
