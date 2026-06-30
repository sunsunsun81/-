from __future__ import annotations

import ipaddress
import re
import socket
import subprocess
from typing import Iterable, List, Optional


def get_primary_lan_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _networks_from_ipconfig() -> List[ipaddress.IPv4Network]:
    networks: List[ipaddress.IPv4Network] = []
    try:
        raw = subprocess.check_output(["ipconfig"], text=True, encoding="mbcs", errors="ignore")
    except Exception:
        return networks

    current_ip = None
    ip_pattern = re.compile(r"IPv4[^\d]*(\d+\.\d+\.\d+\.\d+)")
    mask_pattern = re.compile(r"(?:Subnet Mask|子网掩码)[^\d]*(\d+\.\d+\.\d+\.\d+)", re.IGNORECASE)
    for line in raw.splitlines():
        ip_match = ip_pattern.search(line)
        if ip_match:
            current_ip = ip_match.group(1)
            continue
        mask_match = mask_pattern.search(line)
        if current_ip and mask_match:
            try:
                iface = ipaddress.IPv4Interface(f"{current_ip}/{mask_match.group(1)}")
                if not iface.ip.is_loopback and not iface.ip.is_link_local:
                    networks.append(iface.network)
            except Exception:
                pass
            current_ip = None
    return networks


def allowed_lan_networks() -> List[ipaddress.IPv4Network]:
    networks = _networks_from_ipconfig()
    if networks:
        return networks

    ip = get_primary_lan_ip()
    try:
        addr = ipaddress.ip_address(ip)
        if isinstance(addr, ipaddress.IPv4Address) and not addr.is_loopback:
            parts = ip.split(".")
            return [ipaddress.ip_network(f"{parts[0]}.{parts[1]}.{parts[2]}.0/24")]
    except Exception:
        pass
    return []


def is_allowed_remote(
    remote_addr: Optional[str],
    networks: Optional[Iterable[ipaddress.IPv4Network]] = None,
) -> bool:
    if not remote_addr:
        return False
    try:
        remote = ipaddress.ip_address(remote_addr.split("%")[0])
    except ValueError:
        return False
    if remote.is_loopback:
        return True
    if not isinstance(remote, ipaddress.IPv4Address):
        return False
    allowed = list(networks) if networks is not None else allowed_lan_networks()
    return any(remote in network for network in allowed)
