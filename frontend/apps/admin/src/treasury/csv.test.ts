import { expect, test } from "vitest";

import { csvFile, csvMoney } from "./csv";

const BOM = String.fromCharCode(0xfeff);

test("the file starts with a byte-order mark and ends each row with a line break", () => {
  expect(csvFile([["Client", "Net"]])).toBe(`${BOM}Client;Net\r\n`);
});

test("a cell holding a separator, a quote or a line break is quoted, its quotes doubled", () => {
  expect(csvFile([["Ben; Ali", 'il dit "oui"', "1\n2"]])).toBe(`${BOM}"Ben; Ali";"il dit ""oui""";"1\n2"\r\n`);
});

test("money reads with a French decimal comma", () => {
  expect(csvMoney("1200.500")).toBe("1200,500");
  expect(csvMoney("0.000")).toBe("0,000");
});
