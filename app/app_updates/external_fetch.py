"""Credential-free HTTPS, with DNS checked and pinned before every connection."""
from dataclasses import dataclass
import hashlib
import http.client
import ipaddress
import queue
import re
import socket
import ssl
import threading
import time
from urllib.parse import urljoin, urlsplit


class FetchError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


_dns_slots = threading.BoundedSemaphore(4)


def resolve(host, timeout):
    # A wedged OS resolver cannot create unlimited worker threads or bypass the
    # fetch deadline. Threads retain their slot until getaddrinfo really returns.
    if not _dns_slots.acquire(blocking=False):
        raise FetchError("external_dns_busy")
    result = queue.Queue(maxsize=1)
    def run():
        try:
            result.put(socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
        except Exception:
            result.put(None)
        finally:
            _dns_slots.release()
    threading.Thread(target=run, daemon=True, name="apk-dns").start()
    try:
        records = result.get(timeout=timeout)
    except queue.Empty:
        raise FetchError("external_dns_timeout") from None
    if not records:
        raise FetchError("external_dns_failed")
    return tuple(dict.fromkeys(record[4][0] for record in records))


def public_address(value):
    try:
        address = ipaddress.ip_address(value)
        return (address.is_global and not address.is_multicast and not address.is_reserved
            and not getattr(address, "is_site_local", False)
            and not (isinstance(address, ipaddress.IPv6Address) and
                     (address.ipv4_mapped or address.sixtofour or address.teredo
                      or address in ipaddress.ip_network("64:ff9b::/96")
                      or address in ipaddress.ip_network("64:ff9b:1::/48"))))
    except ValueError:
        return False


def hostname(value):
    if (not isinstance(value, str) or len(value) > 253 or value != value.lower()
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", value)
            or "." not in value or any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
                                         for label in value.split("."))):
        raise FetchError("external_host_invalid")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise FetchError("external_host_invalid")


