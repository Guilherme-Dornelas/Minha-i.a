# Guilherme AI

Assistente pessoal local com Ollama, Llama 3.2 3B, embeddings locais, SQLite e uma nova interface em React/TypeScript. O terminal Python e a interface Streamlit anteriores continuam disponíveis.

## Requisitos

- Windows 11, Node.js 20 ou superior e Python 3.10 ou superior.
- Ollama instalado e em execução.
- Modelo de conversa `guilherme-ai` (Llama 3.2 3B) e modelo de embeddings `nomic-embed-text`.

Confira os modelos com `ollama list`. A aplicação não baixa modelos automaticamente.

## Iniciar a nova interface

No Git Bash, na pasta do projeto:

```bash
py -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
npm install
cp .env.example .env
npm run dev
```

Abra `http://127.0.0.1:5173`. O Ollama precisa continuar ativo em `http://127.0.0.1:11434`. O backend Node fica em `127.0.0.1:8000`; ele delega persistência, RAG e ferramentas ao Python existente. Os dois servidores de desenvolvimento são encerrados com `Ctrl+C`.

Se você usa `llama3.2:3b` sem o alias `guilherme-ai`, ajuste `GUILHERME_AI_MODEL=llama3.2:3b` no `.env`. Nunca coloque credenciais no `.env.example`.

Para produção local:

```bash
npm run build
npm start
```

Abra `http://127.0.0.1:8000`. Também é possível iniciar os servidores de desenvolvimento pelo `run-modern.bat` no Windows.

## Recursos já disponíveis na nova interface

- Conversas com histórico separado e respostas em streaming.
- Migração não destrutiva do histórico antigo para a conversa anterior.
- Busca opcional na biblioteca, com fontes e similaridade exibidas.
- Pesquisa automática de informações atuais pelo SearXNG local, com links das fontes.
- Integração Gmail opcional: pesquisar/listar e ler mensagens, preparar rascunhos e enviar somente após prévia e confirmação explícita.
- Provedor de conversa selecionável: Ollama local (padrão) ou Gemini Developer API via `@google/genai`; Gemini usa streaming SSE e só é iniciado quando selecionado.
- Cada resposta registra e exibe o provedor realmente utilizado, inclusive ao reabrir o histórico; respostas antigas sem metadado aparecem como provedor não registrado.
- Importação e indexação local de TXT e PDF até 20 MB; OCR opcional para PDFs digitalizados.
- Gerenciamento de memórias e notas.
- Calculadora aritmética segura e consulta da data/hora locais.
- Resumo de CSV/XLSX (até 20 MB, 100 mil linhas por aba), com dados ausentes, duplicidades e estatísticas numéricas.
- Criação de XLSX com várias abas e gráficos automáticos quando há categorias e valores numéricos; validação, fórmulas limitadas e sem sobrescrever arquivos existentes.
- Análise estática local de projetos: inventaria manifestos e extensões e verifica sintaxe Python sem executar código ou enviá-lo ao modelo.
- Tema escuro/claro, layout responsivo e indicador de conexão/modelos.
- Banco SQLite compartilhado com o aplicativo Python.

A interface e a API são vinculadas ao loopback (`127.0.0.1`) e não foram feitas para exposição em rede pública. Com Ollama, documentos e dados permanecem locais. Quando a pesquisa web é acionada, a consulta é enviada ao SearXNG configurado e aos mecanismos habilitados nessa instância; os trechos retornados são enviados ao provedor de conversa selecionado. A aplicação não executa código contido em documentos. O conteúdo da biblioteca, memórias, histórico e e-mails Gmail só são encaminhados ao Gemini depois de autorização explícita no compositor. Com Ollama, operações Gmail enviam o conteúdo necessário somente ao modelo local. Corpos de e-mail não são persistidos diretamente; a resposta gerada pode conter trechos e, como as demais respostas, fica no histórico da conversa.

## Execução leve

