import {
  createCipheriv,
  createDecipheriv,
  randomBytes,
  randomUUID,
} from "node:crypto";
import { HttpError } from "./validation.js";

const GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth";
const GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token";
const GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke";
const GMAIL_API_URL = "https://gmail.googleapis.com/gmail/v1/users/me";
const GMAIL_SCOPES = [
  "https://www.googleapis.com/auth/gmail.readonly",
  "https://www.googleapis.com/auth/gmail.send",
];
const MAX_GMAIL_RESPONSE_BYTES = 2_000_000;
const MAX_PENDING_DRAFT_AGE_MS = 15 * 60 * 1000;

export type GmailTokenStore = {
  load(): Promise<string | null>;
  save(encryptedPayload: string): Promise<void>;
  clear(): Promise<void>;
};

type GmailEnvironment = NodeJS.ProcessEnv;
type Credential = {
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
  email: string;
};
type EncryptedCredential = {
  version: 1;
  iv: string;
  tag: string;
  ciphertext: string;
};
type SendFields = {
  to: string | string[];
  cc?: string | string[];
  bcc?: string | string[];
  subject: string;
  body: string;
  threadId?: string;
  inReplyTo?: string;
  references?: string;
};
type Draft = {
  to: string;
  cc: string;
  bcc: string;
  subject: string;
  body: string;
  threadId?: string;
  inReplyTo?: string;
  references?: string;
  from: string;
};
type PendingDraft = {
  draft: Draft;
  createdAt: number;
};
type GmailApiMessage = {
  id?: string;
  threadId?: string;
  snippet?: string;
  internalDate?: string;
  labelIds?: unknown;
  payload?: {
    headers?: unknown;
  };
};
type GmailListResponse = {
  messages?: Array<{ id?: string; threadId?: string }>;
  nextPageToken?: string;
  resultSizeEstimate?: number;
};

function decodeBase64Key(value: string): Buffer | undefined {
  if (!/^[A-Za-z0-9+/]+={0,2}$/.test(value)) return undefined;
  const key = Buffer.from(value, "base64");
  return key.length === 32 ? key : undefined;
}

function isLoopbackOAuthRedirect(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "http:"
      && url.hostname === "127.0.0.1"
      && url.port === "8000"
      && url.pathname === "/api/gmail/oauth/callback"
      && !url.search
      && !url.hash
      && !url.username
      && !url.password;
  } catch {
    return false;
  }
}

function readConfig(env: GmailEnvironment) {
  const clientId = env.GOOGLE_CLIENT_ID?.trim();
  const clientSecret = env.GOOGLE_CLIENT_SECRET?.trim();
  const redirectUri = env.GOOGLE_REDIRECT_URI?.trim();
  const encryptionKey = env.GMAIL_TOKEN_ENCRYPTION_KEY?.trim();
  const allowedEmail = env.GMAIL_ALLOWED_EMAIL?.trim().toLowerCase();
  const key = encryptionKey ? decodeBase64Key(encryptionKey) : undefined;
  if (
    !clientId
    || !clientSecret
    || !redirectUri
    || !key
    || !allowedEmail
    || !/^[^@\s]{1,64}@[^@\s]{1,255}$/.test(allowedEmail)
    || !isLoopbackOAuthRedirect(redirectUri)
  ) {
    return undefined;
  }
  return {
    clientId,
    clientSecret,
    redirectUri,
    encryptionKey: key,
    allowedEmail,
  };
}

async function responseJson(response: Response, maxBytes = MAX_GMAIL_RESPONSE_BYTES): Promise<Record<string, unknown>> {
  if (!response.body) {
    if (response.status === 204) return {};
    throw new HttpError("O serviço do Google retornou uma resposta vazia.", 502);
  }
  const reader = response.body.getReader();
  const chunks: Buffer[] = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > maxBytes) {
      await reader.cancel();
      throw new HttpError("A resposta do Gmail excedeu o limite de tamanho.", 502);
    }
    chunks.push(Buffer.from(value));
  }
  try {
    const payload: unknown = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    if (payload && typeof payload === "object" && !Array.isArray(payload)) {
      return payload as Record<string, unknown>;
    }
  } catch {
    throw new HttpError("O serviço do Google retornou JSON inválido.", 502);
  }
  throw new HttpError("O serviço do Google retornou um formato inválido.", 502);
}

