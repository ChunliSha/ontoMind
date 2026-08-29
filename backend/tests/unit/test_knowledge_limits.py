"""Unit tests for knowledge query limits."""

from __future__ import annotations

import pytest

from app.core.exceptions import AppError, ErrorCode
from app.knowledge.limits import clamp_hops, clamp_limit, clamp_nodes, max_hops, max_limit, max_nodes


def test_clamp_limit_default():
    assert clamp_limit(None) == 20


def test_clamp_limit_over_max():
    with pytest.raises(AppError) as ei:
        clamp_limit(max_limit() + 1)
    assert ei.value.code == ErrorCode.KNOWLEDGE_002


def test_clamp_hops_over_max():
    with pytest.raises(AppError) as ei:
        clamp_hops(max_hops() + 1)
    assert ei.value.code == ErrorCode.KNOWLEDGE_002


def test_clamp_nodes_over_max():
    with pytest.raises(AppError) as ei:
        clamp_nodes(max_nodes() + 1)
    assert ei.value.code == ErrorCode.KNOWLEDGE_002


def test_clamp_limit_zero():
    with pytest.raises(AppError) as ei:
        clamp_limit(0)
    assert ei.value.code == ErrorCode.KNOWLEDGE_002
