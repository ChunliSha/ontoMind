from app.core.exceptions import AppError
from app.storage.minio_backend import parse_minio_endpoint


def test_parse_plain_host_port():
    host, tls = parse_minio_endpoint("172.24.116.1:9000")
    assert host == "172.24.116.1:9000"
    assert tls is False


def test_parse_http_url():
    host, tls = parse_minio_endpoint("http://minio.local:9000")
    assert host == "minio.local:9000"
    assert tls is False


def test_parse_https_url():
    host, tls = parse_minio_endpoint("https://s3.example.com")
    assert host == "s3.example.com"
    assert tls is True


def test_parse_empty_raises():
    try:
        parse_minio_endpoint("  ")
    except AppError as exc:
        assert "MINIO_ENDPOINT" in (exc.message or "")
    else:
        raise AssertionError("expected AppError")