function tokenErrorStatus(response: Response): HttpError {
  if (response.status === 400 || response.status === 401) {
    return new HttpError("A autorização Gmail expirou ou foi recusada. Reconecte a conta.", 401);
  }
  return new HttpError("Não foi possível concluir a autorização Gmail.", 502);
}

function normalizeRecipientList(value: string | string[] | undefined, field: string): string[] {
  if (value === undefined) return [];
  const values = Array.isArray(value) ? value : value.split(/[;,]/);
  if (values.length > 10 || values.some((item) => typeof item !== "string")) {
    throw new HttpError(`A lista ${field} é inválida.`, 400);
  }
  const recipients = values.map((item) => item.trim()).filter(Boolean);
  const emailPattern = /^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,63}$/i;
  if (recipients.some((item) => item.length > 254 || !emailPattern.test(item))) {
    throw new HttpError(`Informe endereços de e-mail válidos em ${field}.`, 400);
  }
  return recipients;
}

function safeHeader(value: string, field: string, maximum: number): string {
  if (value.length > maximum || /[\r\n\u0000]/.test(value)) {
    throw new HttpError(`O campo ${field} contém caracteres inválidos ou excede o limite.`, 400);
  }
  return value;
}

function encodeHeader(value: string): string {
  if (/^[\x20-\x7e]*$/.test(value)) return value;
  return `=?UTF-8?B?${Buffer.from(value, "utf8").toString("base64")}?=`;
}

function wrapBase64(value: string): string {
  return value.match(/.{1,76}/g)?.join("\r\n") ?? "";
}

function messageHeader(headers: unknown, name: string): string {
  if (!Array.isArray(headers)) return "";
  const header = headers.find((item) => (
    item && typeof item === "object"
    && typeof (item as { name?: unknown }).name === "string"
    && (item as { name: string }).name.toLowerCase() === name.toLowerCase()
  )) as { value?: unknown } | undefined;
  return typeof header?.value === "string" ? decodeMimeHeader(header.value) : "";
}

function decodeMimeHeader(value: string): string {
  return value.replace(
    /=\?([^?]+)\?([bq])\?([^?]+)\?=/gi,
    (match, charset: string, encoding: string, data: string) => {
      try {
        let bytes: Buffer;
        if (encoding.toLowerCase() === "b") {
          bytes = Buffer.from(data, "base64");
        } else {
          const output: number[] = [];
          for (let index = 0; index < data.length; index += 1) {
            if (data[index] === "_" ) output.push(32);
            else if (data[index] === "=" && /^[0-9a-f]{2}$/i.test(data.slice(index + 1, index + 3))) {
              output.push(Number.parseInt(data.slice(index + 1, index + 3), 16));
              index += 2;
            } else output.push(data.charCodeAt(index) & 0xff);
          }
          bytes = Buffer.from(output);
        }
        return new TextDecoder(charset).decode(bytes);
      } catch {
        return match;
      }
    },
  );
}

function summarizeMessage(message: GmailApiMessage) {
  const labels = Array.isArray(message.labelIds) ? message.labelIds : [];
  const dateHeader = messageHeader(message.payload?.headers, "Date");
  const internalDate = Number(message.internalDate);
  return {
    id: message.id ?? "",
    threadId: message.threadId ?? "",
    from: messageHeader(message.payload?.headers, "From"),
    to: messageHeader(message.payload?.headers, "To"),
    subject: messageHeader(message.payload?.headers, "Subject"),
    date: dateHeader || (
      Number.isFinite(internalDate) && Number.isFinite(new Date(internalDate).getTime())
        ? new Date(internalDate).toISOString()
        : ""
    ),
    snippet: typeof message.snippet === "string" ? message.snippet.slice(0, 1000) : "",
    unread: labels.includes("UNREAD"),
  };
}

export class GmailService {
  private readonly environment: GmailEnvironment;
  private readonly fetcher: typeof fetch;
  private readonly now: () => number;
  private readonly oauthStates = new Map<string, number>();
  private readonly pendingDrafts = new Map<string, PendingDraft>();

  constructor(
    private readonly tokenStore: GmailTokenStore,
    options: { env?: GmailEnvironment; fetcher?: typeof fetch; now?: () => number } = {},
  ) {
    this.environment = options.env ?? process.env;
    this.fetcher = options.fetcher ?? fetch;
    this.now = options.now ?? Date.now;
  }

