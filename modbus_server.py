import argparse
import configparser
import csv
import logging
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

# pymodbus library is used as Modbus TCP server (slave) that serves the registers from the tag file
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext, ModbusSlaveContext
from pymodbus.device import ModbusDeviceIdentification
from pymodbus.server import StartTcpServer

DEFAULT_CONFIG_FILE = "/app/modbus_server_config.ini"

# Modbus data tables
COILS = "co"
DISCRETE_INPUTS = "di"
HOLDING_REGISTERS = "hr"
INPUT_REGISTERS = "ir"

TABLE_NAMES = {
    COILS: "coil",
    DISCRETE_INPUTS: "discrete input",
    HOLDING_REGISTERS: "holding register",
    INPUT_REGISTERS: "input register",
}

# Function code a client uses for a tag -> data table the server serves it from
FUNCTION_CODE_TABLES = {
    1: COILS,               # read coils
    5: COILS,               # write single coil
    15: COILS,              # write multiple coils
    2: DISCRETE_INPUTS,     # read discrete inputs
    3: HOLDING_REGISTERS,   # read holding registers
    6: HOLDING_REGISTERS,   # write single register
    16: HOLDING_REGISTERS,  # write multiple registers
    4: INPUT_REGISTERS,     # read input registers
}

BIT_TABLES = {COILS, DISCRETE_INPUTS}

# Number of 16-bit registers and struct format per data type
DATA_TYPES = {
    "int16": (1, "h"),
    "uint16": (1, "H"),
    "int32": (2, "i"),
    "uint32": (2, "I"),
    "float32": (2, "f"),
    "int64": (4, "q"),
    "uint64": (4, "Q"),
    "float64": (4, "d"),
    "bool": (1, None),
}

# FC6 writes exactly one 16-bit register
FC6_DATA_TYPES = {"int16", "uint16"}

# Every data table covers the full Modbus address range 0..65535
TABLE_SIZE = 65536


@dataclass
class TagEntry:
    name: str
    unit_id: int
    function_code: int
    address: int
    data_type: str
    scale: float
    offset: float
    unit: str
    value: float

    @property
    def table(self) -> str:
        return FUNCTION_CODE_TABLES[self.function_code]

    @property
    def count(self) -> int:
        return DATA_TYPES[self.data_type][0]


@dataclass
class Settings:
    log_level: str
    tag_file: Path

    host: str
    port: int
    unit_id: int
    word_order: str
    byte_order: str


def parse_args():
    parser = argparse.ArgumentParser(description="Modbus TCP server serving the registers from a tag file")
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_FILE,
        help=f"Parameter file (default: {DEFAULT_CONFIG_FILE})",
    )
    return parser.parse_args()


def load_settings(config_file: str) -> Settings:
    path = Path(config_file)

    if not path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_file}")

    cfg = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(";", "#"))
    cfg.read(path, encoding="utf-8-sig")

    for section in ("general", "modbus"):
        if not cfg.has_section(section):
            raise ValueError(f"Config file is missing section [{section}]")

    general = cfg["general"]
    modbus = cfg["modbus"]

    tag_file = Path(general.get("tag_file", "modbus_tags.csv"))
    if not tag_file.is_absolute():
        tag_file = path.parent / tag_file

    settings = Settings(
        log_level=general.get("log_level", "INFO").upper(),
        tag_file=tag_file,
        host=modbus.get("host", "0.0.0.0").strip() or "0.0.0.0",
        port=modbus.getint("port", 502),
        unit_id=modbus.getint("unit_id", 1),
        word_order=modbus.get("word_order", "big").strip().lower(),
        byte_order=modbus.get("byte_order", "big").strip().lower(),
    )

    if not 1 <= settings.port <= 65535:
        raise ValueError("[modbus] port must be between 1 and 65535")
    if not 0 <= settings.unit_id <= 255:
        raise ValueError("[modbus] unit_id must be between 0 and 255")
    if settings.word_order not in ("big", "little"):
        raise ValueError("[modbus] word_order must be 'big' or 'little'")
    if settings.byte_order not in ("big", "little"):
        raise ValueError("[modbus] byte_order must be 'big' or 'little'")

    return settings


def setup_logging(level: str):
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return logging.getLogger("modbus_server")


