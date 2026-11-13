"""Opt-in synthetic vision benchmark; never reads or operates a business screen."""
import argparse
import json
import struct
import time
import zlib
import codebuddy_bridge


def test_image():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    rows = b''.join(b'\0' + b''.join(bytes((220, 30, 30) if 240 <= x < 360 and 160 <= y < 240 else (255, 255, 255)) for x in range(400)) for y in range(300))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 400, 300, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')


def benchmark(models, repeats=3, timeout=45):
    records = []
    image = test_image()
    for model in models:
        for trial in range(repeats):
            started = time.monotonic()
            row = {'model': model, 'trial': trial + 1}
            try:
                reply = codebuddy_bridge.ask('Locate the red rectangle. Image is 400x300 pixels. Return only JSON {"x":pixel_center_x,"y":pixel_center_y}. Absolute pixels. Do not use tools.', model=model, timeout=timeout, ui_fast=True, images=[image])
                point = codebuddy_bridge.parse_json(reply)
                x, y = point.get('x'), point.get('y')
                row['correct'] = (type(x) in (int, float) and type(y) in (int, float) and abs(x - 300) <= 10 and abs(y - 200) <= 10)
            except ValueError:
                row.update(correct=False, error='request_or_output_failed')
            row['seconds'] = round(time.monotonic() - started, 3)
            records.append(row)
            print(json.dumps(row), flush=True)
    return records


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', nargs='+', default=['hy4std'])
    parser.add_argument('--repeats', type=int, choices=range(1, 11), default=3)
    parser.add_argument('--timeout', type=int, choices=range(1, 181), default=45)
    args = parser.parse_args()
    benchmark(args.models, args.repeats, args.timeout)
