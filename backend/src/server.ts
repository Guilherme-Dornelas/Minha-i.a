import "dotenv/config";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import express, { type NextFunction, type Request, type Response } from "express";
import {
  HttpError,
  requireInteger,
  validateDocumentUpload,
  validateSpreadsheetUpload,
} from "./validation.js";
import { GmailService, type GmailTokenStore } from "./gmail.js";
import { resolveChatProvider } from "./chatProvider.js";
import {
  createGeminiContentStream,
  GeminiApiError,
  GeminiConfigurationError,
} from "./gemini.js";

type WorkerResponse<T> = { ok: true; result: T } | { ok: false; error: string; status: number };
type WebSource = { title: string; url: string; description: string };
type GmailIntent = {
  action: string;
  query: string;
  messageId: string;
  maxResults: number;
};

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const OLLAMA_HOST = (process.env.OLLAMA_HOST ?? "http://127.0.0.1:11434").replace(/\/+$/, "");
const CHAT_MODEL = process.env.GUILHERME_AI_MODEL ?? "guilherme-ai";
const EMBED_MODEL = process.env.GUILHERME_AI_EMBED_MODEL ?? "nomic-embed-text";
const PORT = Number(process.env.GUILHERME_AI_PORT ?? 8000);
const MODEL_KEEP_ALIVE = process.env.GUILHERME_AI_MODEL_KEEP_ALIVE ?? "2m";
const MAX_MODEL_CONTEXT_TOKENS = Number(process.env.GUILHERME_AI_MAX_CONTEXT_TOKENS ?? 4096);
const pythonInVenv = path.join(
  ROOT,
  ".venv",
  process.platform === "win32" ? "Scripts" : "bin",
  process.platform === "win32" ? "python.exe" : "python",
);
const pythonExecutable = process.env.GUILHERME_AI_PYTHON
  ?? (existsSync(pythonInVenv) ? pythonInVenv : "python");

const app = express();
app.disable("x-powered-by");
app.use(express.json({ limit: "28mb" }));

app.use((request, response, next) => {
  const origin = request.get("origin");
  if (origin) {
    const allowed = new Set([
      `http://127.0.0.1:${PORT}`,
      `http://localhost:${PORT}`,
      "http://127.0.0.1:5173",
      "http://localhost:5173",
    ]);
    if (!allowed.has(origin)) {
      response.status(403).json({ error: "Origem não autorizada." });
      return;
    }
  }
  next();
});

function worker<T>(payload: Record<string, unknown>): Promise<T> {
  return new Promise((resolve, reject) => {
    const workerEnvironment = { ...process.env };
    delete workerEnvironment.GEMINI_API_KEY;
    const child = spawn(pythonExecutable, ["-m", "guilherme_ai.web_worker"], {
      cwd: ROOT,
      env: workerEnvironment,
      windowsHide: true,
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8").on("data", (chunk: string) => {
      stdout += chunk;
    });
    child.stderr.setEncoding("utf8").on("data", (chunk: string) => {
      stderr += chunk;
    });
    child.once("error", reject);
    child.once("close", (code) => {
      if (code !== 0) {
        reject(new Error(stderr.trim() || `O worker Python terminou com código ${code}.`));
        return;
      }
      let response: WorkerResponse<T>;
      try {
        response = JSON.parse(stdout) as WorkerResponse<T>;
      } catch {
        reject(new Error(stderr.trim() || "O worker Python retornou uma resposta inválida."));
        return;
      }
      if (response.ok) {
        resolve(response.result);
      } else {
        reject(new HttpError(response.error, response.status));
      }
    });
    child.stdin.end(`${JSON.stringify(payload)}\n`);
  });
}

const gmailTokenStore: GmailTokenStore = {
  async load() {
    const result = await worker<{ encryptedPayload: string | null }>({
      action: "gmail_credentials_load",
    });
    return result.encryptedPayload;
  },
  async save(encryptedPayload) {
    await worker({ action: "gmail_credentials_store", encryptedPayload });
  },
  async clear() {
    await worker({ action: "gmail_credentials_delete" });
  },
};
const gmailService = new GmailService(gmailTokenStore);