def load_tag_map(tag_file: Path, default_unit_id: int) -> List[TagEntry]:
    if not tag_file.is_file():
        raise FileNotFoundError(f"Tag file not found: {tag_file}")

    tag_map: List[TagEntry] = []
    used_names = set()
    supported_fcs = sorted(FUNCTION_CODE_TABLES)

    with tag_file.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        required_columns = {"name", "function_code", "address", "data_type"}
        if reader.fieldnames is None:
            raise ValueError("Tag file is empty or missing header")
        if not required_columns.issubset(set(reader.fieldnames)):
            raise ValueError(
                f"Tag file must contain at least columns: {', '.join(sorted(required_columns))}"
            )

        for line_no, row in enumerate(reader, start=2):
            try:
                name = (row.get("name") or "").strip()
                if not name or name.startswith("#"):
                    continue  # skip empty and commented rows

                unit_id_text = (row.get("unit_id") or "").strip()
                unit_id = int(unit_id_text) if unit_id_text else default_unit_id
                function_code = int(row["function_code"])
                address = int(row["address"])
                data_type = (row.get("data_type") or "").strip().lower()
                scale_text = (row.get("scale") or "").strip()
                offset_text = (row.get("offset") or "").strip()
                value_text = (row.get("value") or "").strip()
                scale = float(scale_text) if scale_text else 1.0
                offset = float(offset_text) if offset_text else 0.0
                unit = (row.get("unit") or "").strip()

                if name in used_names:
                    raise ValueError(f"duplicate name '{name}'")
                if function_code not in FUNCTION_CODE_TABLES:
                    raise ValueError(f"function_code must be one of: {', '.join(map(str, supported_fcs))}")
                if data_type not in DATA_TYPES:
                    raise ValueError(f"data_type must be one of: {', '.join(DATA_TYPES)}")
                if FUNCTION_CODE_TABLES[function_code] in BIT_TABLES and data_type != "bool":
                    raise ValueError("function codes 1, 2, 5 and 15 require data_type 'bool'")
                if function_code == 6 and data_type not in FC6_DATA_TYPES:
                    raise ValueError(f"function code 6 requires data_type {' or '.join(sorted(FC6_DATA_TYPES))}")
                if scale == 0:
                    raise ValueError("scale may not be 0")
                if address < 0 or address + DATA_TYPES[data_type][0] > TABLE_SIZE:
                    raise ValueError("address out of range 0..65535")
                if not 0 <= unit_id <= 255:
                    raise ValueError("unit_id must be between 0 and 255")

                if data_type == "bool":
                    value = value_text.lower() in ("1", "true", "on", "yes")
                else:
                    value = float(value_text) if value_text else 0.0

                used_names.add(name)
                tag_map.append(
                    TagEntry(name, unit_id, function_code, address, data_type, scale, offset, unit, value)
                )

            except Exception as exc:
                raise ValueError(f"Invalid row in tag file at line {line_no}: {row} ({exc})") from exc

    if not tag_map:
        raise ValueError("No tags found in tag file")

    return tag_map


def check_overlaps(tag_map: List[TagEntry], logger):
    owners: Dict[tuple, str] = {}
    for tag in tag_map:
        for address in range(tag.address, tag.address + tag.count):
            key = (tag.unit_id, tag.table, address)
            if key in owners:
                logger.warning(
                    "Tag %s overlaps tag %s at %s %d, unit %d",
                    tag.name, owners[key], TABLE_NAMES[tag.table], address, tag.unit_id,
                )
            else:
                owners[key] = tag.name


def swap_bytes(raw: bytes) -> bytes:
    return b"".join(raw[i + 1:i + 2] + raw[i:i + 1] for i in range(0, len(raw), 2))


def decode_registers(registers: List[int], data_type: str, word_order: str, byte_order: str):
    if data_type == "bool":
        return bool(registers[0])

    words = list(registers)
    if word_order == "little":
        words.reverse()

    raw = b"".join(struct.pack(">H", w) for w in words)
    if byte_order == "little":
        raw = swap_bytes(raw)

    return struct.unpack(">" + DATA_TYPES[data_type][1], raw)[0]


def encode_registers(value, data_type: str, word_order: str, byte_order: str) -> List[int]:
    raw = struct.pack(">" + DATA_TYPES[data_type][1], value)
    if byte_order == "little":
        raw = swap_bytes(raw)

    words = [struct.unpack(">H", raw[i:i + 2])[0] for i in range(0, len(raw), 2)]
    if word_order == "little":
        words.reverse()
    return words


