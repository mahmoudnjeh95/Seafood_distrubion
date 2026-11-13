import { expect, test } from "vitest";

import { encodeWav, RECOGNITION_RATE } from "./speech";

test("a WAV file is 16-bit mono PCM at the recognition rate, samples clamped", () => {
  const wav = new DataView(encodeWav(new Float32Array([0, 1, -1, 2])));
  const text = (offset: number, length: number) =>
    String.fromCharCode(...Array.from({ length }, (_, index) => wav.getUint8(offset + index)));
  expect(text(0, 4)).toBe("RIFF");
  expect(text(8, 4)).toBe("WAVE");
  expect(wav.getUint16(20, true)).toBe(1);
  expect(wav.getUint16(22, true)).toBe(1);
  expect(wav.getUint32(24, true)).toBe(RECOGNITION_RATE);
  expect(wav.getUint16(34, true)).toBe(16);
  expect(wav.getUint32(40, true)).toBe(8);
  expect(wav.byteLength).toBe(52);
  expect(wav.getInt16(44, true)).toBe(0);
  expect(wav.getInt16(46, true)).toBe(0x7fff);
  expect(wav.getInt16(48, true)).toBe(-0x8000);
  expect(wav.getInt16(50, true)).toBe(0x7fff);
});
