#!/usr/bin/env python3
"""
World Conqueror 4 Microsoft Store save editor.

当前只编辑已经通过实测确认的 headquarter.sav 资源字段：
- 顶层 field1 内的 field4-field8：资源栏中的五个主要资源。
- 顶层 field1 内的 field21：令牌资源，已通过 0 -> 10 领取差分确认。

存档校验：
- 文件头前 4 字节为 YSAE。
- offset 8 的 uint32 为 payload 长度。
- offset 12-27 为 MD5(payload + b"wc4hq")。
- payload 从 offset 28 开始，是 Protobuf 风格二进制数据。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import struct
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


MAGIC = b"YSAE"
SALT = b"wc4hq"
HEADER_SIZE = 28


@dataclass(frozen=True)
class KnownField:
    key: str
    field_number: int
    label: str


KNOWN_FIELDS: dict[str, KnownField] = {
    "resource4": KnownField("resource4", 4, "金币资源"),
    "resource5": KnownField("resource5", 5, "齿轮资源"),
    "resource6": KnownField("resource6", 6, "紫色资源"),
    "resource7": KnownField("resource7", 7, "科技点资源"),
    "resource8": KnownField("resource8", 8, "勋章资源"),
    "resource21": KnownField("resource21", 21, "令牌资源"),
}

ALIASES = {
    "gold": "resource4",
    "gear": "resource5",
    "purple": "resource6",
    "tech": "resource7",
    "science": "resource7",
    "medal": "resource8",
    "token": "resource21",
}


def default_local_state() -> Path:
    userprofile = os.environ.get("USERPROFILE")
    if not userprofile:
        raise RuntimeError("无法读取 USERPROFILE 环境变量，请手动传入 --dir。")
    return (
        Path(userprofile)
        / "AppData"
        / "Local"
        / "Packages"
        / "EasyTech.WorldConqueror4_nz34nvfqxfk3r"   #手动更改这里后面的标识符
        / "LocalState"
    )


def read_varint(data: bytearray | bytes, pos: int) -> tuple[int, int]:
    shift = 0
    result = 0
    while pos < len(data):
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, pos
        shift += 7
    raise ValueError("读取 varint 时到达文件末尾")


def encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("当前编辑器只支持非负整数资源值")
    out = bytearray()
    while True:
        part = value & 0x7F
        value >>= 7
        if value:
            part |= 0x80
        out.append(part)
        if not value:
            return bytes(out)


def replace_range(data: bytearray, start: int, old_len: int, new_bytes: bytes) -> tuple[bytearray, int]:
    delta = len(new_bytes) - old_len
    return data[:start] + bytearray(new_bytes) + data[start + old_len :], delta


def validate_and_get_payload(data: bytes) -> tuple[int, bytes]:
    if len(data) < HEADER_SIZE:
        raise ValueError("文件太短，不像有效 YSAE 存档")
    if data[:4] != MAGIC:
        raise ValueError("文件头不是 YSAE")
    payload_len = struct.unpack_from("<I", data, 8)[0]
    if HEADER_SIZE + payload_len != len(data):
        raise ValueError(
            f"payload 长度不匹配：头部={payload_len}，实际={len(data) - HEADER_SIZE}"
        )
    payload = data[HEADER_SIZE:]
    expected = hashlib.md5(payload + SALT).digest()
    actual = data[12:28]
    if expected != actual:
        raise ValueError("MD5 校验不匹配，存档可能已损坏或格式不同")
    return payload_len, payload


def top_field1_bounds(data: bytes | bytearray) -> tuple[int, int, int, int, int]:
    pos = HEADER_SIZE
    key, pos = read_varint(data, pos)
    field = key >> 3
    wire = key & 7
    if field != 1 or wire != 2:
        raise ValueError("payload 顶层 field1 不是 length-delimited")
    len_start = pos
    field1_len, pos = read_varint(data, pos)
    len_end = pos
    data_start = pos
    data_end = data_start + field1_len
    if data_end > len(data):
        raise ValueError("field1 长度越界")
    return len_start, len_end, field1_len, data_start, data_end


def parse_field1_varints(data: bytes | bytearray) -> dict[int, tuple[int, int, int]]:
    _, _, _, start, end = top_field1_bounds(data)
    pos = start
    fields: dict[int, tuple[int, int, int]] = {}
    while pos < end:
        key_start = pos
        key, pos = read_varint(data, pos)
        field = key >> 3
        wire = key & 7
        if wire == 0:
            value_start = pos
            value, pos = read_varint(data, pos)
            fields[field] = (value, value_start, pos)
        elif wire == 2:
            length, pos = read_varint(data, pos)
            pos += length
        else:
            raise ValueError(f"暂不支持 wire type {wire}，位置 {key_start}")
    return fields


def recompute_header(data: bytearray) -> None:
    payload_len = len(data) - HEADER_SIZE
    struct.pack_into("<I", data, 8, payload_len)
    digest = hashlib.md5(bytes(data[HEADER_SIZE:]) + SALT).digest()
    data[12:28] = digest


def patch_field1_value(data: bytes, field_number: int, new_value: int) -> bytes:
    working = bytearray(data)
    validate_and_get_payload(bytes(working))
    len_start, len_end, field1_len, _, _ = top_field1_bounds(working)
    fields = parse_field1_varints(working)
    if field_number not in fields:
        raise ValueError(f"没有在 field1 中找到字段 {field_number}")
    old_value, value_start, value_end = fields[field_number]
    encoded = encode_varint(new_value)
    working, delta = replace_range(working, value_start, value_end - value_start, encoded)

    if delta:
        new_field1_len = field1_len + delta
        new_len_encoded = encode_varint(new_field1_len)
        old_len_width = len_end - len_start
        if len(new_len_encoded) != old_len_width:
            raise ValueError("field1 长度编码宽度变化，当前编辑器为安全起见拒绝写入")
        working[len_start:len_end] = new_len_encoded

    recompute_header(working)
    print(f"字段 {field_number}: {old_value} -> {new_value}")
    return bytes(working)


def backup_file(path: Path, backup_dir: Path, stamp: str) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{path.name}.bak_{stamp}"
    shutil.copy2(path, target)
    return target


def resolve_field(name: str) -> KnownField:
    key = ALIASES.get(name.lower(), name.lower())
    if key not in KNOWN_FIELDS:
        valid = ", ".join(sorted(set(KNOWN_FIELDS) | set(ALIASES)))
        raise ValueError(f"未知字段名：{name}。可用字段：{valid}")
    return KNOWN_FIELDS[key]


def show_values(local_state: Path) -> None:
    path = local_state / "headquarter.sav"
    data = path.read_bytes()
    validate_and_get_payload(data)
    fields = parse_field1_varints(data)
    print(f"文件: {path}")
    print(f"大小: {len(data)} bytes")
    print("已知字段:")
    for key, known in KNOWN_FIELDS.items():
        value = fields.get(known.field_number, (None, None, None))[0]
        print(f"  {key:10s} field{known.field_number:<2d} = {value}  # {known.label}")


def set_value(local_state: Path, field_name: str, value: int, backup_dir: Path) -> None:
    known = resolve_field(field_name)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    paths = [local_state / "headquarter.sav", local_state / "headquarter.bak"]
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)

    backups = [backup_file(path, backup_dir, stamp) for path in paths]
    print("已备份:")
    for backup in backups:
        print(f"  {backup}")

    patched_blobs = []
    for path in paths:
        patched_blobs.append(patch_field1_value(path.read_bytes(), known.field_number, value))

    if patched_blobs[0] != patched_blobs[1]:
        raise RuntimeError("sav 与 bak 生成结果不一致，已停止写入")

    for path, blob in zip(paths, patched_blobs):
        path.write_bytes(blob)
    print(f"已写入 {known.key} = {value}，并同步更新 headquarter.sav / headquarter.bak")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="世界征服者4总部存档资源编辑器")
    parser.add_argument("--dir", type=Path, default=default_local_state(), help="LocalState 存档目录")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path.cwd() / "wc4_save_backups",
        help="自动备份目录",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show", help="显示已知资源字段")
    set_parser = sub.add_parser("set", help="设置一个已知资源字段")
    set_parser.add_argument("field", help="字段名，如 resource8/medal/resource21/token")
    set_parser.add_argument("value", type=int, help="新数值，非负整数")

    args = parser.parse_args(argv)
    local_state = args.dir
    if args.command == "show":
        show_values(local_state)
    elif args.command == "set":
        set_value(local_state, args.field, args.value, args.backup_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
