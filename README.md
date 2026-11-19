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
- Importação e indexação local de TXT e PDF com texto extraível, até 20 MB.
- Gerenciamento de memórias e notas.
- Calculadora aritmética segura e consulta da data/hora locais.
- Resumo de CSV/XLSX (até 20 MB, 100 mil linhas por aba), com dados ausentes, duplicidades e estatísticas numéricas.
- Criação de XLSX a partir de dados JSON, com validação, fórmulas limitadas e sem sobrescrever arquivos existentes.
- Inventário local de projetos: identifica manifestos e extensões sem ler conteúdo de código nem executar arquivos.
- Tema escuro/claro, layout responsivo e indicador de conexão/modelos.
- Banco SQLite compartilhado com o aplicativo Python.

A interface e a API são vinculadas ao loopback (`127.0.0.1`) e não foram feitas para exposição em rede pública. Documentos e dados permanecem locais. A aplicação não executa código contido em documentos nem envia o conteúdo da biblioteca a serviços externos.

## Execução leve

- Mantém o modelo Llama 3.2 3B já instalado pelo usuário; nenhum modelo maior é baixado.
- Usa contexto de 4.096 tokens e solicita retenção do modelo de conversa por dois minutos.
- Embeddings são solicitados apenas quando há documentos indexados e usam retenção curta (`30s`).
- O comportamento final de RAM e velocidade depende da configuração do Ollama e do hardware.

## Funcionalidades ainda pendentes

- A criação de planilhas gera uma aba e não gera gráficos automaticamente; análises de projeto são inventário/recomendações heurísticas, não revisão de código.
- Pesquisa na internet fica desativada para não enviar consultas sem autorização.
- Gmail está pendente. Não há OAuth configurado; só será ativado após configuração e autorização manual, com escopo de leitura.
- A voz permanece opcional e disponível apenas no terminal legado.
- PDFs digitalizados como imagem não têm OCR automático.

## Terminal e interface antiga

- Terminal Python: `python app.py` ou `./run.bat`.
- Interface Streamlit anterior: `python -m streamlit run web_app.py --server.address 127.0.0.1` ou `./run-web.bat` (endereço `http://127.0.0.1:8501`).

Comandos do terminal: `/ajuda`, `/indexar`, `/reindexar`, `/documentos`, `/remover ID`, `/lembrar texto`, `/memorias`, `/esquecer ID`, `/limpar`, `/calc expressão`, `/hora`, `/ferramentas`, `/resumir assunto`, `/nota texto`, `/notas`, `/apagar-nota ID` e `/voz`.

## Dados e backup

O SQLite existente (`memory.db`) e a pasta `biblioteca` são preservados. A nova interface cria tabelas próprias sem apagar as tabelas antigas. Um backup pré-modernização foi criado em `backups/pre-modernization-20261117-2251/`.

## Testes

```bash
python -m unittest discover -s tests -v
npm test
npm run build
```

Os testes unitários não exigem Ollama; a conversa real e a indexação precisam do serviço local e dos modelos instalados.