function asyncRoute(
  handler: (request: Request, response: Response, next: NextFunction) => Promise<void>,
) {
  return (request: Request, response: Response, next: NextFunction) => {
    void handler(request, response, next).catch(next);
  };
}

function escapeMarkdownLinkText(value: string): string {
  return value.replace(/[\\[\]]/g, "\\$&");
}

function appendWebReferences(answer: string, sources: WebSource[]): string {
  if (sources.length === 0) return answer;
  const references = sources.map((source, index) => {
    const url = encodeURI(source.url).replace(/[()]/g, (character) => (
      character === "(" ? "%28" : "%29"
    ));
    return `[W${index + 1}] [${escapeMarkdownLinkText(source.title)}](${url})`;
  });
  return `${answer}\n\nFontes pesquisadas:\n${references.join("\n")}`;
}

function requireSameOrigin(request: Request): void {
  const origin = request.get("origin");
  const allowed = new Set([
    `http://127.0.0.1:${PORT}`,
    `http://localhost:${PORT}`,
    "http://127.0.0.1:5173",
    "http://localhost:5173",
  ]);
  if (!origin || !allowed.has(origin)) {
    throw new HttpError("A solicitação Gmail precisa vir da interface local.", 403);
  }
}

function requestRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new HttpError("O corpo da solicitação é inválido.", 400);
  }
  return value as Record<string, unknown>;
}

function routeString(value: string | string[] | undefined, name: string): string {
  if (typeof value !== "string") throw new HttpError(`${name} inválido.`, 400);
  return value;
}

function optionalStringList(value: unknown, name: string): string | string[] | undefined {
  if (value === undefined) return undefined;
  if (typeof value === "string") return value;
  if (Array.isArray(value) && value.every((item) => typeof item === "string")) {
    return value;
  }
  throw new HttpError(`O campo ${name} deve ser texto ou uma lista de textos.`, 400);
}

function optionalHeader(value: unknown, name: string): string | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "string") throw new HttpError(`O campo ${name} deve ser texto.`, 400);
  return value;
}

