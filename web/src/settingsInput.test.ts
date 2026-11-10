import { expect, it } from "vitest";
import { parseCount, parseOptionalNumber, providerIdOk, urlOk } from "./settingsInput";

it("parses an optional number inside a range, empty meaning 'not set'", () => {
  expect(parseOptionalNumber("", 0, 2)).toEqual({ ok: true, value: null });
  expect(parseOptionalNumber("0.7", 0, 2)).toEqual({ ok: true, value: 0.7 });
  expect(parseOptionalNumber("2.5", 0, 2)).toEqual({ ok: false });
  expect(parseOptionalNumber("-1", 0, 2)).toEqual({ ok: false });
  expect(parseOptionalNumber("abc", 0, 2)).toEqual({ ok: false });
  expect(parseOptionalNumber("1e999", 0, 2)).toEqual({ ok: false });
});

it("parses whole numbers inside a range", () => {
  expect(parseCount("", 64, 32768)).toEqual({ ok: true, value: null });
  expect(parseCount("2048", 64, 32768)).toEqual({ ok: true, value: 2048 });
  expect(parseCount("10", 64, 32768)).toEqual({ ok: false });
  expect(parseCount("100.5", 64, 32768)).toEqual({ ok: false });
  expect(parseCount("99999", 64, 32768)).toEqual({ ok: false });
});

it("checks provider ids and addresses like the server does", () => {
  expect(providerIdOk("my-api")).toBe(true);
  expect(providerIdOk("")).toBe(true); // empty: the preset's id is used
  expect(providerIdOk("Bad Id")).toBe(false);
  expect(providerIdOk("-x")).toBe(false);
  expect(urlOk("http://127.0.0.1:8080/v1")).toBe(true);
  expect(urlOk("https://api.example.com/v1")).toBe(true);
  expect(urlOk("ftp://x")).toBe(false);
  expect(urlOk("")).toBe(false);
});
