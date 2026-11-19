export class HttpError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export function requireInteger(value: unknown, name: string): number {
  if (typeof value !== "string" || !/^[1-9]\d*$/.test(value)) {
    throw new HttpError(`${name} inválido.`, 400);
  }
  return Number(value);
}

export function validateDocumentUpload(filename: unknown, contentBase64: unknown) {
  if (typeof filename !== "string" || typeof contentBase64 !== "string") {
    throw new HttpError("Envie um arquivo TXT ou PDF.", 400);
  }
  const normalized = filename.replace(/\\/g, "/");
  const name = normalized.slice(normalized.lastIndexOf("/") + 1);
  if (
    normalized !== name
    || name === "."
    || name === ".."
    || name.length > 150
    || !/^[\p{L}\p{N} ._-]+\.(txt|pdf)$/iu.test(name)
    || contentBase64.length > 28_000_000
    || !/^[A-Za-z0-9+/]*={0,2}$/.test(contentBase64)
  ) {
    throw new HttpError("Nome ou conteúdo do arquivo inválido. Use TXT ou PDF.", 400);
  }
  const content = Buffer.from(contentBase64, "base64");
  if (content.length === 0 || content.length > 20 * 1024 * 1024) {
    throw new HttpError("O arquivo deve ter entre 1 byte e 20 MB.", 400);
  }
  return { name, content };
}

export function validateSpreadsheetUpload(filename: unknown, contentBase64: unknown) {
  if (typeof filename !== "string" || typeof contentBase64 !== "string") {
    throw new HttpError("Envie um arquivo CSV ou XLSX.", 400);
  }
  const normalized = filename.replace(/\\/g, "/");
  const name = normalized.slice(normalized.lastIndexOf("/") + 1);
  if (
    normalized !== name
    || name === "."
    || name === ".."
    || name.length > 150
    || !/^[\p{L}\p{N} ._-]+\.(csv|xlsx)$/iu.test(name)
    || contentBase64.length > 28_000_000
    || !/^[A-Za-z0-9+/]*={0,2}$/.test(contentBase64)
  ) {
    throw new HttpError("Nome ou conteúdo inválido. Use CSV ou XLSX.", 400);
  }
  const content = Buffer.from(contentBase64, "base64");
  if (content.length === 0 || content.length > 20 * 1024 * 1024) {
    throw new HttpError("A planilha deve ter entre 1 byte e 20 MB.", 400);
  }
  return { name, content };
}