- Mantém o modelo Llama 3.2 3B já instalado pelo usuário; nenhum modelo maior é baixado.
- Usa contexto de 4.096 tokens e solicita retenção do modelo de conversa por dois minutos.
- Embeddings são solicitados apenas quando há documentos indexados e usam retenção curta (`30s`).
- O comportamento final de RAM e velocidade depende da configuração do Ollama e do hardware.

## Limites e integrações pendentes

- Análises de projeto oferecem inventário, recomendações heurísticas e verificação de sintaxe Python; não são revisão completa de código.
- Pesquisa na internet usa o SearXNG local em `http://127.0.0.1:8080/search` por padrão. O JSON precisa estar habilitado no SearXNG. Configure `SEARXNG_URL` no `.env` se o endereço for diferente; não é necessária API Key. A busca automática é orientada por uma classificação estruturada local e por sinais explícitos de atualidade; o modelo também recebe a data e hora locais para interpretar referências temporais. Os resultados podem estar incompletos; confira as fontes.
- Para ativar o Gmail, copie as variáveis Gmail do `.env.example` para `.env`, configure um cliente OAuth do tipo aplicativo para computador/web local no Google Cloud e cadastre `http://127.0.0.1:8000/api/gmail/oauth/callback` como URI de redirecionamento. Preencha `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` e `GMAIL_ALLOWED_EMAIL` (a conta autorizada); gere `GMAIL_TOKEN_ENCRYPTION_KEY` com `node -e "console.log(require('node:crypto').randomBytes(32).toString('base64'))"`. Reinicie `npm run dev` e conecte a conta na página Gmail. A conta autorizada é comparada com a lista permitida e os tokens são protegidos com AES-256-GCM no SQLite local. O consentimento pede apenas `gmail.readonly` e `gmail.send`; pesquisar, listar, ler e compor não envia mensagens. Um envio só ocorre ao revisar a prévia e clicar em “Confirmar e enviar agora”. A autorização OAuth e o envio real dependem da configuração local e não são testados pela suíte automatizada.
- Para usar o Gemini, configure `GEMINI_API_KEY` e `GUILHERME_AI_GEMINI_MODEL` somente no `.env` local do backend. A chave não é enviada ao frontend nem ao worker Python. Selecione “Gemini — Nuvem” no compositor: a pergunta será processada pela API Gemini. Histórico, memórias, biblioteca e conteúdo Gmail não são enviados sem marcar a autorização explícita daquela mensagem; a autorização é limpa após o envio. Ollama continua como padrão. O uso real da API pode consumir cota e não é exercitado nos testes automatizados.
- A voz permanece opcional e disponível apenas no terminal legado.
- OCR não é executado automaticamente. Para usá-lo, instale `requirements-ocr.txt`, instale o Tesseract OCR com os idiomas português e inglês e marque a opção na biblioteca; o processamento continua local e é limitado a 100 páginas por PDF.

## Terminal e interface antiga

- Terminal Python: `python app.py` ou `./run.bat`.
- Interface Streamlit anterior: `python -m streamlit run web_app.py --server.address 127.0.0.1` ou `./run-web.bat` (endereço `http://127.0.0.1:8501`).

Comandos do terminal: `/ajuda`, `/indexar`, `/reindexar`, `/documentos`, `/remover ID`, `/lembrar texto`, `/memorias`, `/esquecer ID`, `/limpar`, `/calc expressão`, `/hora`, `/pesquisar consulta`, `/ferramentas`, `/resumir assunto`, `/nota texto`, `/notas`, `/apagar-nota ID` e `/voz`.

## Dados e backup

O SQLite existente (`memory.db`) e a pasta `biblioteca` são preservados localmente. O banco não é versionado; a nova interface cria tabelas próprias sem apagar as tabelas antigas. Um backup pré-modernização foi criado em `backups/pre-modernization-20261117-2251/`.

## Testes

```bash
python -m unittest discover -s tests -v
npm test
npm run build
```

Os testes unitários não exigem Ollama nem SearXNG; a conversa real precisa dos modelos instalados, e a pesquisa integrada requer o SearXNG ativo com JSON habilitado.
