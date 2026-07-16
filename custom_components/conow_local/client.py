"""CONOW Balcony Solar Storage — Modbus RTU client."""

from __future__ import annotations

import logging
import struct
import time
from typing import Any

from pymodbus.client import ModbusSerialClient
from pymodbus.exceptions import ModbusException

from .register_map import (
    CONTROL_COUNT,
    CONTROL_REGISTERS,
    CONTROL_START,
    DEFAULT_BAUDRATE,
    DEFAULT_SLAVE,
    DIRECTION_FORCE_CHARGE,
    DIRECTION_FORCE_DISCHARGE,
    DIRECTION_IDLE,
    MONITORING_COUNT,
    MONITORING_REGISTERS,
    MONITORING_START,
    REGISTERS_BY_ADDRESS,
    REGISTERS_BY_NAME,
    SYSTEM_STATUS_BITS,
    RegisterDef,
    get_force_mode_sequence,
)

_LOGGER = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_INTERVAL_S = 0.5
INTER_FRAME_DELAY_S = 0.15
POST_WRITE_DELAY_S = 0.3
DEFAULT_TIMEOUT_S = 2.0


def _crc16_modbus(data: bytes) -> int:
    """Compute Modbus RTU CRC-16."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def _build_rtu_frame(slave: int, function_code: int, payload: bytes) -> bytes:
    """Build a Modbus RTU frame (PDU + CRC, little-endian CRC)."""
    pdu = bytes([slave & 0xFF, function_code & 0xFF]) + payload
    crc = _crc16_modbus(pdu)
    return pdu + struct.pack("<H", crc)


def _format_rtu_hex(frame: bytes) -> str:
    """Format RTU bytes as upper-case hex groups."""
    return " ".join(f"{b:02X}" for b in frame)


def _read_holding_request_frame(slave: int, address: int, count: int) -> bytes:
    """Build FC 0x03 read holding registers request frame."""
    payload = struct.pack(">HH", address, count)
    return _build_rtu_frame(slave, 0x03, payload)


def _read_holding_response_frame(slave: int, registers: list[int]) -> bytes:
    """Build FC 0x03 read holding registers response frame (for logging)."""
    payload = bytes([len(registers) * 2 & 0xFF])
    for value in registers:
        payload += struct.pack(">H", value & 0xFFFF)
    return _build_rtu_frame(slave, 0x03, payload)


def _write_register_request_frame(slave: int, address: int, value: int) -> bytes:
    """Build FC 0x06 write single register request frame."""
    payload = struct.pack(">HH", address, value & 0xFFFF)
    return _build_rtu_frame(slave, 0x06, payload)


class ConowModbusError(Exception):
    """Raised when Modbus communication fails."""


class ConowModbusClient:
    """Local Modbus RTU client for CONOW balcony solar storage devices."""

    def __init__(
        self,
        port: str,
        *,
        slave: int = DEFAULT_SLAVE,
        baudrate: int = DEFAULT_BAUDRATE,
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        """Initialize serial Modbus client (38400 8N1 by default)."""
        self._slave = slave
        self._port = port
        self._client = ModbusSerialClient(
            port=port,
            framer="rtu",
            baudrate=baudrate,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=timeout,
            retries=0,
        )

    def connect(self) -> None:
        """Open the serial connection."""
        if not self._client.connect():
            raise ConowModbusError(f"Failed to open serial port {self._port}")
        self._flush_input_buffer()

    def _flush_input_buffer(self) -> None:
        """Discard stale bytes before the next Modbus frame."""
        serial_port = getattr(self._client, "socket", None)
        if serial_port is not None and hasattr(serial_port, "reset_input_buffer"):
            serial_port.reset_input_buffer()

    def _reconnect_after_error(self) -> None:
        """Close and reopen serial after I/O failure."""
        self._client.close()
        time.sleep(RETRY_INTERVAL_S)
        if not self._client.connect():
            raise ConowModbusError(f"Failed to reopen serial port {self._port}")
        self._flush_input_buffer()

    def close(self) -> None:
        """Close the serial connection."""
        self._client.close()

    def __enter__(self) -> ConowModbusClient:
        """Connect on context entry."""
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        """Disconnect on context exit."""
        self.close()

    def read_holding_registers(self, address: int, count: int) -> list[int]:
        """Read holding registers (FC 0x03) with retry."""
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._flush_input_buffer()
                tx_frame = _read_holding_request_frame(self._slave, address, count)
                _LOGGER.debug(
                    "Modbus read TX (FC 0x03): %s",
                    _format_rtu_hex(tx_frame),
                )
                response = self._client.read_holding_registers(
                    address,
                    count=count,
                    device_id=self._slave,
                )
                if response is None:
                    raise ConowModbusError("No response from device")
                if response.isError():
                    raise ConowModbusError(str(response))
                registers = list(response.registers)
                rx_frame = _read_holding_response_frame(self._slave, registers)
                _LOGGER.debug(
                    "Modbus read OK addr=%s count=%s RX=%s registers=%s",
                    address,
                    count,
                    _format_rtu_hex(rx_frame),
                    registers,
                )
                return registers
            except (ModbusException, ConowModbusError) as exc:
                last_error = exc
                _LOGGER.debug(
                    "Read failed (attempt %s/%s) addr=%s: %s",
                    attempt,
                    MAX_RETRIES,
                    address,
                    exc,
                )
                if attempt < MAX_RETRIES:
                    self._reconnect_after_error()
        msg = (
            f"Read failed after {MAX_RETRIES} attempts (slave={self._slave}, "
            f"port={self._port}): device sent no Modbus reply — check DIY Mode, "
            f"RS-485 wiring, and slave/baud (160 / 38400)"
        )
        raise ConowModbusError(msg) from last_error

    def write_register(self, address: int, value: int) -> None:
        """Write single holding register (FC 0x06) with retry."""
        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._flush_input_buffer()
                tx_frame = _write_register_request_frame(self._slave, address, value)
                _LOGGER.info(
                    "Modbus write TX (FC 0x06): %s",
                    _format_rtu_hex(tx_frame),
                )
                response = self._client.write_register(
                    address,
                    value,
                    device_id=self._slave,
                )
                if response is None:
                    raise ConowModbusError("No response from device")
                if response.isError():
                    raise ConowModbusError(str(response))
                # FC 0x06 normal response echoes the request PDU (8 bytes).
                _LOGGER.info(
                    "Modbus write OK: slave=%s addr=%s value=%s; expected RX echo: %s",
                    self._slave,
                    address,
                    value,
                    _format_rtu_hex(tx_frame),
                )
                return
            except (ModbusException, ConowModbusError) as exc:
                last_error = exc
                _LOGGER.debug(
                    "Write failed (attempt %s/%s) addr=%s: %s",
                    attempt,
                    MAX_RETRIES,
                    address,
                    exc,
                )
                if attempt < MAX_RETRIES:
                    self._reconnect_after_error()
        _LOGGER.error(
            "Modbus write failed: slave=%s port=%s addr=%s value=%s TX=%s err=%s",
            self._slave,
            self._port,
            address,
            value,
            _format_rtu_hex(_write_register_request_frame(self._slave, address, value)),
            last_error,
        )
        raise ConowModbusError(
            f"Write failed after {MAX_RETRIES} attempts: {last_error}"
        ) from last_error

    @staticmethod
    def decode_raw(dtype: str, registers: list[int], index: int) -> int:
        """Decode one field from a contiguous register block."""
        if dtype == "uint32":
            if index + 1 >= len(registers):
                raise ConowModbusError("uint32 decode out of range")
            high = registers[index]
            low = registers[index + 1]
            return (high << 16) | low
        raw = registers[index]
        if dtype == "int16":
            return struct.unpack(">h", struct.pack(">H", raw & 0xFFFF))[0]
        return raw

    @staticmethod
    def to_physical(defn: RegisterDef, raw: int) -> float:
        """Convert raw register value to physical quantity."""
        return (raw - defn.offset) * defn.scale

    @staticmethod
    def to_raw(defn: RegisterDef, physical: float) -> int:
        """Convert physical quantity to raw register value."""
        if defn.scale == 0:
            raise ConowModbusError(f"Invalid scale for {defn.name}")
        raw = round(physical / defn.scale + defn.offset)
        if defn.dtype == "int16" and not -32768 <= raw <= 32767:
            raise ConowModbusError(f"Value out of int16 range for {defn.name}: {raw}")
        if defn.dtype != "int16" and raw < 0:
            raise ConowModbusError(f"Value out of range for {defn.name}: {raw}")
        return int(raw) & 0xFFFF

    def decode_block(
        self, definitions: list[RegisterDef], block_start: int, registers: list[int]
    ) -> dict[str, Any]:
        """Decode a register block into named values."""
        result: dict[str, Any] = {}
        index = 0
        while index < len(registers):
            address = block_start + index
            defn = REGISTERS_BY_ADDRESS.get(address)
            if defn is None:
                index += 1
                continue
            raw = self.decode_raw(defn.dtype, registers, index)
            physical = self.to_physical(defn, raw)
            entry: dict[str, Any] = {
                "address": defn.address,
                "raw": raw,
                "value": physical,
                "unit": defn.unit,
            }
            if defn.decode == "bitmask":
                entry["bits"] = decode_system_status(raw)
            result[defn.name] = entry
            index += defn.register_count
        return result

    def read_monitoring(self) -> dict[str, Any]:
        """Read real-time status block (registers 10000–10036)."""
        registers = self.read_holding_registers(MONITORING_START, MONITORING_COUNT)
        return self.decode_block(MONITORING_REGISTERS, MONITORING_START, registers)

    def read_control(self) -> dict[str, Any]:
        """Read parameter / control block (registers 10100–10107)."""
        registers = self.read_holding_registers(CONTROL_START, CONTROL_COUNT)
        return self.decode_block(CONTROL_REGISTERS, CONTROL_START, registers)

    def read_all(self) -> dict[str, Any]:
        """Read monitoring and control blocks."""
        monitoring = self.read_monitoring()
        time.sleep(INTER_FRAME_DELAY_S)
        control = self.read_control()
        return {
            "monitoring": monitoring,
            "control": control,
        }

    def write_named_register_raw(self, name: str, raw_value: int) -> None:
        """Write a single control register using raw Modbus integer."""
        defn = REGISTERS_BY_NAME.get(name)
        if defn is None:
            raise ConowModbusError(f"Unknown register name: {name}")
        if not defn.writable:
            raise ConowModbusError(f"Register {name} is read-only")
        _LOGGER.info(
            "Control write %s: addr=%s raw=%s",
            name,
            defn.address,
            raw_value,
        )
        self.write_register(defn.address, raw_value)

    def write_named_register(self, name: str, physical_value: float) -> None:
        """Write a single control register by physical value."""
        defn = REGISTERS_BY_NAME.get(name)
        if defn is None:
            raise ConowModbusError(f"Unknown register name: {name}")
        if not defn.writable:
            raise ConowModbusError(f"Register {name} is read-only")
        raw = self.to_raw(defn, physical_value)
        _LOGGER.info(
            "Control write %s: addr=%s physical=%s raw=%s",
            name,
            defn.address,
            physical_value,
            raw,
        )
        self.write_register(defn.address, raw)

    def write_force_mode(self, direction: int, power_w: int, cutoff_soc: int) -> None:
        """Write forced charge/discharge or idle using registers.json sequence."""
        valid_directions = {
            DIRECTION_IDLE,
            DIRECTION_FORCE_CHARGE,
            DIRECTION_FORCE_DISCHARGE,
        }
        if direction not in valid_directions:
            raise ConowModbusError(f"Invalid direction: {direction}")
        if not 0 <= cutoff_soc <= 100:
            raise ConowModbusError("cutoff_soc must be 0–100")
        if power_w < 0:
            raise ConowModbusError("power_w must be >= 0")

        sequence = get_force_mode_sequence()
        if direction == DIRECTION_IDLE:
            idle_reg = REGISTERS_BY_NAME[sequence.idle_register]
            _LOGGER.info(
                "Force mode idle: write addr=%s value=%s",
                idle_reg.address,
                sequence.idle_value,
            )
            self.write_register(idle_reg.address, sequence.idle_value)
            return

        values_by_name = {
            sequence.register_names[0]: power_w,
            sequence.register_names[1]: direction,
            sequence.register_names[2]: cutoff_soc,
        }
        _LOGGER.info(
            "Force mode sequence: power=%s direction=%s cutoff_soc=%s (addrs %s)",
            power_w,
            direction,
            cutoff_soc,
            "→".join(str(REGISTERS_BY_NAME[name].address) for name in sequence.register_names),
        )
        for name in sequence.register_names:
            register = REGISTERS_BY_NAME[name]
            self.write_register(register.address, values_by_name[name])


def decode_system_status(raw: int) -> dict[str, bool]:
    """Parse system status bitmask (register 10000)."""
    return {
        label: bool(raw & (1 << bit))
        for bit, label in SYSTEM_STATUS_BITS.items()
    }


def probe_connection(port: str, slave: int, baudrate: int) -> None:
    """Verify Modbus connectivity by reading battery SOC."""
    soc_address = REGISTERS_BY_NAME["battery_soc"].address
    with ConowModbusClient(port, slave=slave, baudrate=baudrate) as client:
        client.read_holding_registers(soc_address, 1)