async function createOllamaContentStream(
  messages: Array<{ role: string; content: string; [key: string]: unknown }>,
  signal: AbortSignal,
): Promise<AsyncIterable<string>> {
  const ollamaResponse = await fetch(`${OLLAMA_HOST}/api/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      model: CHAT_MODEL,
      messages,
      stream: true,
      keep_alive: MODEL_KEEP_ALIVE,
      options: {
        temperature: 0.3,
        num_ctx: Number.isInteger(MAX_MODEL_CONTEXT_TOKENS)
          && MAX_MODEL_CONTEXT_TOKENS > 0
          ? MAX_MODEL_CONTEXT_TOKENS
          : 4096,
      },
    }),
    signal,
  });
  if (!ollamaResponse.ok || !ollamaResponse.body) {
    const detail = await ollamaResponse.text();
    throw new HttpError(
      `O Ollama recusou a conversa (${ollamaResponse.status}): ${detail.slice(0, 500)}`,
      502,
    );
  }

  const reader = ollamaResponse.body.getReader();
  return (async function* () {
    const decoder = new TextDecoder();
    let buffer = "";
    const parseLine = (line: string): string => {
      if (!line.trim()) return "";
      const chunk = JSON.parse(line) as {
        message?: { content?: string };
        error?: string;
      };
      if (chunk.error) throw new Error(chunk.error);
      return chunk.message?.content ?? "";
    };

    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        const text = parseLine(line);
        if (text) yield text;
      }
      if (done) break;
    }
    if (buffer.trim()) {
      const text = parseLine(buffer);
      if (text) yield text;
    }
  })();
}

async function loadGmailMessage(messageId: string): Promise<Record<string, unknown>> {
  const raw = await gmailService.readMessage(messageId);
  return worker<Record<string, unknown>>({
    action: "gmail_parse_message",
    message: raw,
  });
}

async function runGmailIntent(
  intent: GmailIntent,
  question: string,
): Promise<{ action: string; data: unknown; draft?: Record<string, string> } | null> {
  if (intent.action === "none") return null;
  if (!["status", "list", "search", "read", "compose", "reply", "send"].includes(intent.action)) {
    throw new HttpError("O classificador retornou uma ação Gmail inválida.", 502);
  }

  try {
    if (intent.action === "status") {
      return { action: intent.action, data: await gmailService.status() };
    }
    if (intent.action === "list" || intent.action === "search") {
      return {
        action: intent.action,
        data: await gmailService.listMessages(intent.query || "in:inbox", intent.maxResults),
      };
    }
    if (intent.action === "read") {
      let messageId = intent.messageId;
      if (!messageId) {
        const result = await gmailService.listMessages(intent.query || "in:inbox", 1);
        messageId = result.messages[0]?.id ?? "";
      }
      if (!messageId) {
        return { action: intent.action, data: { error: "Nenhuma mensagem corresponde à pesquisa." } };
      }
      return { action: intent.action, data: await loadGmailMessage(messageId) };
    }
    if (intent.action === "reply") {
      let messageId = intent.messageId;
      if (!messageId) {
        const result = await gmailService.listMessages(intent.query || "in:inbox", 1);
        messageId = result.messages[0]?.id ?? "";
      }
      if (!messageId) {
        return { action: intent.action, data: { error: "Nenhuma mensagem corresponde à pesquisa." } };
      }
      const originalMessage = await loadGmailMessage(messageId);
      const fromAddress = originalMessage.fromAddress;
      if (typeof fromAddress !== "string" || !fromAddress.includes("@")) {
        return {
          action: intent.action,
          data: { error: "Não foi possível identificar o endereço do remetente para responder." },
        };
      }
      const generatedDraft = await worker<Record<string, string>>({
        action: "gmail_compose",
        prompt: question,
        originalMessage,
      });
      const originalSubject = typeof originalMessage.subject === "string"
        ? originalMessage.subject
        : "";
      const subject = originalSubject
        ? (/^re:/i.test(originalSubject) ? originalSubject : `Re: ${originalSubject}`)
        : generatedDraft.subject;
      const references = [
        originalMessage.references,
        originalMessage.messageId,
      ].filter((value): value is string => typeof value === "string" && value.length > 0).join(" ");
      const draft: Record<string, string> = {
        ...generatedDraft,
        to: fromAddress,
        subject,
      };
      if (typeof originalMessage.threadId === "string") draft.threadId = originalMessage.threadId;
      if (typeof originalMessage.messageId === "string") draft.inReplyTo = originalMessage.messageId;
      if (references) draft.references = references;
      return { action: intent.action, data: { originalMessage }, draft };
    }

    const draft = await worker<Record<string, string>>({
      action: "gmail_compose",
      prompt: question,
    });
    return { action: intent.action, data: { preparedForReview: true }, draft };
  } catch (error) {
    if (
      error instanceof HttpError
      && [401, 403, 404, 503].includes(error.status)
    ) {
      return { action: intent.action, data: { error: error.message } };
    }
    throw error;
  }
}

function appendGmailToolResult(
  messages: Array<{ role: string; content: string; [key: string]: unknown }>,
  result: { action: string; data: unknown; draft?: Record<string, string> },
): void {
  let data = result.data;
  if (data && typeof data === "object" && !Array.isArray(data)) {
    const record = data as Record<string, unknown>;
    if (result.action === "read" && typeof record.body === "string") {
      data = {
        ...record,
        body: record.body.slice(0, 12_000),
        bodyTruncated: record.body.length > 12_000,
      };
    } else if (
      result.action === "reply"
      && record.originalMessage
      && typeof record.originalMessage === "object"
      && !Array.isArray(record.originalMessage)
    ) {
      const originalMessage = record.originalMessage as Record<string, unknown>;
      const body = originalMessage.body;
      data = {
        ...record,
        originalMessage: {
          ...originalMessage,
          ...(typeof body === "string"
            ? { body: body.slice(0, 12_000), bodyTruncated: body.length > 12_000 }
            : {}),
        },
      };
    }
  }
  messages.push({
    role: "assistant",
    content: "",
    tool_calls: [{
      function: {
        name: "gmail_operation",
        arguments: { action: result.action },
      },
    }],
  });
  messages.push({
    role: "tool",
    content: JSON.stringify({
      action: result.action,
      data,
      ...(result.draft ? { draft: result.draft } : {}),
    }),
  });
}

app.get("/api/health", asyncRoute(async (_request, response) => {
  let models: string[] = [];
  let ollamaConnected = false;
  let ollamaError: string | null = null;
  try {
    const tags = await fetch(`${OLLAMA_HOST}/api/tags`, { signal: AbortSignal.timeout(2000) });
    if (tags.ok) {
      const body = await tags.json() as { models?: Array<{ name?: string }> };
      models = (body.models ?? []).flatMap((model) => model.name ? [model.name] : []);
      ollamaConnected = true;
    } else {
      ollamaError = `Ollama respondeu com HTTP ${tags.status}.`;
    }
  } catch (error) {
    ollamaConnected = false;
    ollamaError = error instanceof Error ? error.message : "Falha ao consultar o Ollama.";
  }
  response.json({
    app: "Guilherme AI",
    localOnly: true,
    ollamaConnected,
    chatModel: CHAT_MODEL,
    embedModel: EMBED_MODEL,
    chatModelAvailable: models.some((name) => name.split(":")[0] === CHAT_MODEL.split(":")[0]),
    embedModelAvailable: models.some((name) => name.split(":")[0] === EMBED_MODEL.split(":")[0]),
    ollamaError,
  });
}));

app.get("/api/gmail/status", asyncRoute(async (_request, response) => {
  response.json(await gmailService.status());
}));

app.get("/api/gmail/oauth/start", asyncRoute(async (_request, response) => {
  response.redirect(gmailService.startOAuth());
}));

app.get("/api/gmail/oauth/callback", asyncRoute(async (request, response) => {
  const { code, state, error } = request.query;
  if (typeof error === "string") {
    throw new HttpError("A autorização Gmail foi recusada no Google.", 400);
  }
  if (typeof code !== "string" || typeof state !== "string") {
    throw new HttpError("O retorno OAuth Gmail está incompleto.", 400);
  }
  await gmailService.finishOAuth(code, state);
  const appUrl = process.env.NODE_ENV === "production"
    ? `http://127.0.0.1:${PORT}`
    : "http://127.0.0.1:5173";
  response.redirect(`${appUrl}/?gmail=connected`);
}));

