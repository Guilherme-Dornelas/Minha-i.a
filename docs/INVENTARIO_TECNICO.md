# Inventário técnico do projeto atual

## Estrutura principal

- Interface moderna: React 18, React DOM 18 e Vite 6 em `frontend/`.
- API moderna: Express 5/TypeScript/Node em `backend/src/`.
- Núcleo Python: pacote `guilherme_ai/`.
- Terminais legados: `app.py`, `web_app.py` e arquivos `main_v*.py`.
- Persistencia: SQLite em `memory.db`.
- Biblioteca local: pasta `biblioteca/`.
- Modelos externos locais: Ollama em `127.0.0.1:11434`.
- Pesquisa: SearXNG em `127.0.0.1:8080/search`.

## Tecnologias

### Python

- requests: HTTP local e web;
- pypdf: leitura de PDF;
- pandas/openpyxl: planilhas;
- streamlit: interface legada;
- sqlite3: persistencia;
- recursos opcionais em manifests separados:
  - OCR: Pillow, pypdfium2, pytesseract;
  - voz: pyttsx3, vosk, sounddevice.

### Node/TypeScript

- Express: API HTTP;
- dotenv: configuração local;
- React/Vite: frontend moderno;
- `tsx` e Node test runner: testes;
- TypeScript compiler: build da API.

## Módulos Python

| Módulo | Função atual | Observações |
|---|---|---|
| `assistant.py` | conversa, memória, recuperação e classificação web | usa Ollama sob demanda |
| `tools.py` | calculadora, data/hora, pesquisa e fetch seguro | possui registry local |
| `web_worker.py` | bridge JSON entre Node e Python | contém algumas operações duplicadas |
| `database.py` | SQLite e migração de conversas | banco compartilhado |
| `documents.py` | TXT/PDF, embeddings e busca na biblioteca | OCR opcional |
| `gmail.py` | classificação e parsing Gmail | envio confirmado na API Node |
| `analysis.py` | planilhas e análise estática de projetos | não executa código |
| `voice.py` | fala e reconhecimento locais opcionais | dependências separadas |
| `time_context.py` | datas locais São Paulo | usado em decisões web/Gmail |

## Módulos Node

- `server.ts`: API, worker, streaming, upload e painéis existentes.
- `gmail.ts`: OAuth, scopes, allowlist, criptografia e confirmações Gmail.
- `validation.ts`: validação de uploads e parâmetros HTTP.

## Funcionalidades existentes

- conversa por streaming com Ollama;
- histórico separado por conversa;
- memória pessoal;
- notas;
- biblioteca TXT/PDF com busca semântica;
- OCR PDF opt-in;
- pesquisa SearXNG local;
- leitura segura de páginas com proteção contra SSRF;
- Gmail leitura/composição/envio confirmado;
- análise/geração de XLSX;
- análise estática de projetos;
- tema claro/escuro;
- terminal legado e voz opcional.

## Banco de dados

Tabelas legadas e novas já usam `memory.db`:

- `mensagens`;
- `memorias`;
- `conhecimentos`;
- `documentos`;
- `notas`;
- `conversations`;
- `conversation_messages`;
- `gmail_credentials`.

O projeto nao possui banco separado para o frontend.

## Dependencias e problemas identificados

- As dependencias Python declaradas estavam ausentes no ambiente atual; `pypdf`, pandas e openpyxl serão restauradas conforme `requirements.txt`.
- Há dois caminhos de seleção de ferramentas: registry do CLI e despacho manual no worker.
- O worker Python cria uma nova instância curta por ação; isso evita serviço ocioso, mas repete inicialização de utilitários.
- A interface principal depende de Ollama/SearXNG e informa corretamente os modos desativados.
- OAuth Gmail usa credenciais no ambiente do servidor e tokens criptografados no SQLite.
- Nenhuma integração Google Drive/Docs/Sheets, GitHub, Gemini, Meta ou ROS 2 existe no núcleo atual.
- Não existe ainda painel de métricas persistidas.
- Voz, OCR e análises pesadas são opcionais, mas precisam estar ligadas a limites configuráveis e descarregamento.

## Segurança atual

- API vinculada ao loopback.
- validação de origem;
- confirmação Gmail antes do envio;
- tokens Gmail armazenados criptografados;
- proteção SSRF no fetch web;
- conteúdo web/biblioteca marcado como não confiável no prompt;
- análise de projetos sem executar código;
- uploads com limite e validação de nome/tipo.

## Critérios da etapa 1

Um módulo integrado deve aparecer no mesmo registro central, declarar a fonte (local/internet/integracao), indicar quando e exige confirmação e validar o resultado. Isso será aplicado progressivamente a cada nova integração.
