import assert from "node:assert/strict";
import test from "node:test";
import {
  HttpError,
  requireInteger,
  validateDocumentUpload,
  validateSpreadsheetUpload,
} from "../src/validation.js";

test("validates positive numeric route identifiers", () => {
  assert.equal(requireInteger("12", "Conversa"), 12);
  assert.throws(() => requireInteger("0", "Conversa"), HttpError);
  assert.throws(() => requireInteger("1e2", "Conversa"), HttpError);
});

test("accepts a small Portuguese TXT upload and returns decoded bytes", () => {
  const uploaded = validateDocumentUpload("anotação.txt", Buffer.from("conteúdo").toString("base64"));
  assert.equal(uploaded.name, "anotação.txt");
  assert.equal(uploaded.content.toString("utf8"), "conteúdo");
});

test("rejects unsafe names, unsupported types, and malformed content", () => {
  for (const [filename, body] of [
    ["../fora.txt", "YQ=="],
    ["C:\\fora.txt", "YQ=="],
    [".env", "YQ=="],
    ["arquivo.exe", "YQ=="],
    ["arquivo.txt", "not-base64!"],
  ]) {
    assert.throws(() => validateDocumentUpload(filename, body), HttpError);
  }
});

test("validates CSV/XLSX uploads with the same path and size limits", () => {
  const uploaded = validateSpreadsheetUpload("dados.csv", Buffer.from("a,b").toString("base64"));
  assert.equal(uploaded.name, "dados.csv");
  assert.equal(uploaded.content.toString("utf8"), "a,b");
  assert.throws(() => validateSpreadsheetUpload("..\\outside.xlsx", "eA=="), HttpError);
  assert.throws(() => validateSpreadsheetUpload("planilha.xlsm", "eA=="), HttpError);
});
