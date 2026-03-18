from fastapi import Request
import requests
import logging

logger = logging.getLogger(__name__)


def get_client_ip(request: Request) -> str:
    """
    Extract client IP address from request headers or direct connection.
    """
    if request.headers.get("x-forwarded-for"):
        return request.headers["x-forwarded-for"].split(",")[0].strip()
    if request.client:
        return request.client.host
    return "127.0.0.1"


def is_private_ip(ip: str) -> bool:
    if not ip or ip in ["127.0.0.1", "localhost", "::1"]:
        return True
    # Basic private ranges
    if ip.startswith("192.168.") or ip.startswith("10."):
        return True
    if ip.startswith("172."):
        try:
            second_octet = int(ip.split(".")[1])
            if 16 <= second_octet <= 31:
                return True
        except Exception:
            pass
    return False


def get_country_from_ip(ip: str) -> str:
    """
    Identify country code from IP. Falls back to server IP if client is local.
    """
    try:
        url = "http://ip-api.com/json/?fields=status,countryCode,message"
        if not is_private_ip(ip):
            url = f"http://ip-api.com/json/{ip}?fields=status,countryCode,message"

        response = requests.get(url, timeout=3)
        response.raise_for_status()
        data = response.json()

        if data.get("status") == "success":
            return data.get("countryCode", "US")

        # If the IP was "private" or "reserved" for the service, try server self-lookup
        if not is_private_ip(ip):
            fallback_res = requests.get(
                "http://ip-api.com/json/?fields=status,countryCode", timeout=3
            )
            if fallback_res.ok:
                fallback_data = fallback_res.json()
                if fallback_data.get("status") == "success":
                    return fallback_data.get("countryCode", "US")

        return "US"
    except Exception as e:
        logger.error(f"Failed to detect country for IP {ip}: {e}")
        return "US"
