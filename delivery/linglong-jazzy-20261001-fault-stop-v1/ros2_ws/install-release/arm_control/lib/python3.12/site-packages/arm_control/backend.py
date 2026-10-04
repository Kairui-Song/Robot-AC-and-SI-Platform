"""Small, ROS-independent adapter to the existing EtherCAT CLI protocol.

Object indices and slave positions match controller/ethercat_left_arm_test.py.
This is a low-rate SDO demonstration, not a real-time CSP/PDO controller.
"""
import math
import re
import subprocess
from dataclasses import dataclass

NAMES = ('joint_1', 'joint_2', 'joint_3', 'joint_5')
SLAVES = (1, 2, 3, 5)


@dataclass
class Calibration:
    scales: list  # signed encoder counts per output-joint radian
    zeros: list
    lower: list
    upper: list

    def __post_init__(self):
        arrays = (self.scales, self.zeros, self.lower, self.upper)
        if any(len(a) != 4 for a in arrays):
            raise ValueError('Calibration arrays must each contain four values')
        if not all(math.isfinite(v) for a in arrays for v in a):
            raise ValueError('Calibration must be finite')
        if any(s == 0 for s in self.scales):
            raise ValueError('Set nonzero signed counts_per_radian for all joints')
        if any(lo >= hi for lo, hi in zip(self.lower, self.upper)):
            raise ValueError('Every lower limit must be below its upper limit')
        for i in range(4):
            self.encode(i, self.lower[i])
            self.encode(i, self.upper[i])

    def encode(self, i, radians):
        value = round(self.zeros[i] + radians * self.scales[i])
        if not -(2**31) <= value < 2**31:
            raise ValueError('Target exceeds int32 encoder range')
        return value

    def decode(self, i, counts):
        return (counts - self.zeros[i]) / self.scales[i]


def validate_command(names, positions, current, calibration, max_step):
    """Validate the complete command before any drive write; reorder by name."""
    if len(names) != 4 or set(names) != set(NAMES) or len(positions) != 4:
        raise ValueError('Command must contain each of joint_1/2/3/5 exactly once')
    values = dict(zip(names, positions))
    ordered = [values[n] for n in NAMES]
    for i, value in enumerate(ordered):
        if not math.isfinite(value):
            raise ValueError('Position must be finite')
        if not calibration.lower[i] <= value <= calibration.upper[i]:
            raise ValueError(f'{NAMES[i]} outside configured joint limits')
        if abs(value - current[i]) > max_step:
            raise ValueError(f'{NAMES[i]} step exceeds max_step_rad')
        calibration.encode(i, value)
    return ordered


def parse_value(output):
    # IgH prints e.g. "0xfffffff6 -10"; take the final signed value.
    token = output.strip().split()[-1:]
    if not token or not re.fullmatch(r'-?(?:0x[0-9a-fA-F]+|\d+)', token[0]):
        raise RuntimeError(f'Invalid EtherCAT response: {output!r}')
    value = int(token[0], 16 if '0x' in token[0] else 10)
    return value


class EthercatBackend:
    def __init__(self, calibration, executable='ethercat', master=0, timeout=0.5):
        self.calibration = calibration
        self.executable, self.master, self.timeout = executable, master, timeout

    def run(self, *args):
        result = subprocess.run(
            [self.executable, '-m', str(self.master), *map(str, args)],
            capture_output=True, text=True, timeout=self.timeout, check=False,
        )
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout).strip())
        return result.stdout

    def upload(self, slave, index, dtype):
        value = parse_value(self.run('upload', '-p', slave, index, '0x00', '-t', dtype))
        if dtype == 'int32' and 2**31 <= value < 2**32:
            value -= 2**32
        return value

    def download(self, slave, index, dtype, value):
        self.run('download', '-p', slave, index, '0x00', '-t', dtype, value)

    def check_ready(self):
        # No automatic reset/enable: a separate field commissioning step owns that.
        for slave in SLAVES:
            status = self.upload(slave, '0x6041', 'uint16')
            mode = self.upload(slave, '0x6061', 'int8')
            if status & 0x006F != 0x0027 or mode != 8:
                raise RuntimeError(f'Slave {slave} must already be enabled in CSP mode')

    def read(self):
        return [self.calibration.decode(i, self.upload(s, '0x6064', 'int32'))
                for i, s in enumerate(SLAVES)]

    def write(self, positions):
        counts = [self.calibration.encode(i, p) for i, p in enumerate(positions)]
        for slave, value in zip(SLAVES, counts):
            self.download(slave, '0x607a', 'int32', value)

    def stop(self):
        errors = []
        for slave in SLAVES:
            try:
                self.download(slave, '0x6040', 'uint16', 0)
            except Exception as exc:
                errors.append(f'p{slave}: {exc}')
        if errors:
            raise RuntimeError('; '.join(errors))


class MockBackend:
    """Instantaneous simulated positions, never presented as hardware feedback."""
    def __init__(self):
        self.positions = [0.0] * 4

    def check_ready(self):
        pass

    def read(self):
        return self.positions.copy()

    def write(self, positions):
        self.positions = list(positions)

    def stop(self):
        pass