def to_raw(tag: TagEntry):
    # Engineering value -> raw value (inverse of value = raw * scale + offset)
    raw = (tag.value - tag.offset) / tag.scale
    if tag.data_type.startswith("float"):
        return raw
    return round(raw)


def from_raw(tag: TagEntry, raw):
    if tag.data_type == "bool" or (tag.scale == 1.0 and tag.offset == 0.0):
        return raw
    return round(raw * tag.scale + tag.offset, 6)


class TagDataBlock(ModbusSequentialDataBlock):
    """Data table that logs the engineering value of the tags a client writes to."""

    def __init__(self, table: str, unit_id: int, tags: List[TagEntry], settings: Settings, logger):
        super().__init__(0, [False if table in BIT_TABLES else 0] * TABLE_SIZE)
        self.table = table
        self.unit_id = unit_id
        self.tags = tags
        self.settings = settings
        self.logger = logger

    def setValues(self, address, values):
        super().setValues(address, values)

        count = len(values) if isinstance(values, list) else 1
        for tag in self.tags:
            if tag.address < address + count and address < tag.address + tag.count:
                self.log_tag(tag)

    def log_tag(self, tag: TagEntry):
        registers = super().getValues(tag.address, tag.count)
        try:
            raw = decode_registers(registers, tag.data_type, self.settings.word_order, self.settings.byte_order)
        except struct.error as exc:
            self.logger.warning("Cannot decode %s: %s", tag.name, exc)
            return
        self.logger.info(
            "Write %-20s value=%s%s (raw %s) -> %s %d, unit %d",
            tag.name, from_raw(tag, raw), f" {tag.unit}" if tag.unit else "", raw,
            TABLE_NAMES[tag.table], tag.address, tag.unit_id,
        )


def build_context(settings: Settings, tag_map: List[TagEntry], logger) -> ModbusServerContext:
    slaves = {}
    for unit_id in sorted({tag.unit_id for tag in tag_map}):
        unit_tags = [tag for tag in tag_map if tag.unit_id == unit_id]
        blocks = {
            table: TagDataBlock(table, unit_id, [tag for tag in unit_tags if tag.table == table], settings, logger)
            for table in TABLE_NAMES
        }

        # Initial values; written to the parent class so they are not logged as client writes
        for tag in unit_tags:
            block = blocks[tag.table]
            if tag.data_type == "bool":
                registers = [bool(tag.value)]
            else:
                registers = encode_registers(to_raw(tag), tag.data_type, settings.word_order, settings.byte_order)
            ModbusSequentialDataBlock.setValues(block, tag.address, registers)
            logger.info(
                "Tag %-20s FC%-2d %s %d (%s), unit %d, initial value %s%s",
                tag.name, tag.function_code, TABLE_NAMES[tag.table], tag.address, tag.data_type,
                unit_id, tag.value, f" {tag.unit}" if tag.unit else "",
            )

        # zero_mode=True: address 0 in the tag file is register 0 on the wire (no +1 offset)
        slaves[unit_id] = ModbusSlaveContext(
            co=blocks[COILS],
            di=blocks[DISCRETE_INPUTS],
            hr=blocks[HOLDING_REGISTERS],
            ir=blocks[INPUT_REGISTERS],
            zero_mode=True,
        )

    return ModbusServerContext(slaves=slaves, single=False)


def main():
    args = parse_args()
    settings = load_settings(args.config)
    logger = setup_logging(settings.log_level)

    tag_map = load_tag_map(settings.tag_file, settings.unit_id)
    logger.info("Loaded %d tags from %s", len(tag_map), settings.tag_file)
    check_overlaps(tag_map, logger)

    context = build_context(settings, tag_map, logger)

    identity = ModbusDeviceIdentification()
    identity.VendorName = "docker-modbus-server"
    identity.ProductName = "Modbus TCP server"
    identity.ModelName = "modbus-server"

    unit_ids = ", ".join(str(uid) for uid in sorted({tag.unit_id for tag in tag_map}))
    logger.info("Starting Modbus TCP server on %s:%d (unit ids: %s)", settings.host, settings.port, unit_ids)
    try:
        StartTcpServer(context=context, identity=identity, address=(settings.host, settings.port))
    except KeyboardInterrupt:
        logger.info("Stopping server...")


if __name__ == "__main__":
    main()
