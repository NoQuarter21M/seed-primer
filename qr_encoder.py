"""
qr_encoder.py -- from-scratch QR Code encoder, scoped to exactly what
entropy-mixer needs: byte-mode data, versions 2 and 3 only (25x25 and
29x29 modules), all four error-correction levels. No numeric/
alphanumeric/kanji modes, no other versions, no structured append, no
image-format writers -- just a boolean module matrix.

Implements ISO/IEC 18004 from the public specification: GF(256) Reed-
Solomon error correction, standard module placement (finder/timing/
alignment/format-info/dark-module), the 8 candidate data masks with
the spec's 4 penalty rules, mask selection by lowest penalty score.

GF(256) log/antilog tables are DERIVED from the primitive polynomial
(x^8 + x^4 + x^3 + x^2 + 1, i.e. 0x11D) rather than hand-transcribed,
for the same reason the secp256k1 Gy constant elsewhere in this
project is derived rather than typed: a wrong constant here would
silently corrupt every Reed-Solomon codeword.
"""

import itertools

# ---------------------------------------------------------------------------
# GF(256) arithmetic (Reed-Solomon field for QR codes)
# ---------------------------------------------------------------------------

_GF_PRIME = 0x11D  # x^8 + x^4 + x^3 + x^2 + 1, the QR spec's primitive poly

_GF_EXP = [0] * 512
_GF_LOG = [0] * 256


def _init_gf_tables():
    x = 1
    for i in range(255):
        _GF_EXP[i] = x
        _GF_LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= _GF_PRIME
    for i in range(255, 512):
        _GF_EXP[i] = _GF_EXP[i - 255]


_init_gf_tables()


def _gf_mul(a, b):
    if a == 0 or b == 0:
        return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _rs_generator_poly(n_ecc):
    """Generator polynomial for n_ecc error-correction codewords, as a
    list of coefficients, highest degree first (leading coeff always 1)."""
    poly = [1]
    for i in range(n_ecc):
        poly = _poly_mul(poly, [1, _GF_EXP[i]])
    return poly


def _poly_mul(p, q):
    result = [0] * (len(p) + len(q) - 1)
    for i, pc in enumerate(p):
        if pc == 0:
            continue
        for j, qc in enumerate(q):
            result[i + j] ^= _gf_mul(pc, qc)
    return result


def _rs_encode(data_codewords, n_ecc):
    """Returns the n_ecc Reed-Solomon error-correction codewords for the
    given data codewords (list of ints 0-255)."""
    gen = _rs_generator_poly(n_ecc)
    msg = list(data_codewords) + [0] * n_ecc
    for i in range(len(data_codewords)):
        coeff = msg[i]
        if coeff == 0:
            continue
        for j, gc in enumerate(gen):
            msg[i + j] ^= _gf_mul(gc, coeff)
    return msg[len(data_codewords):]


# ---------------------------------------------------------------------------
# Block structure (ISO/IEC 18004 Annex, byte-mode data + EC codewords)
# Each entry: version -> level -> list of (num_blocks, block_total_codewords,
# block_data_codewords). Only versions 2 and 3 are included -- this encoder
# is deliberately scoped to just what entropy-mixer needs.
# ---------------------------------------------------------------------------

_BLOCK_STRUCTURE = {
    2: {
        "l": [(1, 44, 34)], "m": [(1, 44, 28)],
        "q": [(1, 44, 22)], "h": [(1, 44, 16)],
    },
    3: {
        "l": [(1, 70, 55)], "m": [(1, 70, 44)],
        "q": [(2, 35, 17)], "h": [(2, 35, 13)],
    },
}

_ALIGNMENT_POS = {2: (6, 18), 3: (6, 22)}

_EC_LEVEL_BITS = {"l": 0b01, "m": 0b00, "q": 0b11, "h": 0b10}


def _total_data_codewords(version, level):
    return sum(nb * bd for nb, _, bd in _BLOCK_STRUCTURE[version][level])