app.post("/api/gmail/disconnect", asyncRoute(async (request, response) => {
  requireSameOrigin(request);
  response.json(await gmailService.disconnect());
}));

app.get("/api/gmail/messages", asyncRoute(async (request, response) => {
  const queryValue = request.query.q;
  const limitValue = request.query.limit;
  const pageTokenValue = request.query.pageToken;
  if (queryValue !== undefined && typeof queryValue !== "string") {
    throw new HttpError("O filtro Gmail é inválido.", 400);
  }
  if (limitValue !== undefined && typeof limitValue !== "string") {
    throw new HttpError("A quantidade de e-mails é inválida.", 400);
  }
  const query = typeof queryValue === "string" ? queryValue : "in:inbox";
  const limit = limitValue === undefined
    ? 10
    : typeof limitValue === "string" && /^\d+$/.test(limitValue)
      ? Number(limitValue)
      : Number.NaN;
  const pageToken = typeof pageTokenValue === "string" ? pageTokenValue : undefined;
  if (pageTokenValue !== undefined && pageToken === undefined) {
    throw new HttpError("O token de paginação Gmail é inválido.", 400);
  }
  response.json(await gmailService.listMessages(query, limit, pageToken));
}));

app.get("/api/gmail/messages/:id", asyncRoute(async (request, response) => {
  response.json(await loadGmailMessage(routeString(request.params.id, "Mensagem")));
}));

