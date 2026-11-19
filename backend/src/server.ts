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

type WorkerResponse<T> = { ok: true; result: T } | { ok: false; error: string; status: number };

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const OLLAMA_HOST = (process.env.OLLAMA_HOST ?? "http://127.0.0.1:11434").replace(/\/+$/, "");
const CHAT_MODEL = process.env.GUILHERME_AI_MODEL ?? "guilherme-ai";
const EMBED_MODEL = process.env.GUILHERME_AI_EMBED_MODEL ?? "nomic-embed-text";
const PORT = Number(process.env.GUILHERME_AI_PORT ?? 8000);
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
    const child = spawn(pythonExecutable, ["-m", "guilherme_ai.web_worker"], {
      cwd: ROOT,
      env: process.env,
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

function asyncRoute(
  handler: (request: Request, response: Response, next: NextFunction) => Promise<void>,
) {
  return (request: Request, response: Response, next: NextFunction) => {
    void handler(request, response, next).catch(next);
  };
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
  const { question, conversationId, useLibrary } = request.body as {
    question?: unknown;
    conversationId?: unknown;
    useLibrary?: unknown;
  };
  if (typeof question !== "string" || question.trim().length === 0 || question.length > 4000) {
    throw new HttpError("Digite uma pergunta com até 4.000 caracteres.", 400);
  }
  if (typeof conversationId !== "number" || !Number.isInteger(conversationId) || conversationId < 1) {
    throw new HttpError("Selecione uma conversa válida.", 400);
  }

  const prepared = await worker<{
    conversationId: number;
    question: string;
    messages: Array<{ role: string; content: string }>;
    sources: Array<{ source: string; content: string; score: number }>;
  }>({ action: "prepare_chat", question, conversationId, useLibrary });

  const controller = new AbortController();
  response.on("close", () => {
    if (!response.writableEnded) controller.abort();
  });

  try {
    const ollamaResponse = await fetch(`${OLLAMA_HOST}/api/chat`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        model: CHAT_MODEL,
        messages: prepared.messages,
        stream: true,
        keep_alive: "2m",
        options: { temperature: 0.3, num_ctx: 4096 },
      }),
      signal: controller.signal,
    });
    if (!ollamaResponse.ok || !ollamaResponse.body) {
      const detail = await ollamaResponse.text();
      throw new HttpError(
        `O Ollama recusou a conversa (${ollamaResponse.status}): ${detail.slice(0, 500)}`,
        502,
      );
    }

    response.status(200);
    response.setHeader("content-type", "text/event-stream; charset=utf-8");
    response.setHeader("cache-control", "no-cache, no-transform");
    response.setHeader("connection", "keep-alive");
    response.flushHeaders();

    const decoder = new TextDecoder();
    const reader = ollamaResponse.body.getReader();
    let buffer = "";
    let answer = "";

    const forwardLine = (line: string) => {
      if (!line.trim()) return;
      const chunk = JSON.parse(line) as {
        message?: { content?: string };
        error?: string;
        done?: boolean;
      };
      if (chunk.error) throw new Error(chunk.error);
      const token = chunk.message?.content ?? "";
      if (token) {
        answer += token;
        response.write(`data: ${JSON.stringify({ token })}\n\n`);
      }
    };

    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) forwardLine(line);
      if (done) break;
    }
    if (buffer.trim()) forwardLine(buffer);
    if (!answer.trim()) throw new Error("O modelo retornou uma resposta vazia.");

    await worker({
      action: "save_chat",
      conversationId: prepared.conversationId,
      question: prepared.question,
      answer,
    });
    response.write(`event: done\ndata: ${JSON.stringify({
      conversationId: prepared.conversationId,
      answer,
      sources: prepared.sources,
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
  response.json(await worker({ action: "index_document", filename: request.body.filename }));
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
    { id: "web", name: "Pesquisa na internet", enabled: false, note: "Desativada por privacidade" },
    { id: "email", name: "Gmail somente leitura", enabled: false, note: "Aguarda autorização manual" },
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