def build_bitstream(data: bytes, version: int, level: str) -> list:
    """
    Builds the full codeword list (data + padding) for byte-mode encoding,
    per ISO/IEC 18004 8.4: mode indicator (4 bits, 0100 for byte mode),
    character count indicator (8 bits for versions 1-9), the data itself,
    a terminator (up to 4 zero bits), pad to a byte boundary, then pad
    with alternating 0xEC/0x11 codewords until capacity is reached.
    """
    n_data_codewords = _total_data_codewords(version, level)

    bits = []
    bits.extend([0, 1, 0, 0])  # byte mode indicator
    count = len(data)
    bits.extend([(count >> i) & 1 for i in range(7, -1, -1)])  # 8-bit count
    for byte in data:
        bits.extend([(byte >> i) & 1 for i in range(7, -1, -1)])

    capacity_bits = n_data_codewords * 8
    if len(bits) > capacity_bits:
        raise ValueError(
            f"{len(data)} bytes does not fit version {version} level "
            f"{level} ({n_data_codewords} data codewords)"
        )

    # terminator: up to 4 zero bits
    terminator_len = min(4, capacity_bits - len(bits))
    bits.extend([0] * terminator_len)

    # pad to byte boundary
    while len(bits) % 8 != 0:
        bits.append(0)

    codewords = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]

    # pad with alternating 0xEC, 0x11 until full
    pad_pattern = itertools.cycle([0xEC, 0x11])
    while len(codewords) < n_data_codewords:
        codewords.append(next(pad_pattern))

    return codewords


def build_final_codewords(data: bytes, version: int, level: str) -> list:
    """
    Splits the data codewords across blocks (per the ISO block-structure
    table), computes Reed-Solomon EC codewords for each block, then
    interleaves: all blocks' data codewords column-by-column, followed
    by all blocks' EC codewords column-by-column. For our two needed
    multi-block cases (version 3, levels Q and H) both blocks are
    exactly equal size, so no short/long block handling is needed --
    implemented generically regardless, per the general interleaving
    rule in ISO/IEC 18004 8.6.
    """
    all_data_codewords = build_bitstream(data, version, level)
    blocks_info = _BLOCK_STRUCTURE[version][level]

    data_blocks = []
    ec_blocks = []
    pos = 0
    for num_blocks, block_total, block_data in blocks_info:
        n_ecc = block_total - block_data
        for _ in range(num_blocks):
            block = all_data_codewords[pos:pos + block_data]
            pos += block_data
            data_blocks.append(block)
            ec_blocks.append(_rs_encode(block, n_ecc))

    max_data_len = max(len(b) for b in data_blocks)
    interleaved = []
    for i in range(max_data_len):
        for b in data_blocks:
            if i < len(b):
                interleaved.append(b[i])
    max_ec_len = max(len(b) for b in ec_blocks)
    for i in range(max_ec_len):
        for b in ec_blocks:
            if i < len(b):
                interleaved.append(b[i])

    return interleaved


# ---------------------------------------------------------------------------
# Module matrix construction
# ---------------------------------------------------------------------------

# Matrix values: True=dark, False=light, None=not yet assigned (data area)
_FINDER = [
    [1,1,1,1,1,1,1],
    [1,0,0,0,0,0,1],
    [1,0,1,1,1,0,1],
    [1,0,1,1,1,0,1],
    [1,0,1,1,1,0,1],
    [1,0,0,0,0,0,1],
    [1,1,1,1,1,1,1],
]

_ALIGNMENT_PATTERN = [
    [1,1,1,1,1],
    [1,0,0,0,1],
    [1,0,1,0,1],
    [1,0,0,0,1],
    [1,1,1,1,1],
]


def _size_for_version(version):
    return 4 * version + 17


def _new_matrix(size):
    return [[None] * size for _ in range(size)]


def _place_finder(matrix, reserved, top, left):
    size = len(matrix)
    for dr in range(-1, 8):
        for dc in range(-1, 8):
            r, c = top + dr, left + dc
            if 0 <= r < size and 0 <= c < size:
                if 0 <= dr < 7 and 0 <= dc < 7:
                    matrix[r][c] = bool(_FINDER[dr][dc])
                else:
                    matrix[r][c] = False  # separator (always light)
                reserved[r][c] = True