app.post("/api/gmail/send/preview", asyncRoute(async (request, response) => {
  requireSameOrigin(request);
  const body = requestRecord(request.body);
  if (typeof body.subject !== "string" || typeof body.body !== "string") {
    throw new HttpError("Informe o assunto e o corpo do e-mail.", 400);
  }
  const threadId = optionalHeader(body.threadId, "threadId");
  const inReplyTo = optionalHeader(body.inReplyTo, "inReplyTo");
  const references = optionalHeader(body.references, "references");
  const preview = gmailService.createSendPreview({
    to: optionalStringList(body.to, "Para") ?? "",
    cc: optionalStringList(body.cc, "CC"),
    bcc: optionalStringList(body.bcc, "CCO"),
    subject: body.subject,
    body: body.body,
    ...(threadId !== undefined ? { threadId } : {}),
    ...(inReplyTo !== undefined ? { inReplyTo } : {}),
    ...(references !== undefined ? { references } : {}),
  });
  response.status(201).json(preview);
}));

app.post("/api/gmail/send/:previewId/confirm", asyncRoute(async (request, response) => {
  requireSameOrigin(request);
  const body = requestRecord(request.body);
  response.json(await gmailService.confirmSend(
    routeString(request.params.previewId, "Prévia"),
    body.confirmed === true,
  ));
}));

app.get("/api/conversations", asyncRoute(async (_request, response) => {
  response.json(await worker({ action: "conversations" }));
}));

app.post("/api/conversations", asyncRoute(async (_request, response) => {
  response.status(201).json(await worker({ action: "create_conversation" }));
}));

app.get("/api/conversations/:id/messages", asyncRoute(async (request, response) => {
  response.json(await worker({
    action: "messages",
    conversationId: requireInteger(request.params.id, "Conversa"),
  }));
}));

app.delete("/api/conversations/:id", asyncRoute(async (request, response) => {
  response.json(await worker({
    action: "delete_conversation",
    conversationId: requireInteger(request.params.id, "Conversa"),
  }));
}));

app.post("/api/chat", asyncRoute(async (request, response) => {
  const {
    question,
    conversationId,
    useLibrary,
    gmailMessageId,
    provider: requestedProvider,
    allowPrivateContext,
  } = requestRecord(request.body);
  const provider = resolveChatProvider(requestedProvider);
  if (allowPrivateContext !== undefined && typeof allowPrivateContext !== "boolean") {
    throw new HttpError("A autorização de contexto privado é inválida.", 400);
  }
  const privateContextAuthorized = provider === "ollama" || allowPrivateContext === true;
  if (typeof question !== "string" || question.trim().length === 0 || question.length > 4000) {
    throw new HttpError("Digite uma pergunta com até 4.000 caracteres.", 400);
  }
  if (typeof conversationId !== "number" || !Number.isInteger(conversationId) || conversationId < 1) {
    throw new HttpError("Selecione uma conversa válida.", 400);
  }
  if (
    gmailMessageId !== undefined
    && (typeof gmailMessageId !== "string" || !/^[A-Za-z0-9_-]{1,200}$/.test(gmailMessageId))
  ) {
    throw new HttpError("Identificador de mensagem Gmail inválido.", 400);
  }
  if (provider === "gemini" && !privateContextAuthorized && gmailMessageId !== undefined) {
    throw new HttpError(
      "Autorize o envio de contexto privado para usar uma mensagem Gmail com Gemini.",
      403,
    );
  }

  const prepared = await worker<{
    conversationId: number;
    question: string;
    messages: Array<{ role: string; content: string; [key: string]: unknown }>;
    sources: Array<{ source: string; content: string; score: number }>;
    webSources: WebSource[];
    gmailIntent: GmailIntent;
  }>({
    action: "prepare_chat",
    question,
    conversationId,
    useLibrary: privateContextAuthorized && useLibrary !== false,
    includePrivateContext: privateContextAuthorized,
    ...(typeof gmailMessageId === "string" ? { gmailMessageId } : {}),
  });
  if (
    provider === "gemini"
    && !privateContextAuthorized
    && prepared.gmailIntent.action !== "none"
  ) {
    throw new HttpError(
      "Esta solicitação requer acesso ao Gmail. Ative a autorização de contexto privado para continuar.",
      403,
    );
  }
  const gmailResult = privateContextAuthorized
    ? await runGmailIntent(prepared.gmailIntent, prepared.question)
    : null;
  if (gmailResult) appendGmailToolResult(prepared.messages, gmailResult);

  const controller = new AbortController();
  response.on("close", () => {
    if (!response.writableEnded) controller.abort();
  });

  try {
    const tokenStream = provider === "gemini"
      ? await createGeminiContentStream(prepared.messages, { signal: controller.signal })
      : await createOllamaContentStream(prepared.messages, controller.signal);

    response.status(200);
    response.setHeader("content-type", "text/event-stream; charset=utf-8");
    response.setHeader("cache-control", "no-cache, no-transform");
    response.setHeader("connection", "keep-alive");
    response.flushHeaders();

    let answer = "";
    for await (const token of tokenStream) {
      answer += token;
      response.write(`data: ${JSON.stringify({ token })}\n\n`);
    }
    if (!answer.trim()) throw new Error("O modelo retornou uma resposta vazia.");

    const answerWithWebReferences = appendWebReferences(answer, prepared.webSources);
    if (answerWithWebReferences !== answer) {
      const references = answerWithWebReferences.slice(answer.length);
      answer = answerWithWebReferences;
      response.write(`data: ${JSON.stringify({ token: references })}\n\n`);
    }

    await worker({
      action: "save_chat",
      conversationId: prepared.conversationId,
      question: prepared.question,
      answer,
      provider,
    });
    response.write(`event: done\ndata: ${JSON.stringify({
      conversationId: prepared.conversationId,
      answer,
      provider,
      sources: prepared.sources,
      webSources: prepared.webSources,
      gmailData: gmailResult?.data,
      gmailDraft: gmailResult?.draft,
    })}\n\n`);
    response.end();
  } catch (error) {
    if (response.headersSent) {
      if (!controller.signal.aborted) {
        const message = error instanceof Error ? error.message : "Falha ao gerar a resposta.";
        response.write(`event: error\ndata: ${JSON.stringify({ error: message })}\n\n`);
      }
      response.end();
      return;
    }
    if (error instanceof GeminiConfigurationError) {
      throw new HttpError(error.message, 503);
    }
    if (error instanceof GeminiApiError) {
      throw new HttpError(error.message, 502);
    }
    throw error;
  }
}));

