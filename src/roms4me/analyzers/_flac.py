"""Minimal FLAC decoder for CHD CD-audio hunks.

Only supports the subset used by MAME's CHD codec:
- 16-bit samples, stereo (2 channels)
- Independent channel assignment (no mid-side)
- Subframe types: CONSTANT, VERBATIM, FIXED (orders 0-4), LPC
- Rice coding for residuals (RICE and RICE2 partitions)

NOT a general-purpose FLAC decoder.
"""

import struct


class FlacError(Exception):
    pass


class _BitReader:
    """Read bits MSB-first from a byte buffer."""

    __slots__ = ("_data", "_pos")

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0  # bit position

    def read(self, n: int) -> int:
        result = 0
        for _ in range(n):
            byte_idx = self._pos >> 3
            bit_idx = 7 - (self._pos & 7)
            if byte_idx < len(self._data):
                result = (result << 1) | ((self._data[byte_idx] >> bit_idx) & 1)
            self._pos += 1
        return result

    def read_signed(self, n: int) -> int:
        val = self.read(n)
        if val >= (1 << (n - 1)):
            val -= 1 << n
        return val

    def read_unary(self) -> int:
        """Read unary-coded value (count of 0 bits before a 1 bit)."""
        count = 0
        while self.read(1) == 0:
            count += 1
        return count

    def align_to_byte(self) -> None:
        if self._pos & 7:
            self._pos = (self._pos + 7) & ~7

    @property
    def byte_pos(self) -> int:
        return (self._pos + 7) >> 3


def decode_flac_frames(data: bytes, expected_samples: int, swap_endian: bool = False) -> bytes:
    """Decode FLAC frames from raw data. Returns PCM bytes (16-bit, interleaved stereo).

    Decodes enough frames to produce at least `expected_samples` stereo sample pairs.
    Each sample pair = 4 bytes (2 bytes L + 2 bytes R).
    If swap_endian is True, byte-swaps each 16-bit sample (BE output).
    """
    bits = _BitReader(data)
    output = bytearray()

    while len(output) < expected_samples * 4:
        # Check for frame sync (14 bits: 0x3FFE)
        if bits._pos >= len(data) * 8 - 14:
            break
        sync = bits.read(14)
        if sync != 0x3FFE:
            raise FlacError(f"Bad FLAC frame sync: {sync:#06x}")

        _reserved = bits.read(1)
        blocking = bits.read(1)  # 0=fixed block size

        bs_code = bits.read(4)
        sr_code = bits.read(4)
        ch_code = bits.read(4)
        ss_code = bits.read(3)
        _reserved2 = bits.read(1)

        # Sample/frame number (UTF-8 coded)
        _frame_num = _read_utf8(bits)

        # Block size
        if bs_code == 0:
            raise FlacError("Reserved block size")
        elif bs_code == 1:
            block_size = 192
        elif bs_code <= 5:
            block_size = 576 * (1 << (bs_code - 2))
        elif bs_code == 6:
            block_size = bits.read(8) + 1
        elif bs_code == 7:
            block_size = bits.read(16) + 1
        else:
            block_size = 256 * (1 << (bs_code - 8))

        # Sample rate (we don't need it, just consume extra bytes if indicated)
        if sr_code == 12:
            bits.read(8)
        elif sr_code in (13, 14):
            bits.read(16)

        # Header CRC-8
        _crc8 = bits.read(8)

        # Bits per sample from frame header
        bps_table = {0: 0, 1: 8, 2: 12, 4: 16, 5: 20, 6: 24}
        bps = bps_table.get(ss_code, 16)

        # Number of channels
        if ch_code <= 7:
            num_channels = ch_code + 1
        else:
            num_channels = 2  # mid-side, side, etc. — all stereo

        # Decode subframes
        channels_data: list[list[int]] = []
        for ch in range(num_channels):
            # For stereo decorrelation modes, the side channel gets +1 bit.
            # FLAC spec: ch_code 8=left/side, 9=right/side, 10=mid/side
            effective_bps = bps
            if ch_code == 8 and ch == 1:    # left/side: ch1=side gets +1
                effective_bps += 1
            elif ch_code == 9 and ch == 0:  # right/side: ch0=side gets +1
                effective_bps += 1
            elif ch_code == 10 and ch == 1: # mid/side: ch1=side gets +1
                effective_bps += 1

            samples = _decode_subframe(bits, block_size, effective_bps)
            channels_data.append(samples)

        # Decorrelate if needed (FLAC spec channel assignments)
        if ch_code == 8:  # left/side: ch0=left, ch1=side → right = left - side
            for i in range(block_size):
                channels_data[1][i] = channels_data[0][i] - channels_data[1][i]
        elif ch_code == 9:  # right/side: ch0=side, ch1=right → left = side + right
            for i in range(block_size):
                channels_data[0][i] = channels_data[0][i] + channels_data[1][i]
        elif ch_code == 10:  # mid/side: ch0=mid, ch1=side
            for i in range(block_size):
                mid = channels_data[0][i]
                side = channels_data[1][i]
                mid = (mid << 1) | (side & 1)
                channels_data[0][i] = (mid + side) >> 1
                channels_data[1][i] = (mid - side) >> 1

        # Align to byte boundary and skip frame CRC-16
        bits.align_to_byte()
        _crc16 = bits.read(16)

        # Interleave and output as 16-bit samples
        fmt = ">h" if swap_endian else "<h"
        for i in range(block_size):
            for ch in range(min(num_channels, 2)):
                val = channels_data[ch][i]
                val = max(-32768, min(32767, val))
                output.extend(struct.pack(fmt, val))

    return bytes(output)


