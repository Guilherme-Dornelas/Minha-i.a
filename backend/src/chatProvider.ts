import { HttpError } from "./validation.js";

export type ChatProvider = "ollama" | "gemini";

export function resolveChatProvider(value: unknown): ChatProvider {
  if (value === undefined) return "ollama";
  if (value === "ollama" || value === "gemini") return value;
  throw new HttpError("Provedor de conversa inválido.", 400);
}
