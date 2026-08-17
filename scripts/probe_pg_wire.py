"""排障用：探测 172.25.58.24:5432 是否真的在讲 PostgreSQL 协议。

Test-NetConnection 显示 TCP 可达但 asyncpg 握手超时，这种组合通常意味着中间有代理
接受了连接却没把流量转到真实的 Postgres。本脚本发一个 SSLRequest 包并等待应答：
  - 收到 'S' / 'N'  -> 对端确实是 PostgreSQL
  - 读超时/读到 0 字节 -> 对端接受了 TCP 但不是 Postgres（或流量被中断）
"""

from __future__ import annotations

import socket
import struct
import sys

HOST = sys.argv[1] if len(sys.argv) > 1 else "172.25.58.24"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 5432
TIMEOUT = float(sys.argv[3]) if len(sys.argv) > 3 else 20.0

SSL_REQUEST = struct.pack("!ii", 8, 80877103)

print(f"探测 {HOST}:{PORT}，超时 {TIMEOUT}s")

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(TIMEOUT)

try:
    sock.connect((HOST, PORT))
    print(f"[ OK ] TCP 已建立，本端 {sock.getsockname()}")
except Exception as exc:  # noqa: BLE001
    print(f"[FAIL] TCP 建立失败：{type(exc).__name__}: {exc}")
    raise SystemExit(1)

try:
    sock.sendall(SSL_REQUEST)
    print("[ OK ] 已发送 SSLRequest(8 字节)，等待应答…")
    data = sock.recv(1)
    if not data:
        print("[FAIL] 对端关闭了连接且未应答 —— 不是 PostgreSQL，或被中间设备切断")
        raise SystemExit(1)
    if data in (b"S", b"N"):
        mode = "支持 TLS" if data == b"S" else "不支持 TLS（明文）"
        print(f"[ OK ] 收到 {data!r} —— 对端是 PostgreSQL，{mode}")
        raise SystemExit(0)
    print(f"[WARN] 收到非预期字节 {data!r} —— 对端可能不是 PostgreSQL")
    raise SystemExit(1)
except socket.timeout:
    print(f"[FAIL] {TIMEOUT}s 内无任何应答 —— TCP 握手成功但协议层无响应")
    print("       典型原因：中间代理/VPN 接受连接但未转发，或服务端防火墙静默丢包")
    raise SystemExit(1)
finally:
    sock.close()
