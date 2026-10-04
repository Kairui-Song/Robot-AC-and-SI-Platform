#!/usr/bin/env python3
"""Read-only DS402 and PDO probe using the EtherCAT CLI.

This script never writes to the bus. It inspects a single slave's standard
mapping objects and common CiA 402 status objects, then prints JSON events so
the caller can capture results without scraping human text.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys


class EthercatError(RuntimeError):
    pass


def emit(event, **payload):
    print(json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def parse_ethercat_value(output):
    tokens = re.findall(r"-?0x[0-9a-fA-F]+|-?\d+", output or "")
    if not tokens:
        raise EthercatError(f"无法解析 EtherCAT 返回值: {output!r}")
    token = tokens[-1]
    sign = -1 if token.startswith("-") else 1
    token = token[1:] if sign < 0 else token
    base = 16 if token.lower().startswith("0x") else 10
    return sign * int(token, base)


def parse_mapping_entry(value):
    unsigned = value & 0xFFFFFFFF
    return {
        "raw": f"0x{unsigned:08X}",
        "index": f"0x{(unsigned >> 16) & 0xFFFF:04X}",
        "subindex": (unsigned >> 8) & 0xFF,
        "bits": unsigned & 0xFF,
    }


class EthercatRunner:
    def __init__(self, master="0"):
        self.master = str(master)

    def run(self, args, timeout=8):
        completed = subprocess.run(
            ["ethercat", "-m", self.master, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if completed.returncode:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise EthercatError(detail or f"ethercat 返回码 {completed.returncode}")
        return (completed.stdout or "").strip()

    def upload(self, position, index, subindex, data_type):
        return parse_ethercat_value(
            self.run(["upload", "-p", str(position), index, subindex, "-t", data_type])
        )

    def upload_optional(self, position, index, subindex, data_type):
        try:
            return {"ok": True, "value": self.upload(position, index, subindex, data_type)}
        except EthercatError as exc:
            return {"ok": False, "error": str(exc)}

    def slaves(self):
        return self.run(["slaves"])


def parse_slave_row(output, position):
    pattern = re.compile(
        r"^\s*(?P<position>\d+)\s+\d+:\d+\s+(?P<state>\w+)\s+\+\s+(?P<name>.+?)\s*$"
    )
    for line in output.splitlines():
        match = pattern.match(line)
        if match and int(match.group("position")) == int(position):
            return {
                "position": int(match.group("position")),
                "al_state": match.group("state").upper(),
                "name": match.group("name").strip(),
            }
    raise EthercatError(f"未在 ethercat slaves 输出中找到从站 position={position}")


def read_assignment(runner, position, index):
    count = runner.upload(position, index, "0x00", "uint8")
    entries = []
    for subindex in range(1, count + 1):
        mapped_index = runner.upload(position, index, f"0x{subindex:02x}", "uint16")
        entries.append(f"0x{mapped_index & 0xFFFF:04X}")
    return {"index": index, "count": count, "entries": entries}


def read_pdo(runner, position, index):
    count = runner.upload(position, index, "0x00", "uint8")
    entries = []
    for subindex in range(1, count + 1):
        raw = runner.upload(position, index, f"0x{subindex:02x}", "uint32")
        entries.append(parse_mapping_entry(raw))
    return {"index": index, "count": count, "entries": entries}


def read_ds402_snapshot(runner, position):
    status = runner.upload_optional(position, "0x6041", "0x00", "uint16")
    mode_display = runner.upload_optional(position, "0x6061", "0x00", "int8")
    mode_command = runner.upload_optional(position, "0x6060", "0x00", "int8")
    actual_position = runner.upload_optional(position, "0x6064", "0x00", "int32")
    error_code = runner.upload_optional(position, "0x603F", "0x00", "uint16")
    return {
        "status_word": status if not status["ok"] else {
            "ok": True,
            "value": status["value"],
            "hex": f"0x{status['value'] & 0xFFFF:04X}",
        },
        "mode_display": mode_display,
        "mode_command": mode_command,
        "position_actual": actual_position,
        "error_code": error_code if not error_code["ok"] else {
            "ok": True,
            "value": error_code["value"],
            "hex": f"0x{error_code['value'] & 0xFFFF:04X}",
        },
    }


def probe_slave(runner, position):
    slave = parse_slave_row(runner.slaves(), position)
    emit("progress", stage="slave_identified", slave=slave)
    rx_assignment = read_assignment(runner, position, "0x1C12")
    tx_assignment = read_assignment(runner, position, "0x1C13")
    emit("progress", stage="pdo_assignment_read", rxpdo=rx_assignment, txpdo=tx_assignment)

    pdos = {"rxpdo": [], "txpdo": []}
    for index in rx_assignment["entries"]:
        pdo = read_pdo(runner, position, index)
        pdos["rxpdo"].append(pdo)
        emit("progress", stage="rxpdo_read", pdo=pdo)
    for index in tx_assignment["entries"]:
        pdo = read_pdo(runner, position, index)
        pdos["txpdo"].append(pdo)
        emit("progress", stage="txpdo_read", pdo=pdo)

    ds402 = read_ds402_snapshot(runner, position)
    emit("progress", stage="ds402_snapshot", ds402=ds402)
    return {
        "slave": slave,
        "assignments": {"rxpdo": rx_assignment, "txpdo": tx_assignment},
        "pdos": pdos,
        "ds402": ds402,
        "motion_allowed": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only DS402/PDO probe")
    parser.add_argument("--master", default="0")
    parser.add_argument("--position", type=int, required=True)
    args = parser.parse_args(argv)

    runner = EthercatRunner(master=args.master)
    try:
        result = probe_slave(runner, args.position)
    except Exception as exc:
        emit(
            "result",
            target="ds402_probe",
            ok=False,
            master=str(args.master),
            position=args.position,
            motion_allowed=False,
            error=str(exc),
        )
        return 1

    emit(
        "result",
        target="ds402_probe",
        ok=True,
        master=str(args.master),
        position=args.position,
        motion_allowed=False,
        result=result,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