  get configured(): boolean {
    return readConfig(this.environment) !== undefined;
  }

  private requireConfig() {
    const config = readConfig(this.environment);
    if (!config) {
      throw new HttpError(
        "Gmail não está configurado. Defina OAuth, GMAIL_ALLOWED_EMAIL e a chave de criptografia no .env.",
        503,
      );
    }
    return config;
  }

  private encryptCredential(credential: Credential): string {
    const { encryptionKey } = this.requireConfig();
    const iv = randomBytes(12);
    const cipher = createCipheriv("aes-256-gcm", encryptionKey, iv);
    const ciphertext = Buffer.concat([
      cipher.update(JSON.stringify(credential), "utf8"),
      cipher.final(),
    ]);
    const envelope: EncryptedCredential = {
      version: 1,
      iv: iv.toString("base64"),
      tag: cipher.getAuthTag().toString("base64"),
      ciphertext: ciphertext.toString("base64"),
    };
    return JSON.stringify(envelope);
  }

  private decryptCredential(value: string): Credential {
    const { encryptionKey } = this.requireConfig();
    try {
      const envelope = JSON.parse(value) as EncryptedCredential;
      if (
        envelope.version !== 1
        || typeof envelope.iv !== "string"
        || typeof envelope.tag !== "string"
        || typeof envelope.ciphertext !== "string"
      ) {
        throw new Error("invalid envelope");
      }
      const decipher = createDecipheriv(
        "aes-256-gcm",
        encryptionKey,
        Buffer.from(envelope.iv, "base64"),
      );
      decipher.setAuthTag(Buffer.from(envelope.tag, "base64"));
      const plaintext = Buffer.concat([
        decipher.update(Buffer.from(envelope.ciphertext, "base64")),
        decipher.final(),
      ]).toString("utf8");
      const credential = JSON.parse(plaintext) as Credential;
      if (
        typeof credential.accessToken !== "string"
        || typeof credential.refreshToken !== "string"
        || typeof credential.email !== "string"
        || typeof credential.expiresAt !== "number"
      ) {
        throw new Error("invalid credentials");
      }
      return credential;
    } catch {
      throw new HttpError(
        "As credenciais Gmail locais não puderam ser descriptografadas. Reconecte a conta.",
        500,
      );
    }
  }

  private async credential(): Promise<Credential | null> {
    const encryptedPayload = await this.tokenStore.load();
    if (!encryptedPayload) return null;
    return this.decryptCredential(encryptedPayload);
  }

  private async saveCredential(credential: Credential): Promise<void> {
    await this.tokenStore.save(this.encryptCredential(credential));
  }

  private async readJson(
    url: string,
    init: RequestInit,
    maxBytes = MAX_GMAIL_RESPONSE_BYTES,
  ): Promise<{ response: Response; body: Record<string, unknown> }> {
    let response: Response;
    try {
      response = await this.fetcher(url, {
        ...init,
        redirect: "error",
        signal: AbortSignal.timeout(15_000),
      });
    } catch (error) {
      if (error instanceof TypeError || error instanceof DOMException) {
        throw new HttpError("Não foi possível conectar ao serviço Gmail do Google.", 502);
      }
      throw error;
    }
    const body = await responseJson(response, maxBytes);
    return { response, body };
  }

