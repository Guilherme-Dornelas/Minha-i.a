# Arquitetura do Neno

## Objetivo

O Neno e uma aplicacao local composta por uma interface React, uma API Node/Express e modulos Python. A arquitetura final separa decisao, contexto e execucao: o modelo decide ou sugere uma operacao, mas o codigo autorizador valida entrada, permissao, alcance e confirmacao antes de executar.

## Fluxo principal

1. React envia uma solicitacao a API Node.
2. A API valida a origem, o tamanho e os identificadores.
3. A API inicia um processo Python sob demanda para a acao solicitada.
4. Modulos Python recuperam memoria, documentos locais e fontes web separadamente.
5. A API consulta o Ollama local e envia um stream para a interface.
6. Integracoes externas executam apenas quando configuradas e autorizadas.

O Ollama, os embeddings, o SearXNG e integrações opcionais devem ser iniciados ou carregados sob demanda. O processo Python atual e curto e acionado por cada ação; nao cria um serviço pesado permanente.

## Camadas

### Interface

- React/TypeScript em `frontend/src`.
- Mostra conversas, biblioteca, ferramentas, Gmail e estado do sistema.
- Nunca recebe ou persiste credenciais de provedores.

### API e seguranca

- Node/Express em `backend/src/server.ts`.
- Mantem a aplicacao no loopback por padrao.
- Valida uploads, nomes de arquivo, roteiros, identificadores e origens.
- Cria processos Python sob demanda.
- Intermedia OAuth e confirmações de Gmail.

### Worker Python

- `guilherme_ai/web_worker.py` recebe JSON por stdin e devolve JSON por stdout.
- Deve delegar todas as operações a um registro central de ferramentas.
- E o ponto de unificação para memoria, biblioteca, ferramentas locais e integracoes futuras.

### Modelo e conhecimento

- Ollama local para conversa e classificacao estrutural.
- SQLite em `memory.db` como fonte única de dados locais.
- Biblioteca local em `biblioteca/` e índice vetorial leve em SQLite.
- O modelo de embeddings pode ser mantido por poucos minutos pelo Ollama e nao deve ser iniciado sem documentos.

### Ferramentas

Toda ferramenta deve registrar nome, descrição, categoria, origem, operação sensível, permissões e handler. O registro inicial contém calculadora, data/hora, pesquisa web e leitura segura de páginas. Integrações futuras serão registradas no mesmo componente.

Regras:

- codigo encontrado em repositórios nunca sera executado;
- operações de envio, publicação ou exclusao exigem confirmacao;
- tokens ficam fora do frontend e dos logs;
- pesquisa web usa somente fontes HTTP(S) publicas com protecao SSRF;
- fontes da biblioteca são marcadas separadamente de fontes da internet;
- cada integração será inicializada sob demanda.

## Fontes de contexto

Existem dois tipos de fonte, com marcadores distintos no prompt:

- Biblioteca local: marcadores `[1]`, `[2]`, etc.
- Internet: marcadores `[W1]`, `[W2]`, paginas `[P1]`, `[P2]`.

A recuperação da biblioteca só ocorre quando `useLibrary=true`. A internet só ocorre quando a classificação identifica necessidade atual ou o usuario pede explicitamente. Falhas de busca e pagina sao informadas sem serem confundidas com confirmacao.

## Persistencia

O SQLite existente permanece em `memory.db`. Novas tabelas são aditivas:

- conversas e mensagens;
- memorias e notas;
- documentos e chunks;
- credenciais Gmail criptografadas;
- no futuro, métricas operacionais, contas, integrações e histórico sanitizado.

Nao sera criado banco paralelo para o painel.

## Observabilidade

Etapa 2 adicionará tabelas existentes no mesmo SQLite para registrar:

- evento da operacao;
- integração utilizada;
- duração;
- resultado e código de falha sanitizado;
- consumo aproximado de CPU/RAM quando disponível;
- tamanho de resposta;
- sem tokens, credenciais, corpo completo de emails ou conteudo de prompts sensíveis.

## Limites leves

- pesquisa web: até 10 resultados, timeout curto e leitura limitada a 1 MB/12 mil caracteres;
- contexto da conversa: limite configurado;
- memoria embutida: no máximo configurado;
- OCR e voz: instalaveis separadamente e carregados apenas sob chamada;
- embeddings: usados somente com documentos relevantes;
- visão, voz e robótica: módulos independentes;
- limites de memoria/CPU podem ser configurados por ambiente sem manter serviços ociosos.

## Evolucao futura

- Gmail multi-contas;
- Google Drive, Docs e Sheets;
- GitHub;
- Gemini opcional;
- visão computacional local;
- personalidade e voz na interface;
- APIs da Meta;
- ROS 2/Gazebo em modulo isolado e somente em simulacao inicial.
