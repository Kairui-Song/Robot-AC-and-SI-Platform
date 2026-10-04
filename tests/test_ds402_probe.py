from controller.ds402_probe import (
    parse_ethercat_value,
    parse_mapping_entry,
    probe_slave,
)


class FakeRunner:
    def slaves(self):
        return "0  0:0 PREOP + JE DS402 Motor"

    def upload(self, position, index, subindex, data_type):
        key = (position, index.lower(), subindex.lower(), data_type)
        table = {
            (0, "0x1c12", "0x00", "uint8"): 1,
            (0, "0x1c12", "0x01", "uint16"): 0x1600,
            (0, "0x1c13", "0x00", "uint8"): 1,
            (0, "0x1c13", "0x01", "uint16"): 0x1A00,
            (0, "0x1600", "0x00", "uint8"): 3,
            (0, "0x1600", "0x01", "uint32"): 0x60400010,
            (0, "0x1600", "0x02", "uint32"): 0x607A0020,
            (0, "0x1600", "0x03", "uint32"): 0x60600008,
            (0, "0x1a00", "0x00", "uint8"): 3,
            (0, "0x1a00", "0x01", "uint32"): 0x60410010,
            (0, "0x1a00", "0x02", "uint32"): 0x60640020,
            (0, "0x1a00", "0x03", "uint32"): 0x60610008,
            (0, "0x6041", "0x00", "uint16"): 0x0231,
            (0, "0x6061", "0x00", "int8"): 8,
            (0, "0x6060", "0x00", "int8"): 8,
            (0, "0x6064", "0x00", "int32"): 123456,
            (0, "0x603f", "0x00", "uint16"): 0,
        }
        return table[key]

    def upload_optional(self, position, index, subindex, data_type):
        try:
            return {"ok": True, "value": self.upload(position, index, subindex, data_type)}
        except Exception as exc:  # pragma: no cover - interface compatibility
            return {"ok": False, "error": str(exc)}


def test_parse_ethercat_value_accepts_hex_and_decimal():
    assert parse_ethercat_value("0x00000231 561") == 561
    assert parse_ethercat_value("-42") == -42


def test_parse_mapping_entry_decodes_index_subindex_and_width():
    assert parse_mapping_entry(0x607A0020) == {
        "raw": "0x607A0020",
        "index": "0x607A",
        "subindex": 0,
        "bits": 32,
    }


def test_probe_slave_reads_assignments_pdos_and_ds402_snapshot(capsys):
    result = probe_slave(FakeRunner(), 0)

    assert result["slave"]["al_state"] == "PREOP"
    assert result["assignments"]["rxpdo"]["entries"] == ["0x1600"]
    assert result["assignments"]["txpdo"]["entries"] == ["0x1A00"]
    assert result["pdos"]["rxpdo"][0]["entries"][0]["index"] == "0x6040"
    assert result["pdos"]["txpdo"][0]["entries"][1]["index"] == "0x6064"
    assert result["ds402"]["status_word"]["hex"] == "0x0231"
    assert result["ds402"]["mode_display"]["value"] == 8
    events = capsys.readouterr().out.splitlines()
    assert any('"stage": "pdo_assignment_read"' in line for line in events)
