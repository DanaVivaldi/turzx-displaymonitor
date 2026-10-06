"""The display driver without any hardware: rectangle diffing, block splitting, wire format."""
import numpy as np

from displaymonitor.display import CMD_BITMAP, HW_H, HW_W, Display, _header, rgb565


class FakeSerial:
    def __init__(self):
        self.chunks = []

    def write(self, data):
        self.chunks.append(bytes(data))

    def flush(self):
        pass


def decode_header(h: bytes):
    x = (h[0] << 2) | (h[1] >> 6)
    y = ((h[1] & 63) << 4) | (h[2] >> 4)
    ex = ((h[2] & 15) << 6) | (h[3] >> 2)
    ey = ((h[3] & 3) << 8) | h[4]
    return x, y, ex, ey, h[5]


def test_header_matches_the_documented_full_frame_command():
    # from the public Rev A protocol: DISPLAY_BITMAP over 480x320 is [0, 0, 7, 125, 63, 197]
    assert list(_header(CMD_BITMAP, 0, 0, 479, 319)) == [0, 0, 7, 125, 63, 197]


def test_header_roundtrip():
    for box in [(0, 0, 0, 0), (5, 7, 100, 200), (319, 479, 319, 479), (123, 321, 300, 479)]:
        assert decode_header(_header(CMD_BITMAP, *box)) == (*box, CMD_BITMAP)


def test_rgb565_little_endian():
    from PIL import Image
    im = Image.new("RGB", (2, 1))
    im.putpixel((0, 0), (255, 0, 0))
    im.putpixel((1, 0), (0, 255, 0))
    px = rgb565(im)
    assert px.dtype == np.dtype("<u2")
    assert px[0, 0] == 0xF800 and px[0, 1] == 0x07E0


def test_diff_of_identical_frames_is_empty():
    d = Display({})
    f = np.random.default_rng(1).integers(0, 65535, (HW_H, HW_W), dtype=np.uint16)
    assert d._diff(f, f.copy()) == []


def test_diff_rectangles_rebuild_the_new_frame():
    d = Display({})
    rng = np.random.default_rng(2)
    prev = rng.integers(0, 65535, (HW_H, HW_W), dtype=np.uint16)
    cur = prev.copy()
    cur[10:30, 5:100] = 1                 # a block
    cur[200, 17] = 2                      # a single pixel
    cur[400:480, 300:320] = 3             # touching the bottom-right corner
    out = prev.copy()
    for (x, y, w, h) in d._diff(prev, cur):
        assert 0 <= x and 0 <= y and x + w <= HW_W and y + h <= HW_H and w > 0 and h > 0
        out[y:y + h, x:x + w] = cur[y:y + h, x:x + w]
    assert np.array_equal(out, cur)


def test_rectangles_are_split_into_small_blocks():
    d = Display({"max_block_px": 12800})
    d._ser = FakeSerial()
    frame = np.random.default_rng(3).integers(0, 65535, (HW_H, HW_W), dtype=np.uint16)
    d._send_rect(frame, 0, 0, HW_W, HW_H)
    headers = d._ser.chunks[0::2]
    payloads = d._ser.chunks[1::2]
    assert len(headers) == len(payloads) > 1
    covered = 0
    for h, p in zip(headers, payloads):
        x, y, ex, ey, cmd = decode_header(h)
        w, hh = ex - x + 1, ey - y + 1
        assert cmd == CMD_BITMAP and w * hh <= 12800
        assert len(p) == w * hh * 2                      # exactly the pixels the header announces
        covered += w * hh
    assert covered == HW_W * HW_H


def test_show_rotates_landscape_into_portrait_and_sends_a_full_frame_first():
    d = Display({"rotate": 1, "refresh_band": 0})
    d._ser = FakeSerial()
    frame = np.zeros((320, 480), dtype=np.uint16)
    assert d.show(frame) is True
    total = sum(len(c) for c in d._ser.chunks[1::2])
    assert total == 320 * 480 * 2
    d._ser.chunks.clear()
    assert d.show(frame.copy()) is True                  # nothing changed: nothing sent
    assert d._ser.chunks == []


def test_brightness_is_a_percentage_and_the_firmware_scale_is_inverted():
    d = Display({"brightness": 100})
    assert d.brightness == 100 and d.raw_brightness() == 0          # 100 % -> raw 0 (brightest)
    d.set_brightness(0)
    assert d.raw_brightness() == 255                                # 0 % -> raw 255 (darkest)
    d.set_brightness(60)
    assert d.raw_brightness() == round(255 - 60 * 2.55)
    d.set_brightness(250)
    assert d.brightness == 100                                      # clamped
    assert Display({}).brightness == 100                            # default: brightest