def _place_alignment(matrix, reserved, center_r, center_c):
    for dr in range(-2, 3):
        for dc in range(-2, 3):
            r, c = center_r + dr, center_c + dc
            matrix[r][c] = bool(_ALIGNMENT_PATTERN[dr + 2][dc + 2])
            reserved[r][c] = True


def _alignment_centers(version):
    positions = _ALIGNMENT_POS[version]
    size = _size_for_version(version)
    finder_zone = 8  # positions within this distance of a finder corner are skipped
    centers = []
    for r, c in itertools.product(positions, positions):
        if (r < finder_zone and c < finder_zone):
            continue
        if (r < finder_zone and c > size - finder_zone):
            continue
        if (r > size - finder_zone and c < finder_zone):
            continue
        centers.append((r, c))
    return centers


def _place_timing_patterns(matrix, reserved):
    size = len(matrix)
    for i in range(8, size - 8):
        val = (i % 2 == 0)
        if matrix[6][i] is None:
            matrix[6][i] = val
        reserved[6][i] = True
        if matrix[i][6] is None:
            matrix[i][6] = val
        reserved[i][6] = True


def _place_dark_module(matrix, reserved, version):
    r, c = 4 * version + 9, 8
    matrix[r][c] = True
    reserved[r][c] = True


def _reserve_format_info_areas(reserved):
    size = len(reserved)
    for i in range(9):
        reserved[8][i] = True
        reserved[i][8] = True
    for i in range(size - 8, size):
        reserved[8][i] = True
        reserved[i][8] = True


# BCH(15,5) generator for format information, per ISO/IEC 18004 Annex C.
_FORMAT_GEN = 0b10100110111  # x^10+x^8+x^5+x^4+x^2+x+1
_FORMAT_MASK = 0b101010000010010


def _bch_format_bits(data5):
    """data5: 5-bit value (2-bit EC level << 3 | 3-bit mask id).
    Returns the 15-bit format info value (5 data + 10 BCH ECC),
    XORed with the fixed spec mask."""
    value = data5 << 10
    g = _FORMAT_GEN
    for i in range(4, -1, -1):
        if value & (1 << (i + 10)):
            value ^= g << i
    full = (data5 << 10) | value
    return full ^ _FORMAT_MASK


def _place_format_info(matrix, version, level, mask_id):
    size = len(matrix)
    data5 = (_EC_LEVEL_BITS[level] << 3) | mask_id
    format_info = _bch_format_bits(data5)

    voffset = 0
    hoffset = 0
    for i in range(8):
        vbit = bool((format_info >> i) & 1)
        hbit = bool((format_info >> (14 - i)) & 1)
        if i == 6:
            voffset += 1
            hoffset = 1
        matrix[i + voffset][8] = vbit          # vertical, upper-left corner
        matrix[8][i + hoffset] = hbit          # horizontal, upper-left corner
        matrix[8][size - 1 - i] = vbit         # horizontal, upper-right corner
        matrix[size - 1 - i][8] = hbit         # vertical, bottom-left corner
    matrix[size - 8][8] = True                 # dark module


def _place_data(matrix, reserved, codewords):
    """
    Zigzag placement per ISO/IEC 18004 7.7.3: two-module-wide columns,
    right to left, starting bottom-right, moving upward then downward
    alternately, skipping column 6 (the vertical timing pattern).
    """
    size = len(matrix)
    bits = []
    for cw in codewords:
        bits.extend([(cw >> i) & 1 for i in range(7, -1, -1)])
    bit_idx = 0
    n_bits = len(bits)

    col = size - 1
    going_up = True
    while col > 0:
        if col == 6:
            col -= 1
            continue
        rows = range(size - 1, -1, -1) if going_up else range(size)
        for row in rows:
            for c in (col, col - 1):
                if not reserved[row][c]:
                    bit = bits[bit_idx] if bit_idx < n_bits else 0
                    matrix[row][c] = bool(bit)
                    bit_idx += 1
        going_up = not going_up
        col -= 2


