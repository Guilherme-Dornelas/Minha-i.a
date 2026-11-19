import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import {
  Activity,
  ArrowDown,
  ArrowUp,
  BookOpen,
  Check,
  ChevronDown,
  CircleHelp,
  Clock3,
  Copy,
  Download,
  FileText,
  FileSpreadsheet,
  FlaskConical,
  FolderOpen,
  Hash,
  History,
  LoaderCircle,
  Mail,
  Menu,
  MessageSquare,
  Moon,
  MoreHorizontal,
  Plus,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Sun,
  Trash2,
  Upload,
  UserRound,
  X,
  type LucideIcon,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type Page = "chat" | "library" | "memories" | "notes" | "tools" | "settings" | "email";
type Message = {
  id: number | string;
  role: "user" | "assistant";
  content: string;
  sources?: Array<{ source: string; content: string; score: number }>;
  loading?: boolean;
};
type Conversation = { id: number; title: string; is_default: number; updated_at: string };
type DocumentItem = { id: number; fonte: string; tipo: string; trechos_atuais: number };
type Memory = { id: number; content: string; created_at: string };
type Note = { id: number; conteudo: string; created_at: string };
type Health = {
  ollamaConnected: boolean;
  chatModel: string;
  embedModel: string;
  chatModelAvailable: boolean;
  embedModelAvailable: boolean;
  ollamaError?: string | null;
};
type SheetReport = {
  filename: string;
  sheets: Array<{
    sheet: string;
    rows: number;
    columns: number;
    columnNames: string[];
    missingByColumn: Record<string, number>;
    duplicateRows: number;
    numericSummary: Record<string, { min: number; max: number; mean: number }>;
    sample: Array<Record<string, unknown>>;
    truncated: boolean;
  }>;
};
type ProjectReport = {
  directory: string;
  filesAnalyzed: number;
  capped: boolean;
  technologies: string[];
  extensions: Record<string, number>;
  recommendations: string[];
  sensitiveFilesSkipped: number;
  contentsSentToModel: boolean;
  codeExecuted: boolean;
};

const navigation: Array<{ id: Page; label: string; icon: LucideIcon }> = [
  { id: "chat", label: "Conversas", icon: MessageSquare },
  { id: "library", label: "Biblioteca", icon: BookOpen },
  { id: "memories", label: "Memórias", icon: Hash },
  { id: "notes", label: "Notas", icon: FileText },
  { id: "tools", label: "Ferramentas", icon: FlaskConical },
];

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      ...(init?.body ? { "content-type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  const body = await response.json().catch(() => ({})) as { error?: string } & T;
  if (!response.ok) throw new Error(body.error || `Falha na solicitação (${response.status}).`);
  return body;
}

function App() {
  const [page, setPage] = useState<Page>("chat");
  const [collapsed, setCollapsed] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light">(
    () => localStorage.getItem("guilherme-ai-theme") === "light" ? "light" : "dark",
  );
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [useLibrary, setUseLibrary] = useState(true);
  const [health, setHealth] = useState<Health | null>(null);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [notes, setNotes] = useState<Note[]>([]);
  const [memoryText, setMemoryText] = useState("");
  const [noteText, setNoteText] = useState("");
  const [toolInput, setToolInput] = useState("2 * (3 + 4)");
  const [toolResult, setToolResult] = useState("");
  const [spreadsheetReport, setSpreadsheetReport] = useState<SheetReport | null>(null);
  const [spreadsheetName, setSpreadsheetName] = useState("relatorio.xlsx");
  const [spreadsheetJson, setSpreadsheetJson] = useState(
    JSON.stringify({ columns: ["Item", "Quantidade"], rows: [["Exemplo", 1]] }, null, 2),
  );
  const [projectDirectory, setProjectDirectory] = useState("");
  const [projectReport, setProjectReport] = useState<ProjectReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [mobileSidebar, setMobileSidebar] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const spreadsheetInput = useRef<HTMLInputElement>(null);
  const messageEnd = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("guilherme-ai-theme", theme);
  }, [theme]);

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await api<Health>("/api/health"));
    } catch {
      setHealth({
        ollamaConnected: false,
        chatModel: "guilherme-ai",
        embedModel: "nomic-embed-text",
        chatModelAvailable: false,
        embedModelAvailable: false,
      });
    }
  }, []);

  const refreshConversations = useCallback(async () => {
    const data = await api<Conversation[]>("/api/conversations");
    setConversations(data);
    return data;
  }, []);

  const selectConversation = useCallback(async (id: number) => {
    setConversationId(id);
    setPage("chat");
    setError("");
    const data = await api<Array<Omit<Message, "sources">>>(`/api/conversations/${id}/messages`);
    setMessages(data.map((message) => ({ ...message, role: message.role as Message["role"] })));
  }, []);

  useEffect(() => {
    void refreshHealth();
    const timer = window.setInterval(() => void refreshHealth(), 30000);
    void refreshConversations()
      .then(async (items) => {
        const selected = items[0] ?? await api<Conversation>("/api/conversations", { method: "POST" });
        if (selected) await selectConversation(selected.id);
      })
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : "Não foi possível iniciar."));
    return () => window.clearInterval(timer);
  }, [refreshConversations, refreshHealth, selectConversation]);

  useEffect(() => {
    messageEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const refreshPageData = useCallback(async (target: Page) => {
    try {
      if (target === "library") setDocuments(await api<DocumentItem[]>("/api/documents"));
      if (target === "memories") setMemories(await api<Memory[]>("/api/memories"));
      if (target === "notes") setNotes(await api<Note[]>("/api/notes"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Falha ao carregar os dados.");
    }
  }, []);

  const navigate = (target: Page) => {
    setPage(target);
    setError("");
    setNotice("");
    setMobileSidebar(false);
    void refreshPageData(target);
  };

  const newConversation = async () => {
    try {
      const created = await api<Conversation>("/api/conversations", { method: "POST" });
      setConversationId(created.id);
      setMessages([]);
      setPage("chat");
      setError("");
      setNotice("");
      await refreshConversations();
      setMobileSidebar(false);
      composer.current?.focus();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível criar a conversa.");
    }
  };

  const sendMessage = async (value: string) => {
    const trimmed = value.trim();
    if (!trimmed || busy || !conversationId) return;
    setError("");
    setNotice("");
    setQuestion("");
    setBusy(true);
    const userMessage: Message = { id: `user-${Date.now()}`, role: "user", content: trimmed };
    const assistantId = `assistant-${Date.now()}`;
    setMessages((current) => [
      ...current,
      userMessage,
      { id: assistantId, role: "assistant", content: "", loading: true },
    ]);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question: trimmed, conversationId, useLibrary }),
      });
      if (!response.ok || !response.body) {
        const body = await response.json().catch(() => ({})) as { error?: string };
        throw new Error(body.error || "Não foi possível iniciar a resposta.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let eventName = "message";
      let completed = false;
      const processEvent = (raw: string) => {
        let data = "";
        for (const line of raw.split("\n")) {
          if (line.startsWith("event:")) eventName = line.slice(6).trim();
          if (line.startsWith("data:")) data += line.slice(5).trim();
        }
        if (!data) return;
        const event = JSON.parse(data) as {
          token?: string;
          answer?: string;
          sources?: Message["sources"];
          error?: string;
        };
        if (eventName === "error") throw new Error(event.error || "Falha ao gerar a resposta.");
        if (eventName === "done") {
          completed = true;
          setMessages((current) => current.map((message) => message.id === assistantId
            ? { ...message, content: event.answer ?? message.content, sources: event.sources, loading: false }
            : message));
          return;
        }
        if (event.token) {
          setMessages((current) => current.map((message) => message.id === assistantId
            ? { ...message, content: message.content + event.token, loading: false }
            : message));
        }
        eventName = "message";
      };

      while (true) {
        const { value: chunk, done } = await reader.read();
        buffer += decoder.decode(chunk, { stream: !done });
        const events = buffer.split("\n\n");
        buffer = events.pop() ?? "";
        for (const event of events) processEvent(event);
        if (done) break;
      }
      if (buffer.trim()) processEvent(buffer);
      if (!completed) throw new Error("A conexão terminou antes da resposta ser salva.");
      await refreshConversations();
    } catch (cause) {
      setMessages((current) => current.filter((message) => message.id !== assistantId));
      setError(cause instanceof Error ? cause.message : "Falha ao conversar com o modelo.");
    } finally {
      setBusy(false);
    }
  };

  const submitMessage = (event: FormEvent) => {
    event.preventDefault();
    void sendMessage(question);
  };

  const uploadFile = async (file?: File) => {
    if (!file) return;
    setError("");
    setNotice("");
    if (file.size > 20 * 1024 * 1024) {
      setError("O arquivo excede o limite de 20 MB.");
      return;
    }
    if (!/\.(txt|pdf)$/i.test(file.name)) {
      setError("Envie um arquivo TXT ou PDF.");
      return;
    }
    setUploading(true);
    try {
      const contentBase64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => reject(new Error("Não foi possível ler o arquivo."));
        reader.onload = () => {
          const result = String(reader.result);
          resolve(result.slice(result.indexOf(",") + 1));
        };
        reader.readAsDataURL(file);
      });
      await api("/api/documents/upload", {
        method: "POST",
        body: JSON.stringify({ filename: file.name, contentBase64 }),
      });
      const result = await api<{ status: string }>("/api/documents/index", {
        method: "POST",
        body: JSON.stringify({ filename: file.name }),
      });
      setNotice(result.status === "indexed" ? `${file.name} enviado e indexado.` : `${file.name}: ${result.status}.`);
      await refreshPageData("library");
      setPage("library");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Falha ao enviar o arquivo.");
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const addRecord = async (kind: "memories" | "notes") => {
    const content = kind === "memories" ? memoryText : noteText;
    if (!content.trim()) return;
    try {
      await api(`/api/${kind}`, { method: "POST", body: JSON.stringify({ content }) });
      if (kind === "memories") {
        setMemoryText("");
        setMemories(await api<Memory[]>("/api/memories"));
      } else {
        setNoteText("");
        setNotes(await api<Note[]>("/api/notes"));
      }
      setNotice(kind === "memories" ? "Memória salva." : "Nota salva.");
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível salvar.");
    }
  };

  const removeRecord = async (kind: "memories" | "notes", id: number) => {
    if (!window.confirm("Confirma a exclusão deste item?")) return;
    try {
      await api(`/api/${kind}/${id}`, { method: "DELETE" });
      if (kind === "memories") setMemories(await api<Memory[]>("/api/memories"));
      else setNotes(await api<Note[]>("/api/notes"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível excluir.");
    }
  };

  const runTool = async (name: "calculator" | "datetime") => {
    setError("");
    setToolResult("");
    try {
      const result = await api<{ result: string | number }>("/api/tools/execute", {
        method: "POST",
        body: JSON.stringify({ name, input: toolInput }),
      });
      setToolResult(String(result.result));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível executar a ferramenta.");
    }
  };

  const analyzeSpreadsheet = async (file?: File) => {
    if (!file) return;
    setError("");
    setNotice("");
    setSpreadsheetReport(null);
    if (file.size > 20 * 1024 * 1024 || !/\.(csv|xlsx)$/i.test(file.name)) {
      setError("Envie um arquivo CSV ou XLSX de até 20 MB.");
      return;
    }
    setUploading(true);
    try {
      const contentBase64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => reject(new Error("Não foi possível ler a planilha."));
        reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
        reader.readAsDataURL(file);
      });
      await api("/api/spreadsheets/upload", {
        method: "POST",
        body: JSON.stringify({ filename: file.name, contentBase64 }),
      });
      const result = await api<SheetReport>("/api/spreadsheets/analyze", {
        method: "POST",
        body: JSON.stringify({ filename: file.name }),
      });
      setSpreadsheetReport(result);
      setNotice(`${file.name} analisado localmente.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível analisar a planilha.");
    } finally {
      setUploading(false);
      if (spreadsheetInput.current) spreadsheetInput.current.value = "";
    }
  };

  const createWorkbook = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setNotice("");
    try {
      const data = JSON.parse(spreadsheetJson) as { columns?: unknown; rows?: unknown };
      if (!Array.isArray(data.columns) || !Array.isArray(data.rows)) {
        throw new Error("O JSON precisa ter as listas columns e rows.");
      }
      const result = await api<{ filename: string }>("/api/spreadsheets/create", {
        method: "POST",
        body: JSON.stringify({
          filename: spreadsheetName,
          columns: data.columns,
          rows: data.rows,
        }),
      });
      setNotice(`${result.filename} criado. Baixe-o abaixo.`);
      setSpreadsheetReport({
        filename: result.filename,
        sheets: [],
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível criar a planilha.");
    }
  };

  const analyzeProject = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setNotice("");
    setProjectReport(null);
    try {
      const result = await api<ProjectReport>("/api/projects/analyze", {
        method: "POST",
        body: JSON.stringify({ directory: projectDirectory }),
      });
      setProjectReport(result);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível analisar o projeto.");
    }
  };

  const deleteConversation = async (event: React.MouseEvent, item: Conversation) => {
    event.stopPropagation();
    if (item.is_default || !window.confirm(`Excluir a conversa "${item.title}"?`)) return;
    try {
      await api(`/api/conversations/${item.id}`, { method: "DELETE" });
      const remaining = await refreshConversations();
      if (conversationId === item.id && remaining[0]) await selectConversation(remaining[0].id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Não foi possível excluir a conversa.");
    }
  };

  const copyText = async (content: string) => {
    try {
      await navigator.clipboard.writeText(content);
      setNotice("Resposta copiada.");
    } catch {
      setError("Não foi possível copiar. Verifique a permissão da área de transferência.");
    }
  };

  const title = page === "chat"
    ? conversations.find((item) => item.id === conversationId)?.title ?? "Nova conversa"
    : ({
      library: "Biblioteca",
      memories: "Memórias",
      notes: "Notas",
      tools: "Ferramentas",
      settings: "Configurações",
      email: "E-mail",
    } as Record<Exclude<Page, "chat">, string>)[page];

  return (
    <div className={`app-shell ${collapsed ? "sidebar-collapsed" : ""} ${mobileSidebar ? "mobile-sidebar-open" : ""}`}>
      {mobileSidebar && <button className="mobile-backdrop" onClick={() => setMobileSidebar(false)} aria-label="Fechar menu" />}
      <aside className="sidebar">
        <div className="brand-row">
          <div className="brand-mark"><Sparkles size={18} /></div>
          {!collapsed && <span className="brand-name">Guilherme <b>AI</b></span>}
          <button className="icon-button sidebar-toggle" onClick={() => setCollapsed(!collapsed)} aria-label="Recolher menu">
            {collapsed ? <Menu size={18} /> : <ChevronDown className="rotate-side" size={17} />}
          </button>
        </div>

        <button className="new-chat-button" onClick={() => void newConversation()} title="Nova conversa">
          <Plus size={17} /> {!collapsed && <span>Nova conversa</span>}
          {!collapsed && <kbd>⌘ K</kbd>}
        </button>

        <div className="nav-list">
          {navigation.map(({ id, label, icon: Icon }) => (
            <button key={id} className={`nav-item ${page === id ? "active" : ""}`} onClick={() => navigate(id)} title={label}>
              <Icon size={17} /><span>{!collapsed && label}</span>
            </button>
          ))}
          <button className={`nav-item ${page === "email" ? "active" : ""}`} onClick={() => navigate("email")} title="E-mail pendente">
            <Mail size={17} /><span>{!collapsed && "E-mail"}</span>
            {!collapsed && <span className="nav-badge">Pendente</span>}
          </button>
        </div>

        {!collapsed && (
          <>
            <div className="sidebar-section-heading"><span>SEU ESPAÇO</span><MoreHorizontal size={15} /></div>
            <button className="nav-item muted-nav" onClick={() => navigate("tools")}><FolderOpen size={17} /><span>Projetos</span><span className="soon-dot" /></button>
            <div className="history-heading"><History size={14} /><span>Recentes</span></div>
            <div className="conversation-list">
              {conversations.map((item) => (
                <button key={item.id} className={`conversation-item ${conversationId === item.id ? "selected" : ""}`} onClick={() => void selectConversation(item.id)}>
                  <span className="conversation-title">{item.title}</span>
                  {!item.is_default && <span className="conversation-delete" onClick={(event) => void deleteConversation(event, item)} role="button" aria-label="Excluir conversa"><X size={13} /></span>}
                </button>
              ))}
            </div>
          </>
        )}

        <div className="sidebar-bottom">
          <button className="nav-item" onClick={() => navigate("settings")} title="Configurações"><Settings size={17} /><span>{!collapsed && "Configurações"}</span></button>
          <div className="profile-row">
            <div className="avatar"><UserRound size={16} /></div>
            {!collapsed && <div className="profile-text"><strong>Guilherme</strong><small>Execução local</small></div>}
            {!collapsed && <button className="icon-button profile-menu" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label="Alternar tema">{theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}</button>}
          </div>
        </div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div className="topbar-title">
            <button className="icon-button mobile-menu" onClick={() => setMobileSidebar(true)} aria-label="Abrir menu"><Menu size={19} /></button>
            <span>{title}</span>
            <button className="icon-button top-chevron" aria-label="Menu de conversa"><ChevronDown size={16} /></button>
          </div>
          <div className="topbar-status">
            <span className={`status-dot ${health?.ollamaConnected ? "online" : "offline"}`} />
            <span>{health?.ollamaConnected ? "Local e privado" : "Ollama desconectado"}</span>
            <ShieldCheck size={15} className="shield-icon" />
          </div>
          <button className="icon-button top-search" title="Pesquisar (em breve)" disabled><Search size={18} /></button>
        </header>

        <section className={`content-area ${page === "chat" ? "chat-content" : "tool-content"}`}>
          {error && <div className="alert error-alert"><CircleHelp size={17} /><span>{error}</span><button onClick={() => setError("")} aria-label="Fechar aviso"><X size={15} /></button></div>}
          {notice && <div className="alert notice-alert"><Check size={17} /><span>{notice}</span><button onClick={() => setNotice("")} aria-label="Fechar aviso"><X size={15} /></button></div>}

          {page === "chat" && (
            <>
              <div className={`conversation-view ${messages.length ? "has-messages" : "empty-conversation"}`}>
                {messages.length === 0 ? (
                  <div className="welcome-panel">
                    <div className="welcome-orb"><Sparkles size={22} /></div>
                    <div className="eyebrow"><span className="eyebrow-line" /> ASSISTENTE LOCAL <span className="eyebrow-line" /></div>
                    <h1>Como posso ajudar<br /><span>hoje?</span></h1>
                    <p>Converse com sua assistente local ou consulte seus documentos com privacidade.</p>
                    <div className="suggestion-grid">
                      <button onClick={() => void sendMessage("Explique em palavras simples como funciona a busca em documentos nesta assistente.")}>
                        <BookOpen size={17} /><span><b>Entender meus documentos</b><small>Faça perguntas sobre a biblioteca</small></span><ArrowUp size={15} />
                      </button>
                      <button onClick={() => void sendMessage("Dê três ideias úteis para organizar minhas tarefas de hoje.")}>
                        <Sparkles size={17} /><span><b>Começar uma conversa</b><small>Peça ideias, explicações ou ajuda</small></span><ArrowUp size={15} />
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="message-list">
                    {messages.map((message) => (
                      <article key={message.id} className={`message-row ${message.role}`}>
                        <div className={`message-avatar ${message.role}`}>
                          {message.role === "assistant" ? <Sparkles size={16} /> : <UserRound size={16} />}
                        </div>
                        <div className="message-body">
                          <div className="message-label">{message.role === "assistant" ? "Guilherme AI" : "Você"}</div>
                          {message.loading && !message.content
                            ? <div className="thinking"><span /><span /><span /><small>pensando localmente</small></div>
                            : <div className="markdown-body"><ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown></div>}
                          {message.role === "assistant" && message.content && (
                            <div className="message-actions">
                              <button onClick={() => void copyText(message.content)} title="Copiar resposta"><Copy size={14} /></button>
                              {message.sources && message.sources.length > 0 && <span>{message.sources.length} fonte(s)</span>}
                            </div>
                          )}
                          {message.sources && message.sources.length > 0 && (
                            <details className="sources-card">
                              <summary><BookOpen size={14} /> Fontes consultadas <ChevronDown size={14} /></summary>
                              {message.sources.map((source, index) => (
                                <div key={`${source.source}-${index}`} className="source-item">
                                  <b>[{index + 1}] {source.source}</b><small>similaridade {source.score.toFixed(3)}</small>
                                  <p>{source.content}</p>
                                </div>
                              ))}
                            </details>
                          )}
                        </div>
                      </article>
                    ))}
                    <div ref={messageEnd} />
                  </div>
                )}
              </div>

              <div className="composer-wrap">
                <form className="composer" onSubmit={submitMessage}>
                  <textarea
                    ref={composer}
                    rows={1}
                    value={question}
                    onChange={(event) => {
                      setQuestion(event.target.value);
                      event.currentTarget.style.height = "auto";
                      event.currentTarget.style.height = `${Math.min(event.currentTarget.scrollHeight, 180)}px`;
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        void sendMessage(question);
                      }
                    }}
                    placeholder="Pergunte qualquer coisa..."
                    maxLength={4000}
                    disabled={busy || !conversationId}
                  />
                  <div className="composer-controls">
                    <div className="composer-left">
                      <button type="button" className="composer-icon" onClick={() => fileInput.current?.click()} title="Anexar TXT ou PDF" disabled={uploading}>
                        {uploading ? <LoaderCircle className="spin" size={17} /> : <Plus size={18} />}
                      </button>
                      <input ref={fileInput} type="file" accept=".txt,.pdf" hidden onChange={(event) => void uploadFile(event.target.files?.[0])} />
                      <span className="composer-divider" />
                      <label className="mode-select">
                        <BookOpen size={14} />
                        <select value={useLibrary ? "library" : "chat"} onChange={(event) => setUseLibrary(event.target.value === "library")} aria-label="Modo de conversa">
                          <option value="library">Biblioteca + chat</option>
                          <option value="chat">Somente chat</option>
                        </select>
                        <ChevronDown size={13} />
                      </label>
                    </div>
                    <div className="composer-right">
                      <span className="model-chip"><span /> {health?.chatModel ?? "guilherme-ai"}</span>
                      <button type="button" className="composer-icon mic-disabled" title="Voz: configuração opcional"><Activity size={17} /></button>
                      <button type="submit" className="send-button" disabled={!question.trim() || busy || !conversationId} aria-label="Enviar mensagem">
                        {busy ? <LoaderCircle className="spin" size={17} /> : <ArrowUp size={18} />}
                      </button>
                    </div>
                  </div>
                </form>
                <div className="composer-footnote"><ShieldCheck size={12} /> Suas conversas ficam neste computador <span>·</span> <span>Shift + Enter para nova linha</span></div>
              </div>
            </>
          )}

          {page === "library" && (
            <div className="management-page">
              <div className="page-heading"><div className="page-icon blue"><BookOpen size={19} /></div><div><h1>Sua biblioteca</h1><p>Adicione documentos para consultar durante as conversas.</p></div></div>
              <div className="upload-card">
                <div className="upload-icon"><Upload size={20} /></div>
                <h2>Importar um documento</h2>
                <p>TXT ou PDF com texto extraível · até 20 MB · processado localmente</p>
                <button className="primary-button" onClick={() => fileInput.current?.click()} disabled={uploading}>
                  {uploading ? <LoaderCircle className="spin" size={16} /> : <Plus size={17} />} Escolher arquivo
                </button>
                <input ref={fileInput} type="file" accept=".txt,.pdf" hidden onChange={(event) => void uploadFile(event.target.files?.[0])} />
              </div>
              <div className="section-title"><h2>Documentos indexados</h2><button className="text-button" onClick={async () => {
                try {
                  await api("/api/documents/reindex", { method: "POST" });
                  setDocuments(await api<DocumentItem[]>("/api/documents"));
                  setNotice("A biblioteca foi reindexada.");
                } catch (cause) {
                  setError(cause instanceof Error ? cause.message : "Falha ao reindexar.");
                }
              }}><History size={14} /> Reindexar</button></div>
              <div className="data-list">
                {documents.length === 0 ? <div className="empty-card">Nenhum documento indexado ainda.</div> : documents.map((document) => (
                  <div className="data-row" key={document.id}>
                    <div className="file-mark"><FileText size={17} /></div><div className="data-main"><strong>{document.fonte}</strong><small>{document.tipo.toUpperCase()} · {document.trechos_atuais} trechos</small></div>
                    <button className="icon-button" title="Remover índice" onClick={async () => {
                      if (!window.confirm("Remover o índice? O arquivo original será mantido.")) return;
                      try {
                        await api(`/api/documents/${document.id}/index`, { method: "DELETE" });
                        setDocuments(await api<DocumentItem[]>("/api/documents"));
                      } catch (cause) { setError(cause instanceof Error ? cause.message : "Falha ao remover índice."); }
                    }}><Trash2 size={15} /></button>
                  </div>
                ))}
              </div>
              <p className="muted-note">PDFs digitalizados como imagem não têm OCR automático. O texto extraído permanece no banco local.</p>
            </div>
          )}

          {page === "memories" && (
            <div className="management-page">
              <div className="page-heading"><div className="page-icon purple"><Hash size={19} /></div><div><h1>Memórias</h1><p>Informações selecionadas podem ser usadas como contexto nas conversas.</p></div></div>
              <form className="record-form" onSubmit={(event) => { event.preventDefault(); void addRecord("memories"); }}>
                <textarea value={memoryText} onChange={(event) => setMemoryText(event.target.value)} maxLength={500} placeholder="Adicione uma memória (até 500 caracteres)" />
                <button className="primary-button" disabled={!memoryText.trim()}><Plus size={16} /> Salvar memória</button>
              </form>
              <div className="section-title"><h2>Memórias salvas <span className="count-pill">{memories.length}</span></h2></div>
              <div className="data-list">{memories.length === 0 ? <div className="empty-card">Nenhuma memória cadastrada.</div> : memories.map((item) => (
                <div className="data-row" key={item.id}><div className="memory-dot"><Hash size={15} /></div><div className="data-main"><strong>{item.content}</strong><small>Memória {item.id}</small></div><button className="icon-button" onClick={() => void removeRecord("memories", item.id)} aria-label="Excluir memória"><Trash2 size={15} /></button></div>
              ))}</div>
            </div>
          )}

          {page === "notes" && (
            <div className="management-page">
              <div className="page-heading"><div className="page-icon amber"><FileText size={19} /></div><div><h1>Notas</h1><p>Rascunhos locais, separados das memórias da assistente.</p></div></div>
              <form className="record-form" onSubmit={(event) => { event.preventDefault(); void addRecord("notes"); }}>
                <textarea value={noteText} onChange={(event) => setNoteText(event.target.value)} placeholder="Escreva uma nota..." />
                <button className="primary-button" disabled={!noteText.trim()}><Plus size={16} /> Salvar nota</button>
              </form>
              <div className="section-title"><h2>Suas notas <span className="count-pill">{notes.length}</span></h2></div>
              <div className="data-list">{notes.length === 0 ? <div className="empty-card">Nenhuma nota cadastrada.</div> : notes.map((item) => (
                <div className="data-row" key={item.id}><div className="file-mark"><FileText size={16} /></div><div className="data-main"><strong>{item.conteudo}</strong><small>Nota {item.id}</small></div><button className="icon-button" onClick={() => void removeRecord("notes", item.id)} aria-label="Excluir nota"><Trash2 size={15} /></button></div>
              ))}</div>
            </div>
          )}

          {page === "tools" && (
            <div className="management-page">
              <div className="page-heading"><div className="page-icon blue"><FlaskConical size={19} /></div><div><h1>Ferramentas</h1><p>Recursos locais seguros, sem execução arbitrária de código.</p></div></div>
              <div className="tool-card">
                <div className="tool-card-heading"><div className="page-icon blue small"><Hash size={16} /></div><div><h2>Calculadora</h2><p>Operações aritméticas avaliadas com segurança.</p></div></div>
                <div className="tool-run-row"><input value={toolInput} onChange={(event) => setToolInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void runTool("calculator"); }} aria-label="Expressão matemática" /><button className="primary-button" onClick={() => void runTool("calculator")}>Calcular <ArrowUp size={15} /></button></div>
                {toolResult && <div className="tool-result"><Check size={15} /> Resultado: <b>{toolResult}</b></div>}
                <button className="subtle-button" onClick={() => void runTool("datetime")}><Clock3 size={15} /> Consultar data e hora locais</button>
              </div>
                <div className="section-title"><h2>Analisar uma planilha</h2></div>
                <div className="tool-card">
                  <div className="tool-card-heading"><div className="page-icon blue small"><FileSpreadsheet size={16} /></div><div><h2>CSV ou Excel</h2><p>Resumo de abas, colunas, valores ausentes, duplicidades e amostra. Processamento local.</p></div></div>
                  <input ref={spreadsheetInput} type="file" accept=".csv,.xlsx" hidden onChange={(event) => void analyzeSpreadsheet(event.target.files?.[0])} />
                  <button className="primary-button" onClick={() => spreadsheetInput.current?.click()} disabled={uploading}>
                    {uploading ? <LoaderCircle className="spin" size={16} /> : <Upload size={15} />} Escolher CSV/XLSX (até 20 MB)
                  </button>
                  {spreadsheetReport && (
                    <div className="analysis-report">
                      <div className="report-heading"><strong>{spreadsheetReport.filename}</strong><a className="text-button" href={`/api/spreadsheets/files/${encodeURIComponent(spreadsheetReport.filename)}`}><Download size={14} /> Baixar XLSX</a></div>
                      {spreadsheetReport.sheets.map((sheet) => (
                        <div className="sheet-summary" key={sheet.sheet}>
                          <h3>{sheet.sheet}</h3>
                          <p>{sheet.rows.toLocaleString("pt-BR")} linhas · {sheet.columns} colunas · {sheet.duplicateRows} duplicadas</p>
                          {sheet.truncated && <small className="muted-note">A análise foi limitada a 100 mil linhas.</small>}
                          {Object.keys(sheet.missingByColumn).length > 0 && <p>Valores ausentes: {Object.entries(sheet.missingByColumn).map(([column, count]) => `${column} (${count})`).join(", ")}</p>}
                          <div className="column-tags">{sheet.columnNames.map((column) => <span key={column}>{column}</span>)}</div>
                          {sheet.sample.length > 0 && <div className="sample-table-wrap"><table><thead><tr>{Object.keys(sheet.sample[0]).map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{sheet.sample.map((row, index) => <tr key={index}>{Object.keys(row).map((column) => <td key={column}>{String(row[column] ?? "—")}</td>)}</tr>)}</tbody></table></div>}
                          {Object.keys(sheet.numericSummary).length > 0 && <details className="numeric-details"><summary>Resumo numérico</summary>{Object.entries(sheet.numericSummary).map(([column, values]) => <p key={column}><b>{column}</b>: min {values.min ?? "—"} · média {values.mean ?? "—"} · max {values.max ?? "—"}</p>)}</details>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="section-title"><h2>Criar uma planilha</h2></div>
                <form className="tool-card create-sheet-form" onSubmit={(event) => void createWorkbook(event)}>
                  <label>Nome do arquivo<input value={spreadsheetName} onChange={(event) => setSpreadsheetName(event.target.value)} maxLength={150} /></label>
                  <label>Dados JSON (colunas e linhas)<textarea value={spreadsheetJson} onChange={(event) => setSpreadsheetJson(event.target.value)} spellCheck={false} /></label>
                  <small className="muted-note">Exemplo: {"{ \"columns\": [\"Nome\", \"Valor\"], \"rows\": [[\"Item\", 10]] }"}. Arquivos existentes nunca são sobrescritos.</small>
                  <button className="primary-button" type="submit"><Plus size={15} /> Criar XLSX</button>
                </form>

                <div className="section-title"><h2>Analisar um projeto</h2></div>
                <div className="tool-card">
                  <div className="tool-card-heading"><div className="page-icon purple small"><FolderOpen size={16} /></div><div><h2>Inventário local</h2><p>Lê somente nomes e extensões. Ignora dependências e arquivos de credenciais; não abre nem executa o código.</p></div></div>
                  <form className="project-form" onSubmit={(event) => void analyzeProject(event)}>
                    <input value={projectDirectory} onChange={(event) => setProjectDirectory(event.target.value)} placeholder={"C:\\Users\\...\\MeuProjeto"} aria-label="Caminho da pasta do projeto" />
                    <button className="primary-button" type="submit" disabled={!projectDirectory.trim()}><Search size={15} /> Analisar</button>
                  </form>
                  {projectReport && (
                    <div className="analysis-report">
                      <div className="report-heading"><strong>{projectReport.directory}</strong><span>{projectReport.filesAnalyzed.toLocaleString("pt-BR")} arquivos identificados</span></div>
                      {projectReport.capped && <p className="muted-note">Análise limitada a 2.000 arquivos.</p>}
                      <p>Tecnologias identificadas: {projectReport.technologies.join(", ") || "não detectadas pelos manifestos"}</p>
                      <div className="column-tags">{Object.entries(projectReport.extensions).map(([extension, count]) => <span key={extension}>{extension}: {count}</span>)}</div>
                      {projectReport.recommendations.length > 0 && <ul className="recommendations">{projectReport.recommendations.map((item) => <li key={item}>{item}</li>)}</ul>}
                      <small className="muted-note">{projectReport.sensitiveFilesSkipped} arquivo(s) com nome sensível ignorado(s). Conteúdo enviado ao modelo: não. Código executado: não.</small>
                    </div>
                  )}
                </div>

                <div className="section-title"><h2>Integrações externas</h2></div>
                <div className="future-grid"><FutureCard icon={Search} title="Pesquisa na internet" text="Desativada para não enviar consultas sem autorização." /></div>
            </div>
          )}

          {page === "settings" && (
            <div className="management-page">
              <div className="page-heading"><div className="page-icon purple"><Settings size={19} /></div><div><h1>Configurações</h1><p>Estado da execução e preferências locais.</p></div></div>
              <div className="settings-card">
                <div className="settings-row"><div><strong>Modo de execução</strong><small>Aplicação e dados neste computador</small></div><span className="setting-status"><ShieldCheck size={14} /> Local</span></div>
                <div className="settings-row"><div><strong>Ollama</strong><small>{health?.ollamaConnected ? "Conectado em 127.0.0.1:11434" : "Não foi possível conectar ao serviço local"}</small></div><span className={`connection-pill ${health?.ollamaConnected ? "connected" : "disconnected"}`}><i />{health?.ollamaConnected ? "Conectado" : "Desconectado"}</span></div>
                <div className="settings-row"><div><strong>Modelo de conversa</strong><small>Um único modelo de chat, contexto limitado a 4.096 tokens</small></div><code>{health?.chatModel ?? "guilherme-ai"}</code></div>
                <div className="settings-row"><div><strong>Embeddings</strong><small>Usados sob demanda quando há documentos indexados</small></div><code>{health?.embedModel ?? "nomic-embed-text"}</code></div>
                <div className="settings-row"><div><strong>Interface</strong><small>Alternar entre tema escuro e claro</small></div><button className="subtle-button" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>{theme === "dark" ? <Sun size={15} /> : <Moon size={15} />} Tema {theme === "dark" ? "claro" : "escuro"}</button></div>
              </div>
              <p className="muted-note">A memória do modelo é gerenciada pelo Ollama. A aplicação solicita um contexto moderado e mantém somente um modelo de chat configurado.</p>
            </div>
          )}

          {page === "email" && (
            <div className="management-page">
              <div className="page-heading"><div className="page-icon amber"><Mail size={19} /></div><div><h1>Consulta de e-mail</h1><p>Integração planejada para leitura, sem enviar ou alterar mensagens.</p></div></div>
              <div className="pending-card"><div className="pending-icon"><ShieldCheck size={21} /></div><div><h2>Aguardando sua autorização</h2><p>Nenhuma conta foi conectada. A integração só será ativada depois da configuração manual do OAuth do Google e da sua autorização.</p><span className="scope-chip">Escopo previsto: gmail.readonly</span></div></div>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

function FutureCard({ icon: Icon, title, text }: { icon: LucideIcon; title: string; text: string }) {
  return <div className="future-card"><Icon size={17} /><div><strong>{title}</strong><small>{text}</small></div><span>EM BREVE</span></div>;
}

export default App;
