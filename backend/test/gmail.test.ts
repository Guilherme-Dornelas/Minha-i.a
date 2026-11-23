import assert from "node:assert/strict";
import test from "node:test";
import { GmailService, type GmailTokenStore } from "../src/gmail.js";
import { HttpError } from "../src/validation.js";

const baseEnvironment: NodeJS.ProcessEnv = {
  GOOGLE_CLIENT_ID: "client-id",
  GOOGLE_CLIENT_SECRET: "client-secret",
  GOOGLE_REDIRECT_URI: "http://127.0.0.1:8000/api/gmail/oauth/callback",
  GMAIL_ALLOWED_EMAIL: "user@example.com",
  GMAIL_TOKEN_ENCRYPTION_KEY: Buffer.alloc(32, 7).toString("base64"),
};

class MemoryTokenStore implements GmailTokenStore {
  value: string | null = null;

  async load() {
    return this.value;
  }

  async save(encryptedPayload: string) {
    this.value = encryptedPayload;
  }

  async clear() {
    this.value = null;
  }
}

function jsonResponse(payload: Record<string, unknown>, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function formValues(init?: RequestInit): URLSearchParams {
  assert.ok(init?.body instanceof URLSearchParams);
  return init.body;
}

function oauthFetcher(email = "user@example.com") {
  return async (input: string | URL | Request, init?: RequestInit): Promise<Response> => {
    const url = String(input);
    if (url === "https://oauth2.googleapis.com/token") {
      return jsonResponse({
        access_token: "access-token-secret",
        refresh_token: "refresh-token-secret",
        expires_in: 3600,
      });
    }
    if (url.endsWith("/profile")) return jsonResponse({ emailAddress: email });
    throw new Error(`Unexpected request: ${url}`);
  };
}

async function connect(
  service: GmailService,
  email?: string,
): Promise<void> {
  const authorization = new URL(service.startOAuth());
  const state = authorization.searchParams.get("state");
  assert.ok(state);
  await service.finishOAuth("authorization-code", state);
  if (email) assert.equal((await service.status()).email, email.toLowerCase());
}

test("OAuth uses required scopes, validates state and encrypts stored tokens", async () => {
  const store = new MemoryTokenStore();
  const service = new GmailService(store, {
    env: { ...baseEnvironment },
    fetcher: oauthFetcher(),
    now: () => 1_000,
  });
  const authorization = new URL(service.startOAuth());
  assert.equal(authorization.searchParams.get("redirect_uri"), baseEnvironment.GOOGLE_REDIRECT_URI);
  assert.match(authorization.searchParams.get("scope") ?? "", /gmail\.readonly/);
  assert.match(authorization.searchParams.get("scope") ?? "", /gmail\.send/);
  await assert.rejects(service.finishOAuth("authorization-code", "wrong-state"), HttpError);
  await service.finishOAuth("authorization-code", authorization.searchParams.get("state") ?? "");

  assert.ok(store.value);
  assert.equal(store.value.includes("access-token-secret"), false);
  assert.equal(store.value.includes("refresh-token-secret"), false);
  assert.deepEqual(await service.status(), {
    configured: true,
    connected: true,
    email: "user@example.com",
  });
});

test("OAuth enforces the configured account allowlist and requires it to be configured", async () => {
  const store = new MemoryTokenStore();
  const service = new GmailService(store, {
    env: { ...baseEnvironment },
    fetcher: oauthFetcher("other@example.com"),
  });
  const authorization = new URL(service.startOAuth());
  await assert.rejects(
    service.finishOAuth("authorization-code", authorization.searchParams.get("state") ?? ""),
    (error: unknown) => error instanceof HttpError && error.status === 403,
  );
  assert.equal(store.value, null);

  const unconfigured = new GmailService(store, {
    env: { ...baseEnvironment, GMAIL_ALLOWED_EMAIL: "" },
    fetcher: oauthFetcher(),
  });
  assert.deepEqual(await unconfigured.status(), {
    configured: false,
    connected: false,
    email: null,
  });
  assert.throws(() => unconfigured.startOAuth(), (error: unknown) => (
    error instanceof HttpError && error.status === 503
  ));
});

test("Gmail listing and send require an explicit, single-use confirmation", async () => {
  const store = new MemoryTokenStore();
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  let now = 5_000;
  const fetcher: typeof fetch = async (input, init) => {
    const url = String(input);
    requests.push({ url, init });
    if (url === "https://oauth2.googleapis.com/token") {
      return jsonResponse({
        access_token: "access-token-secret",
        refresh_token: "refresh-token-secret",
        expires_in: 3600,
      });
    }
    if (url.endsWith("/profile")) return jsonResponse({ emailAddress: "user@example.com" });
    if (url.includes("/messages?")) {
      return jsonResponse({
        messages: [{ id: "message-1", threadId: "thread-1" }],
        resultSizeEstimate: 1,
      });
    }
    if (url.includes("/messages/message-1?format=metadata")) {
      return jsonResponse({
        id: "message-1",
        threadId: "thread-1",
        snippet: "Preview",
        labelIds: ["UNREAD"],
        payload: {
          headers: [
            { name: "From", value: "sender@example.com" },
            { name: "Subject", value: "Hello" },
            { name: "Date", value: "Mon, 20 Nov 2026 10:00:00 +0000" },
          ],
        },
      });
    }
    if (url.endsWith("/messages/send")) return jsonResponse({ id: "sent-1", threadId: "thread-1" });
    throw new Error(`Unexpected request: ${url}`);
  };
  const service = new GmailService(store, {
    env: { ...baseEnvironment },
    fetcher,
    now: () => now,
  });
  await connect(service, "user@example.com");

  const listed = await service.listMessages("in:inbox", 5);
  assert.equal(listed.messages.length, 1);
  assert.equal(listed.messages[0]?.from, "sender@example.com");
  assert.equal(listed.messages[0]?.unread, true);

  const preview = service.createSendPreview({
    to: "recipient@example.com",
    cc: "copy@example.com",
    subject: "Atualização",
    body: "Linha um\nLinha dois",
    threadId: "thread-1",
  });
  assert.equal(requests.some((item) => item.url.endsWith("/messages/send")), false);
  await assert.rejects(service.confirmSend(preview.previewId, false), HttpError);
  assert.deepEqual(await service.confirmSend(preview.previewId, true), {
    id: "sent-1",
    threadId: "thread-1",
  });
  await assert.rejects(service.confirmSend(preview.previewId, true), HttpError);
  assert.equal(requests.filter((item) => item.url.endsWith("/messages/send")).length, 1);
  const sendRequest = requests.find((item) => item.url.endsWith("/messages/send"));
  assert.ok(sendRequest?.init?.body);
  const sentMessage = JSON.parse(String(sendRequest.init.body)) as { raw: string; threadId: string };
  const raw = Buffer.from(sentMessage.raw, "base64url").toString("utf8");
  assert.match(raw, /To: recipient@example\.com/);
  assert.match(raw, /Cc: copy@example\.com/);
  assert.match(raw, /Subject: =\?UTF-8\?B\?/);
  assert.match(raw, /From: user@example\.com/);
  assert.equal(sentMessage.threadId, "thread-1");
  const encodedBody = raw.split("\r\n\r\n").at(-1)?.replace(/\r\n/g, "") ?? "";
  assert.equal(Buffer.from(encodedBody, "base64").toString("utf8"), "Linha um\nLinha dois");
  now += 20 * 60 * 1000;
  assert.throws(() => service.createSendPreview({
    to: "recipient@example.com",
    subject: "Bad\r\nBcc: other@example.com",
    body: "Body",
  }), HttpError);
  assert.throws(() => service.createSendPreview({
    to: "not-an-email",
    subject: "Bad address",
    body: "Body",
  }), HttpError);
});

test("refresh preserves the original refresh token when Google omits a replacement", async () => {
  const store = new MemoryTokenStore();
  let now = 10_000;
  const refreshTokens: string[] = [];
  const fetcher: typeof fetch = async (input, init) => {
    const url = String(input);
    if (url === "https://oauth2.googleapis.com/token") {
      const values = formValues(init);
      if (values.get("grant_type") === "authorization_code") {
        return jsonResponse({
          access_token: "initial-access",
          refresh_token: "original-refresh",
          expires_in: 1,
        });
      }
      const refreshToken = values.get("refresh_token");
      if (refreshToken) refreshTokens.push(refreshToken);
      return jsonResponse({ access_token: "renewed-access", expires_in: 1 });
    }
    if (url.endsWith("/profile")) return jsonResponse({ emailAddress: "user@example.com" });
    if (url.includes("/messages?")) return jsonResponse({ messages: [], resultSizeEstimate: 0 });
    throw new Error(`Unexpected request: ${url}`);
  };
  const service = new GmailService(store, {
    env: { ...baseEnvironment },
    fetcher,
    now: () => now,
  });
  await connect(service);
  now += 10_000;
  await service.listMessages("in:inbox", 1);
  now += 10_000;
  await service.listMessages("in:inbox", 1);
  assert.deepEqual(refreshTokens, ["original-refresh", "original-refresh"]);
});

test("expired send previews cannot be confirmed", async () => {
  let now = 0;
  const service = new GmailService(new MemoryTokenStore(), {
    env: { ...baseEnvironment },
    now: () => now,
  });
  const preview = service.createSendPreview({
    to: "recipient@example.com",
    subject: "Hello",
    body: "Body",
  });
  now = 16 * 60 * 1000;
  await assert.rejects(service.confirmSend(preview.previewId, true), HttpError);
});