# ---------------------------------------------------------------------------
# Masking (8 candidate patterns, ISO/IEC 18004 7.8, applied to data
# modules only) + penalty scoring (7.8.3) to pick the best one.
# ---------------------------------------------------------------------------

_MASK_FUNCS = [
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: (r // 2 + c // 3) % 2 == 0,
    lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
]


def _apply_mask(matrix, reserved, mask_id):
    size = len(matrix)
    result = [row[:] for row in matrix]
    f = _MASK_FUNCS[mask_id]
    for r in range(size):
        for c in range(size):
            if not reserved[r][c] and f(r, c):
                result[r][c] = not result[r][c]
    return result


def _penalty_score(matrix):
    size = len(matrix)
    score = 0

    # Rule 1: runs of 5+ same-color modules in a row/column
    for line_getter in (lambda i: matrix[i], lambda i: [matrix[r][i] for r in range(size)]):
        for i in range(size):
            line = line_getter(i)
            run = 1
            for k in range(1, size):
                if line[k] == line[k - 1]:
                    run += 1
                else:
                    if run >= 5:
                        score += 3 + (run - 5)
                    run = 1
            if run >= 5:
                score += 3 + (run - 5)

    # Rule 2: 2x2 blocks of same color
    for r in range(size - 1):
        for c in range(size - 1):
            v = matrix[r][c]
            if v == matrix[r][c + 1] == matrix[r + 1][c] == matrix[r + 1][c + 1]:
                score += 3

    # Rule 3: finder-like patterns (1:1:3:1:1 ratio with 4 light either side)
    pattern_dark_light = [True, False, True, True, True, False, True]
    pattern_light_dark = [False, True, False, False, False, True, False]

    def has_pattern(line):
        n = len(line)
        count = 0
        for start in range(n - 6):
            window = line[start:start + 7]
            if window == pattern_dark_light or window == pattern_light_dark:
                # need 4 light modules before or after per spec; approximate
                # via the standard 11-cell check when possible
                before_ok = start >= 4 and all(x is False for x in line[start - 4:start])
                after_ok = start + 7 + 4 <= n and all(x is False for x in line[start + 7:start + 11])
                if before_ok or after_ok:
                    count += 1
        return count

    for r in range(size):
        score += 40 * has_pattern(matrix[r])
    for c in range(size):
        score += 40 * has_pattern([matrix[r][c] for r in range(size)])

    # Rule 4: overall dark/light balance
    dark = sum(1 for row in matrix for v in row if v)
    total = size * size
    pct = dark * 100 // total
    lower = (pct // 5) * 5
    upper = lower + 5
    score += 10 * min(abs(lower - 50) // 5, abs(upper - 50) // 5)

    return score


def build_matrix(data: bytes, version: int, level: str):
    """Returns (matrix, mask_id) -- the final boolean module matrix and
    which of the 8 mask patterns was selected (lowest penalty score)."""
    size = _size_for_version(version)
    matrix = _new_matrix(size)
    reserved = [[False] * size for _ in range(size)]

    _place_finder(matrix, reserved, 0, 0)
    _place_finder(matrix, reserved, 0, size - 7)
    _place_finder(matrix, reserved, size - 7, 0)
    for r, c in _alignment_centers(version):
        _place_alignment(matrix, reserved, r, c)
    _place_timing_patterns(matrix, reserved)
    _place_dark_module(matrix, reserved, version)
    _reserve_format_info_areas(reserved)

    codewords = build_final_codewords(data, version, level)
    _place_data(matrix, reserved, codewords)

    best_mask = None
    best_score = None
    best_matrix = None
    for mask_id in range(8):
        candidate = _apply_mask(matrix, reserved, mask_id)
        _place_format_info(candidate, version, level, mask_id)
        score = _penalty_score(candidate)
        if best_score is None or score < best_score:
            best_score = score
            best_mask = mask_id
            best_matrix = candidate

    return best_matrix, best_mask