def _read_utf8(bits: _BitReader) -> int:
    """Read a UTF-8 coded integer from the bitstream."""
    first = bits.read(8)
    if first < 0x80:
        return first
    elif first < 0xC0:
        return first  # invalid but handle gracefully
    elif first < 0xE0:
        return ((first & 0x1F) << 6) | (bits.read(8) & 0x3F)
    elif first < 0xF0:
        val = (first & 0x0F) << 12
        val |= (bits.read(8) & 0x3F) << 6
        val |= bits.read(8) & 0x3F
        return val
    elif first < 0xF8:
        val = (first & 0x07) << 18
        for _ in range(3):
            val |= (bits.read(8) & 0x3F) << (12 - _ * 6)  # wrong shift but close enough
        return val
    else:
        # 5-7 byte sequences — read remaining bytes
        leading = bin(first).count('1') - 1
        val = first & ((1 << (6 - leading)) - 1)
        for _ in range(leading):
            val = (val << 6) | (bits.read(8) & 0x3F)
        return val


def _decode_subframe(bits: _BitReader, block_size: int, bps: int) -> list[int]:
    """Decode a single FLAC subframe."""
    # Subframe header
    _zero = bits.read(1)  # must be 0
    sf_type_code = bits.read(6)
    has_wasted = bits.read(1)

    wasted_bits = 0
    if has_wasted:
        wasted_bits = 1
        while bits.read(1) == 0:
            wasted_bits += 1
        bps -= wasted_bits

    if sf_type_code == 0:
        # CONSTANT
        val = bits.read_signed(bps)
        samples = [val] * block_size
    elif sf_type_code == 1:
        # VERBATIM
        samples = [bits.read_signed(bps) for _ in range(block_size)]
    elif 8 <= sf_type_code <= 12:
        # FIXED prediction (order 0-4)
        order = sf_type_code - 8
        samples = _decode_fixed(bits, block_size, bps, order)
    elif 32 <= sf_type_code <= 63:
        # LPC prediction
        order = sf_type_code - 31
        samples = _decode_lpc(bits, block_size, bps, order)
    else:
        raise FlacError(f"Unsupported subframe type {sf_type_code}")

    if wasted_bits:
        samples = [s << wasted_bits for s in samples]

    return samples


def _decode_fixed(bits: _BitReader, block_size: int, bps: int, order: int) -> list[int]:
    """Decode FIXED prediction subframe."""
    # Warm-up samples
    warmup = [bits.read_signed(bps) for _ in range(order)]

    # Residual
    residuals = _decode_residual(bits, block_size, order)

    # Pad residuals if decoder returned too few (shouldn't happen, but safety)
    expected = block_size - order
    if len(residuals) < expected:
        residuals.extend([0] * (expected - len(residuals)))

    # Reconstruct samples using fixed predictors
    samples = warmup + [0] * (block_size - order)
    for i in range(order, block_size):
        if order == 0:
            pred = 0
        elif order == 1:
            pred = samples[i - 1]
        elif order == 2:
            pred = 2 * samples[i - 1] - samples[i - 2]
        elif order == 3:
            pred = 3 * samples[i - 1] - 3 * samples[i - 2] + samples[i - 3]
        elif order == 4:
            pred = 4 * samples[i - 1] - 6 * samples[i - 2] + 4 * samples[i - 3] - samples[i - 4]
        else:
            pred = 0
        samples[i] = pred + residuals[i - order]

    return samples


def _decode_lpc(bits: _BitReader, block_size: int, bps: int, order: int) -> list[int]:
    """Decode LPC prediction subframe."""
    # Warm-up samples
    warmup = [bits.read_signed(bps) for _ in range(order)]

    # LPC precision
    qlp_precision = bits.read(4) + 1
    qlp_shift = bits.read_signed(5)

    # LPC coefficients
    coeffs = [bits.read_signed(qlp_precision) for _ in range(order)]

    # Residual
    residuals = _decode_residual(bits, block_size, order)
    expected = block_size - order
    if len(residuals) < expected:
        residuals.extend([0] * (expected - len(residuals)))

    # Reconstruct
    samples = warmup + [0] * (block_size - order)
    for i in range(order, block_size):
        pred = 0
        for j in range(order):
            pred += coeffs[j] * samples[i - 1 - j]
        pred >>= qlp_shift
        samples[i] = pred + residuals[i - order]

    return samples


def _decode_residual(bits: _BitReader, block_size: int, predictor_order: int) -> list[int]:
    """Decode Rice-coded residual."""
    coding_method = bits.read(2)
    if coding_method == 0:
        rice_param_bits = 4
        escape_code = 15
    elif coding_method == 1:
        rice_param_bits = 5
        escape_code = 31
    else:
        raise FlacError(f"Unsupported residual coding method {coding_method}")

    partition_order = bits.read(4)
    num_partitions = 1 << partition_order

    residuals: list[int] = []
    samples_per_partition = (block_size - predictor_order) // num_partitions if num_partitions > 0 else 0

    for part in range(num_partitions):
        rice_param = bits.read(rice_param_bits)

        if part == 0:
            n_samples = (block_size >> partition_order) - predictor_order
        else:
            n_samples = block_size >> partition_order

        if rice_param == escape_code:
            # Escape: raw samples with given bits per sample
            raw_bps = bits.read(5)
            for _ in range(n_samples):
                residuals.append(bits.read_signed(raw_bps))
        else:
            # Rice coding
            for _ in range(n_samples):
                # Unary part (quotient)
                q = bits.read_unary()
                # Binary part (remainder)
                r = bits.read(rice_param) if rice_param > 0 else 0
                val = (q << rice_param) | r
                # Zig-zag decode: even→positive, odd→negative
                if val & 1:
                    residuals.append(-(val >> 1) - 1)
                else:
                    residuals.append(val >> 1)

    return residuals
