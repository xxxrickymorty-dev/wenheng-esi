# -*- coding: utf-8 -*-
"""`tools/ports.py` 的纯函数层：netstat 解析与端口归类。

不起子进程、不读真实系统状态——只钉住「什么算本机回环监听」和「什么算违规端口」。
"""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))

import ports  # noqa: E402

SAMPLE = """\
活动连接

  协议  本地地址          外部地址        状态           PID
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       920
  TCP    127.0.0.1:8080         0.0.0.0:0              LISTENING       18060
  TCP    127.0.0.1:8091         0.0.0.0:0              LISTENING       33456
  TCP    [::1]:5180             [::]:0                 LISTENING       17104
  TCP    127.0.0.1:7897         0.0.0.0:0              LISTENING       45108
  TCP    127.0.0.1:52345        127.0.0.1:8080         ESTABLISHED     18060
"""


def test_只认本机回环的监听行():
    rows = ports.parse_netstat(SAMPLE)
    ports_seen = sorted(r["port"] for r in rows)
    # 0.0.0.0:135 不是回环；52345 是 ESTABLISHED 不是 LISTENING
    assert ports_seen == [5180, 7897, 8080, 8091]


def test_ipv6_回环也认():
    rows = {r["port"]: r for r in ports.parse_netstat(SAMPLE)}
    assert rows[5180]["host"] == "[::1]"
    assert rows[5180]["pid"] == 17104


def test_空输入不炸():
    assert ports.parse_netstat("") == []
    assert ports.parse_netstat("活动连接\n") == []


def test_唯一入口是_8080():
    legacy = ports.LEGACY
    assert 8080 in legacy
    # 历史端口都在表里（用来判违规），且都带说明
    for p in (5173, 5180, 5181, 8081, 8082, 8091, 8777):
        assert p in legacy and legacy[p].strip()
    assert "唯一入口" in legacy[8080]