def validate_url(url, allowed_hosts):
    try:
        if (not isinstance(url, str) or len(url) > 4096 or any(ord(c) <= 32 or ord(c) >= 127 for c in url)
                or "\\" in url):
            raise ValueError()
        parsed = urlsplit(url)
        host = hostname(parsed.hostname)
        if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment
                or parsed.port not in (None, 443) or host not in allowed_hosts):
            raise ValueError()
        # Reject alternate spellings that complicate DNS/SNI/Host agreement.
        if parsed.netloc not in (host, host + ":443"):
            raise ValueError()
        return parsed
    except (ValueError, TypeError):
        raise FetchError("external_url_not_allowed") from None


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout, *, context=None, port=443):
        super().__init__(host, port=port, timeout=timeout, context=context or ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
            self.transport_socket = self.sock
        except BaseException:
            raw.close()
            raise


@dataclass(frozen=True)
class FetchedApk:
    size: int
    sha256: str
    range_supported: bool
    evidence: dict


class ExternalFetcher:
    def __init__(self, *, max_bytes=8 * 1024**3, seconds=300, resolver=resolve, connection=PinnedHTTPS):
        if not 0 < max_bytes <= 8 * 1024**3 or not 0 < seconds <= 1200:
            raise ValueError("invalid external fetch limits")
        self.max_bytes, self.seconds = max_bytes, seconds
        self.resolver, self.connection = resolver, connection

    def fetch(self, url, allowed_hosts, output):
        deadline, hops = time.monotonic() + self.seconds, []
        def remaining():
            value = deadline - time.monotonic()
            if value <= 0:
                raise FetchError("external_timeout")
            return min(30, value)
        try:
            for hop in range(4):
                parsed = validate_url(url, allowed_hosts)
                addresses = self.resolver(parsed.hostname, min(5, remaining()))
                if not addresses or len(addresses) > 32 or not all(public_address(ip) for ip in addresses):
                    raise FetchError("external_address_forbidden")
                # Connect directly to the validated IP; SNI/cert/Host retain
                # the approved DNS name. No second DNS lookup or env proxy.
                connection = self.connection(parsed.hostname, addresses[0], remaining())
                response = None
                def abort(connection=connection):
                    sock = getattr(connection, "transport_socket", None) or connection.sock
                    if sock:
                        try:
                            sock.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                        try:
                            sock.close()
                        except OSError:
                            pass
                timer = threading.Timer(max(0.001, deadline - time.monotonic()), abort)
                timer.daemon = True
                timer.start()
                try:
                    path = parsed.path or "/"
                    if parsed.query:
                        path += "?" + parsed.query
                    connection.request("GET", path, headers={"Accept": "application/vnd.android.package-archive, application/octet-stream",
                        "Accept-Encoding": "identity", "User-Agent": "AIYOLO-APK-Verifier/1", "Connection": "close"})
                    response = connection.getresponse()
                    # HTTPConnection detaches its socket for Connection: close.
                    # Retain the connected TLS socket for deadline updates.
                    response_socket = connection.sock
                    if response_socket is None and getattr(response, "fp", None) is not None:
                        response_socket = getattr(getattr(response.fp, "raw", None), "_sock", None)
                    hops.append({"host": parsed.hostname, "addresses": list(addresses), "status": response.status,
                        "urlSha256": hashlib.sha256(url.encode()).hexdigest()})
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.getheader("Location")
                        if hop == 3 or not location:
                            raise FetchError("external_redirect_limit")
                        if (len(response.headers.get_all("Location", [])) != 1 or len(location) > 4096
                                or any(ord(c) <= 32 or ord(c) >= 127 for c in location) or "\\" in location):
                            raise FetchError("external_url_invalid")
                        url = urljoin(url, location)
                        continue
                    if response.status != 200:
                        code = str(response.status) if response.status in (403, 404, 429) or 500 <= response.status <= 599 else "unexpected"
                        raise FetchError("external_http_" + code)
                    if response.getheader("Content-Encoding", "identity").lower() != "identity":
                        raise FetchError("external_encoding_unsupported")
                    mime = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
                    if mime in ("text/html", "application/xhtml+xml", "application/json"):
                        raise FetchError("external_not_apk")
                    lengths = response.headers.get_all("Content-Length", [])
                    if len(lengths) > 1 or (lengths and not re.fullmatch(r"[0-9]{1,12}", lengths[0])):
                        raise FetchError("external_length_invalid")
                    length = int(lengths[0]) if lengths else None
                    if lengths and response.getheader("Transfer-Encoding"):
                        raise FetchError("external_length_invalid")
                    encodings = response.headers.get_all("Transfer-Encoding", [])
                    if encodings and (len(encodings) != 1 or encodings[0].strip().lower() != "chunked"):
                        raise FetchError("external_length_invalid")
                    if length is not None and (length < 1 or length > self.max_bytes):
                        raise FetchError("external_too_large")
                    size, digest, prefix = 0, hashlib.sha256(), b""
                    while True:
                        timeout = remaining()
                        if response_socket is not None:
                            try:
                                response_socket.settimeout(timeout)
                            except OSError:
                                # read1 closed the response at exact Content-
                                # Length. Its next call returns EOF without I/O.
                                if not response.isclosed():
                                    raise
                        # read1 never waits for a whole large block across many
                        # small packets, so the overall deadline is enforced.
                        block = response.read1(min(65536, self.max_bytes - size + 1))
                        if not block:
                            break
                        size += len(block)
                        if size > self.max_bytes:
                            raise FetchError("external_too_large")
                        prefix = (prefix + block)[:4]
                        if len(prefix) >= 4 and prefix != b"PK\x03\x04":
                            raise FetchError("external_not_apk")
                        output.write(block)
                        digest.update(block)
                    if not size or (length is not None and size != length):
                        raise FetchError("external_truncated")
                    remaining()
                    ranges = response.getheader("Accept-Ranges", "").lower() == "bytes"
                    return FetchedApk(size, digest.hexdigest(), ranges,
                        {"hops": hops, "rangeAdvertised": ranges, "contentLength": length})
                finally:
                    timer.cancel()
                    if response is not None:
                        response.close()
                    connection.close()
            raise FetchError("external_redirect_limit")
        except FetchError:
            raise
        except (TimeoutError, socket.timeout):
            raise FetchError("external_timeout") from None
        except ssl.SSLError:
            raise FetchError("external_tls_failed") from None
        except (OSError, http.client.HTTPException):
            raise FetchError("external_timeout" if time.monotonic() >= deadline else "external_connection_failed") from None