app.get("/api/memories", asyncRoute(async (_request, response) => {
  response.json(await worker({ action: "memories" }));
}));

app.post("/api/memories", asyncRoute(async (request, response) => {
  response.status(201).json(await worker({ action: "add_memory", content: request.body.content }));
}));

app.delete("/api/memories/:id", asyncRoute(async (request, response) => {
  response.json(await worker({
    action: "delete_memory",
    id: requireInteger(request.params.id, "Memória"),
  }));
}));

app.get("/api/notes", asyncRoute(async (_request, response) => {
  response.json(await worker({ action: "notes" }));
}));

app.post("/api/notes", asyncRoute(async (request, response) => {
  response.status(201).json(await worker({ action: "add_note", content: request.body.content }));
}));

app.delete("/api/notes/:id", asyncRoute(async (request, response) => {
  response.json(await worker({
    action: "delete_note",
    id: requireInteger(request.params.id, "Nota"),
  }));
}));

app.get("/api/documents", asyncRoute(async (_request, response) => {
  response.json(await worker({ action: "documents" }));
}));

app.post("/api/documents/upload", asyncRoute(async (request, response) => {
  const { filename, contentBase64 } = request.body as {
    filename?: unknown;
    contentBase64?: unknown;
  };
  const { name, content } = validateDocumentUpload(filename, contentBase64);
  const library = path.join(ROOT, "biblioteca");
  await mkdir(library, { recursive: true });
  const destination = path.join(library, name);
  try {
    await writeFile(destination, content, { flag: "wx" });
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "EEXIST") {
      throw new HttpError("Já existe um arquivo com esse nome. Renomeie antes de enviar.", 409);
    }
    throw error;
  }
  response.status(201).json({ filename: name, uploaded: true });
}));