  private async tokenRequest(values: Record<string, string>): Promise<Record<string, unknown>> {
    const { response, body } = await this.readJson(
      GOOGLE_TOKEN_URL,
      {
        method: "POST",
        headers: { "content-type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams(values),
      },
    );
    if (!response.ok) throw tokenErrorStatus(response);
    return body;
  }

  startOAuth(): string {
    const config = this.requireConfig();
    const now = this.now();
    for (const [state, expiresAt] of this.oauthStates) {
      if (expiresAt <= now) this.oauthStates.delete(state);
    }
    if (this.oauthStates.size >= 1000) {
      throw new HttpError("Há muitas autorizações Gmail aguardando. Tente novamente em instantes.", 429);
    }
    const state = randomBytes(32).toString("base64url");
    this.oauthStates.set(state, now + 10 * 60 * 1000);
    const authorization = new URL(GOOGLE_AUTH_URL);
    authorization.search = new URLSearchParams({
      client_id: config.clientId,
      redirect_uri: config.redirectUri,
      response_type: "code",
      scope: GMAIL_SCOPES.join(" "),
      access_type: "offline",
      prompt: "consent",
      include_granted_scopes: "true",
      state,
    }).toString();
    return authorization.toString();
  }

  async finishOAuth(code: string, state: string): Promise<{ email: string }> {
    const expiresAt = this.oauthStates.get(state);
    this.oauthStates.delete(state);
    if (!expiresAt || expiresAt <= this.now() || !/^[A-Za-z0-9._~+/=-]{1,2048}$/.test(code)) {
      throw new HttpError("A autorização Gmail expirou ou o parâmetro state é inválido.", 400);
    }
    const config = this.requireConfig();
    const oldCredential = await this.credential();
    const tokenBody = await this.tokenRequest({
      code,
      client_id: config.clientId,
      client_secret: config.clientSecret,
      redirect_uri: config.redirectUri,
      grant_type: "authorization_code",
    });
    const accessToken = tokenBody.access_token;
    const newRefreshToken = tokenBody.refresh_token;
    const expiresIn = tokenBody.expires_in;
    if (
      typeof accessToken !== "string"
      || (newRefreshToken !== undefined && typeof newRefreshToken !== "string")
      || typeof expiresIn !== "number"
      || !Number.isFinite(expiresIn)
      || expiresIn <= 0
    ) {
      throw new HttpError("O Google não retornou tokens válidos para o Gmail.", 502);
    }
    const refreshToken = (newRefreshToken as string | undefined) || oldCredential?.refreshToken;
    if (!refreshToken) {
      throw new HttpError(
        "O Google não forneceu um refresh token. Revogue o acesso antigo e autorize novamente.",
        502,
      );
    }
    const { body: profile } = await this.readJson(
      `${GMAIL_API_URL}/profile`,
      { headers: { authorization: `Bearer ${accessToken}` } },
    );
    const email = profile.emailAddress;
    if (typeof email !== "string" || !email.includes("@")) {
      throw new HttpError("Não foi possível identificar a conta Gmail autorizada.", 502);
    }
    const normalizedEmail = email.toLowerCase();
    if (normalizedEmail !== config.allowedEmail) {
      throw new HttpError("A conta Google autorizada não corresponde à conta permitida.", 403);
    }
    await this.saveCredential({
      accessToken,
      refreshToken,
      expiresAt: this.now() + expiresIn * 1000,
      email: normalizedEmail,
    });
    return { email: normalizedEmail };
  }

  async status(): Promise<{ configured: boolean; connected: boolean; email: string | null }> {
    if (!this.configured) return { configured: false, connected: false, email: null };
    const credential = await this.credential();
    return {
      configured: true,
      connected: Boolean(credential),
      email: credential?.email ?? null,
    };
  }

  private async refreshCredential(credential: Credential): Promise<Credential> {
    const { clientId, clientSecret } = this.requireConfig();
    const body = await this.tokenRequest({
      client_id: clientId,
      client_secret: clientSecret,
      refresh_token: credential.refreshToken,
      grant_type: "refresh_token",
    });
    if (typeof body.access_token !== "string" || typeof body.expires_in !== "number") {
      throw new HttpError("O Google não conseguiu renovar o acesso Gmail. Reconecte a conta.", 401);
    }
    const updated: Credential = {
      ...credential,
      accessToken: body.access_token,
      refreshToken: typeof body.refresh_token === "string"
        ? body.refresh_token
        : credential.refreshToken,
      expiresAt: this.now() + body.expires_in * 1000,
    };
    await this.saveCredential(updated);
    return updated;
  }

  private async freshCredential(forceRefresh = false): Promise<Credential> {
    const credential = await this.credential();
    if (!credential) throw new HttpError("Conecte uma conta Gmail antes de continuar.", 401);
    if (!forceRefresh && credential.expiresAt > this.now() + 60_000) return credential;
    return this.refreshCredential(credential);
  }

  private async gmailRequest(
    route: string,
    init: RequestInit = {},
    options: { retryUnauthorized?: boolean; maxBytes?: number } = {},
  ): Promise<Record<string, unknown>> {
    let credential = await this.freshCredential();
    const request = () => this.readJson(
      `${GMAIL_API_URL}${route}`,
      {
        ...init,
        headers: {
          ...init.headers,
          authorization: `Bearer ${credential.accessToken}`,
        },
      },
      options.maxBytes,
    );
    let result = await request();
    if (result.response.status === 401 && options.retryUnauthorized !== false) {
      credential = await this.freshCredential(true);
      result = await request();
    }
    if (!result.response.ok) {
      const status = result.response.status === 401 || result.response.status === 403
        ? 401
        : result.response.status === 404
          ? 404
          : 502;
      throw new HttpError(
        status === 401
          ? "O acesso Gmail foi recusado. Reconecte a conta e tente novamente."
          : status === 404
            ? "A mensagem Gmail solicitada não foi encontrada."
            : `A Gmail API respondeu com HTTP ${result.response.status}.`,
        status,
      );
    }
    return result.body;
  }

  async listMessages(
    query = "in:inbox",
    maxResults = 10,
    pageToken?: string,
  ): Promise<{
    messages: ReturnType<typeof summarizeMessage>[];
    nextPageToken: string | null;
    resultSizeEstimate: number;
  }> {
    if (typeof query !== "string" || query.length > 500 || /[\u0000-\u001f]/.test(query)) {
      throw new HttpError("O filtro Gmail é inválido.", 400);
    }
    if (!Number.isInteger(maxResults) || maxResults < 1 || maxResults > 10) {
      throw new HttpError("A quantidade de e-mails deve estar entre 1 e 10.", 400);
    }
    if (pageToken !== undefined && (
      pageToken.length > 2048 || !/^[A-Za-z0-9._~+/=-]+$/.test(pageToken)
    )) {
      throw new HttpError("O token de paginação Gmail é inválido.", 400);
    }
    const parameters = new URLSearchParams({ maxResults: String(maxResults) });
    if (query.trim()) parameters.set("q", query.trim());
    if (pageToken) parameters.set("pageToken", pageToken);
    const payload = await this.gmailRequest(`/messages?${parameters.toString()}`);
    const list = payload as GmailListResponse;
    const messages = Array.isArray(list.messages) ? list.messages : [];
    const summaries = await Promise.all(messages.map(async (item) => {
      if (typeof item.id !== "string" || !/^[A-Za-z0-9_-]{1,200}$/.test(item.id)) return null;
      const metadata = await this.gmailRequest(
        `/messages/${encodeURIComponent(item.id)}?format=metadata`
          + "&metadataHeaders=From&metadataHeaders=To&metadataHeaders=Subject&metadataHeaders=Date",
      ) as GmailApiMessage;
      return summarizeMessage({
        ...metadata,
        id: item.id,
        threadId: typeof item.threadId === "string" ? item.threadId : metadata.threadId,
      });
    }));
    return {
      messages: summaries.filter((message): message is ReturnType<typeof summarizeMessage> => message !== null),
      nextPageToken: typeof list.nextPageToken === "string" ? list.nextPageToken : null,
      resultSizeEstimate: typeof list.resultSizeEstimate === "number" ? list.resultSizeEstimate : messages.length,
    };
  }

  async readMessage(messageId: string): Promise<Record<string, unknown>> {
    if (!/^[A-Za-z0-9_-]{1,200}$/.test(messageId)) {
      throw new HttpError("Identificador de mensagem Gmail inválido.", 400);
    }
    return this.gmailRequest(
      `/messages/${encodeURIComponent(messageId)}?format=full`,
      {},
      { maxBytes: MAX_GMAIL_RESPONSE_BYTES },
    );
  }

  async disconnect(): Promise<{ disconnected: true; remoteRevoked: boolean }> {
    this.oauthStates.clear();
    this.pendingDrafts.clear();
    if (!this.configured) {
      await this.tokenStore.clear();
      return { disconnected: true, remoteRevoked: false };
    }
    let credential: Credential | null;
    try {
      credential = await this.credential();
    } catch (error) {
      await this.tokenStore.clear();
      if (error instanceof HttpError) {
        return { disconnected: true, remoteRevoked: false };
      }
      throw error;
    }
    await this.tokenStore.clear();
    if (!credential) {
      return { disconnected: true, remoteRevoked: false };
    }
    try {
      const response = await this.fetcher(
        GOOGLE_REVOKE_URL,
        {
          method: "POST",
          headers: { "content-type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({ token: credential.refreshToken }),
          redirect: "error",
          signal: AbortSignal.timeout(10_000),
        },
      );
      return { disconnected: true, remoteRevoked: response.ok };
    } catch {
      return { disconnected: true, remoteRevoked: false };
    }
  }

  createSendPreview(fields: SendFields): {
    previewId: string;
    to: string;
    cc: string;
    bcc: string;
    subject: string;
    body: string;
  } {
    this.expireDrafts();
    const to = normalizeRecipientList(fields.to, "Para");
    const cc = normalizeRecipientList(fields.cc, "CC");
    const bcc = normalizeRecipientList(fields.bcc, "CCO");
    if (to.length === 0 || to.length + cc.length + bcc.length > 20) {
      throw new HttpError("Informe ao menos um destinatário e limite a 20 endereços.", 400);
    }
    const subject = safeHeader(fields.subject, "assunto", 300).trim();
    if (!subject) throw new HttpError("Informe o assunto do e-mail.", 400);
    if (
      typeof fields.body !== "string"
      || !fields.body.trim()
      || fields.body.length > 50_000
      || /[\u0000]/.test(fields.body)
    ) {
      throw new HttpError("Informe o corpo do e-mail, com até 50.000 caracteres.", 400);
    }
    for (const [name, value] of [
      ["threadId", fields.threadId],
      ["inReplyTo", fields.inReplyTo],
      ["references", fields.references],
    ] as const) {
      if (value !== undefined) safeHeader(value, name, 2000);
    }
    const previewId = randomUUID();
    const draft: Draft = {
      to: to.join(", "),
      cc: cc.join(", "),
      bcc: bcc.join(", "),
      subject,
      body: fields.body,
      threadId: fields.threadId,
      inReplyTo: fields.inReplyTo,
      references: fields.references,
      from: "",
    };
    this.pendingDrafts.set(previewId, { draft, createdAt: this.now() });
    return { previewId, to: draft.to, cc: draft.cc, bcc: draft.bcc, subject, body: draft.body };
  }

  async confirmSend(previewId: string, confirmed: boolean): Promise<{ id: string; threadId?: string }> {
    if (confirmed !== true) throw new HttpError("Confirme o envio explicitamente.", 400);
    this.expireDrafts();
    const pending = this.pendingDrafts.get(previewId);
    if (!pending) throw new HttpError("A prévia expirou ou já foi processada.", 409);
    this.pendingDrafts.delete(previewId);
    const credential = await this.freshCredential();
    const draft = { ...pending.draft, from: credential.email };
    const raw = buildMimeMessage(draft);
    const response = await this.gmailRequest(
      "/messages/send",
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          raw,
          ...(draft.threadId ? { threadId: draft.threadId } : {}),
        }),
      },
      { retryUnauthorized: false },
    );
    if (typeof response.id !== "string") {
      throw new HttpError("O Google não confirmou o envio do e-mail.", 502);
    }
    return {
      id: response.id,
      ...(typeof response.threadId === "string" ? { threadId: response.threadId } : {}),
    };
  }

  private expireDrafts(): void {
    const cutoff = this.now() - MAX_PENDING_DRAFT_AGE_MS;
    for (const [id, item] of this.pendingDrafts) {
      if (item.createdAt < cutoff) this.pendingDrafts.delete(id);
    }
  }
}

function buildMimeMessage(draft: Draft): string {
  const headers = [
    `From: ${draft.from}`,
    `To: ${draft.to}`,
  ];
  if (draft.cc) headers.push(`Cc: ${draft.cc}`);
  if (draft.bcc) headers.push(`Bcc: ${draft.bcc}`);
  headers.push(
    `Subject: ${encodeHeader(draft.subject)}`,
    "MIME-Version: 1.0",
    "Content-Type: text/plain; charset=UTF-8",
    "Content-Transfer-Encoding: base64",
  );
  if (draft.inReplyTo) headers.push(`In-Reply-To: ${draft.inReplyTo}`);
  if (draft.references) headers.push(`References: ${draft.references}`);
  const body = wrapBase64(Buffer.from(draft.body, "utf8").toString("base64"));
  return Buffer.from(`${headers.join("\r\n")}\r\n\r\n${body}`, "utf8").toString("base64url");
}
