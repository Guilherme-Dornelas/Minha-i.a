# Guilherme AI 5.0

Assistente pessoal local em Python, com Ollama, SQLite, pesquisa RAG, importação de TXT/PDF e interface web local. As versões `main.py`, `main_v2.py`, `main_v3.py` e `main_v4.py` foram mantidas; a nova aplicação utiliza `app.py` (terminal) e `web_app.py` (navegador).

## Requisitos

- Windows 11 e Python 3.10 ou superior.
- Ollama instalado e em execução.
- Modelos locais: `guilherme-ai` (chat) e `nomic-embed-text` (embeddings).
- 16 GB de RAM são suficientes para os modelos descritos; os embeddings e a interface não enviam conteúdo a serviços externos.

Confirme os modelos no terminal:

```powershell
ollama list
```

Caso ainda não estejam instalados, baixe-os usando Ollama (`ollama pull llama3.2:3b`, `ollama pull nomic-embed-text`) e crie o modelo personalizado conforme o `Modelfile` que você já utiliza. Não substitua seu modelo personalizado sem conferir suas instruções.

## Instalação

No PowerShell, na pasta do projeto:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Se a pasta `.venv` ainda não existir, crie-a primeiro com `py -m venv .venv`. O banco existente `memory.db` é atualizado de forma não destrutiva ao abrir o programa; mensagens, memórias e trechos antigos são mantidos. Um backup anterior à atualização foi criado em `backups\pre-v5-20261116-1905`.

## Inicialização

- Terminal: `.\run.bat` ou `.\.venv\Scripts\python.exe app.py`
- Interface web: `.\run-web.bat` ou `.\.venv\Scripts\python.exe -m streamlit run web_app.py --server.address 127.0.0.1`

A interface fica disponível em `http://127.0.0.1:8501`. Ela é vinculada ao loopback e não deve ser exposta a uma rede pública.

## Uso no terminal

Digite perguntas normalmente. Os trechos recuperados são mostrados com marcador `[1]`, arquivo e similaridade. Se nenhum trecho ultrapassar o limiar padrão (`0.60`), a aplicação informa que não usou a biblioteca; ajuste opcionalmente com `GUILHERME_AI_MIN_SIMILARITY`.

Comandos:

- `/indexar` indexa TXT/PDF dentro de `biblioteca`; `/indexar arquivo.pdf` indexa um arquivo específico.
- `/reindexar` reconstrói os vetores. Uma falha mantém os registros anteriores do documento.
- `/documentos` lista os documentos; `/remover ID` remove o índice (com confirmação), não o arquivo.
- `/lembrar texto`, `/memorias`, `/esquecer ID`, `/esquecer tudo` (com confirmação).
- `/limpar` apaga somente o histórico (com confirmação).
- `/calc 2 * (3 + 4)` executa apenas aritmética; `/hora` consulta a data e hora locais.
- `/ferramentas` lista os recursos locais disponíveis; `/resumir assunto` resume trechos relevantes da biblioteca.
- `/nota texto`, `/notas`, `/apagar-nota ID` (com confirmação).
- `/voz` inicia uma gravação local opcional.

Memórias são referências persistentes, não treinamento do modelo. O sistema seleciona memórias por correspondência de termos e limita a quantidade inserida no contexto.

## Biblioteca e PDFs

Coloque os arquivos na pasta `biblioteca` ou importe-os pela interface. São aceitos TXT UTF-8/Windows-1252 e PDF com texto extraível. Arquivos com extensão diferente ou fora da pasta autorizada são recusados. PDFs protegidos, vazios ou sem texto extraível geram mensagens explícitas. OCR de páginas digitalizadas não é feito.

O índice identifica alterações por SHA-256 e não cria uma segunda indexação para arquivos idênticos com nomes diferentes. A troca de trechos e metadados ocorre em transação após a extração e geração bem-sucedidas dos embeddings, preservando a indexação anterior se algo falhar.

## Voz (opcional)

Instale as dependências adicionais:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-voice.txt
```

Baixe manualmente um modelo pequeno do Vosk em português e extraia-o em `models\vosk-model-small-pt-0.3` (ou configure `GUILHERME_AI_VOICE_MODEL`). O pacote do modelo não é incluído nem baixado automaticamente. A captura usa o microfone local por até sete segundos e a fala é sintetizada localmente via pyttsx3. Se a configuração ou o microfone não estiverem disponíveis, o chat normal continua funcionando.

## Configuração opcional

- `OLLAMA_HOST`: endereço do Ollama (padrão `http://127.0.0.1:11434`).
- `GUILHERME_AI_MODEL`: modelo de chat (padrão `guilherme-ai`).
- `GUILHERME_AI_EMBED_MODEL`: modelo de embeddings (padrão `nomic-embed-text`).
- `GUILHERME_AI_MIN_SIMILARITY`: limiar de similaridade entre `-1` e `1` (padrão `0.60`, calibrado contra consultas relevantes e não relacionadas no documento de exemplo).
- `GUILHERME_AI_DATABASE` e `GUILHERME_AI_LIBRARY`: caminhos locais alternativos.

## Testes

Com as dependências instaladas, execute:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Os testes unitários não requerem o Ollama. O uso real dos modelos requer Ollama ativo e ambos os modelos configurados. Testes com PDF usam a dependência `pypdf`.

## Limitações conhecidas

- A qualidade da busca RAG depende do modelo de embeddings, do texto extraído e do limiar configurado; ajuste-o com exemplos representativos.
- A geração do modelo pode errar citações apesar das fontes exibidas separadamente na aplicação.
- Não há OCR automático, pesquisa na internet, execução de comandos do sistema, nem leitura arbitrária fora da biblioteca autorizada.
- A interface web mantém a conversa no banco SQLite compartilhado com o terminal.
- A voz depende de modelo Vosk, dispositivo de áudio e configuração manual, e só está disponível no terminal nesta versão.