app.post("/api/documents/index", asyncRoute(async (request, response) => {
  response.json(await worker({
    action: "index_document",
    filename: request.body.filename,
    enableOcr: request.body.enableOcr,
  }));
}));

app.post("/api/documents/reindex", asyncRoute(async (_request, response) => {
  response.json(await worker({ action: "reindex_library" }));
}));

app.delete("/api/documents/:id/index", asyncRoute(async (request, response) => {
  response.json(await worker({
    action: "remove_document",
    id: requireInteger(request.params.id, "Documento"),
  }));
}));

app.post("/api/spreadsheets/upload", asyncRoute(async (request, response) => {
  const { name, content } = validateSpreadsheetUpload(
    request.body.filename,
    request.body.contentBase64,
  );
  const directory = path.join(ROOT, "data", "spreadsheets");
  await mkdir(directory, { recursive: true });
  try {
    await writeFile(path.join(directory, name), content, { flag: "wx" });
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "EEXIST") {
      throw new HttpError("Já existe uma planilha com esse nome. Renomeie antes de enviar.", 409);
    }
    throw error;
  }
  response.status(201).json({ filename: name, uploaded: true });
}));

app.post("/api/spreadsheets/analyze", asyncRoute(async (request, response) => {
  response.json(await worker({
    action: "analyze_spreadsheet",
    filename: request.body.filename,
  }));
}));

app.post("/api/spreadsheets/create", asyncRoute(async (request, response) => {
  response.status(201).json(await worker({
    action: "create_spreadsheet",
    filename: request.body.filename,
    columns: request.body.columns,
    rows: request.body.rows,
  }));
}));

app.get("/api/spreadsheets/files/:filename", (request, response, next) => {
  const filename = request.params.filename;
  if (!/^[\p{L}\p{N} ._-]+\.xlsx$/iu.test(filename)) {
    response.status(400).json({ error: "Nome de planilha inválido." });
    return;
  }
  const file = path.join(ROOT, "data", "spreadsheets", filename);
  if (!existsSync(file)) {
    response.status(404).json({ error: "Planilha não encontrada." });
    return;
  }
  response.download(file, filename, (error) => {
    if (error) next(error);
  });
});

app.post("/api/projects/analyze", asyncRoute(async (request, response) => {
  response.json(await worker({
    action: "analyze_project",
    directory: request.body.directory,
  }));
}));

app.get("/api/tools", (_request, response) => {
  response.json([
    { id: "calculator", name: "Calculadora segura", enabled: true },
    { id: "datetime", name: "Data e hora locais", enabled: true },
    { id: "spreadsheet", name: "Análise e criação de planilhas", enabled: true },
    { id: "project", name: "Inventário de projetos", enabled: true },
    { id: "web_search", name: "Pesquisa na internet", enabled: true, note: "SearXNG local" },
    { id: "email", name: "Gmail", enabled: gmailService.configured, note: "Leitura e envio com confirmação explícita" },
  ]);
});

app.post("/api/tools/execute", asyncRoute(async (request, response) => {
  response.json(await worker({
    action: "execute_tool",
    name: request.body.name,
    input: request.body.input,
  }));
}));

const builtFrontend = path.join(ROOT, "frontend", "dist");
if (existsSync(builtFrontend)) {
  app.use(express.static(builtFrontend));
  app.use((request, response, next) => {
    if (request.method !== "GET" || request.path.startsWith("/api/")) {
      next();
      return;
    }
    response.sendFile(path.join(builtFrontend, "index.html"));
  });
}

app.use("/api", (_request, response) => {
  response.status(404).json({ error: "Rota da API não encontrada." });
});

app.use((error: unknown, _request: Request, response: Response, next: NextFunction) => {
  if (response.headersSent) {
    next(error);
    return;
  }
  const status = error instanceof HttpError ? error.status : 500;
  const message = error instanceof Error ? error.message : "Erro interno inesperado.";
  if (status >= 500) console.error(error);
  response.status(status).json({ error: message });
});

app.listen(PORT, "127.0.0.1", () => {
  console.log(`Guilherme AI API local em http://127.0.0.1:${PORT}`);
});
