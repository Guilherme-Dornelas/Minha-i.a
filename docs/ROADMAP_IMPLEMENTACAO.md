# Roadmap de implementação do Neno

## Estado geral

O projeto ja possui conversa local com Ollama, memoria, biblioteca TXT/PDF, pesquisa SearXNG, leitura segura de paginas, Gmail basico, análise de planilhas/projetos e interface React. O plano abaixo preserva essas funções e evolui os módulos sem manter tudo ativo ao mesmo tempo.

## Etapa 1 — Arquitetura e diagnóstico

Status: em andamento.

- [x] Inventariar tecnologias, módulos, dependencias e interfaces.
- [x] Registrar todas as ferramentas em um componente central.
- [x] Definir metadados de origem, permissao e confirmacao.
- [x] Separar conteudo da biblioteca e da internet no contexto.
- [x] Validar a pesquisa web/SearXNG e a leitura segura de paginas.
- [x] Corrigir o fluxo atual de fontes sem duplicar banco ou modelos.
- [x] Documentar arquitetura e inventario.
- [x] Confirmar testes da etapa.

### Evidência da Etapa 1

- Python: 70 testes executados, todos aprovados.
- TypeScript: 9 testes executados, todos aprovados.
- Build: API e frontend compilados com sucesso.
- Dependências Python declaradas em `requirements.txt` foram restauradas no ambiente.

Entregas principais:

- `docs/INVENTARIO_TECNICO.md`;
- `docs/ARQUITETURA_NENO.md`;
- registro central de ferramentas;
- teste de que ferramentas locais usam o mesmo registry.

## Etapa 2 — Painel e observabilidade

- [ ] Criar tabelas aditivas no SQLite atual.
- [ ] Registrar tempo, sucesso, falha e integração usada.
- [ ] Registrar métricas sanitizadas de CPU/RAM/resposta.
- [ ] Criar API de resumo operacional.
- [ ] Adicionar painel React sem depender de processo em segundo plano.
- [ ] Adicionar limites configuráveis de memória/processamento.
- [ ] Testar contagem, limpeza sanitizada e limites.

## Etapa 3 — Integrações

### 3.1 Gmail multi-contas

- [ ] Trocar credencial unica por contas e aliases.
- [ ] Selecionar conta ativa por conversa/solicitacao.
- [ ] Mover refresh tokens para armazenamento seguro do SQLite.
- [ ] Revisar confirmação para envio, exclusao e operações sensíveis.
- [ ] Testar seleção, troca e isolamento entre contas.

### 3.2 Google Drive, Docs e Sheets

- [ ] OAuth compartilhado por conta Google autorizada.
- [ ] Leitura, busca e metadados do Drive.
- [ ] Leitura e exportação de Docs.
- [ ] Leitura e atualizacao controlada de Sheets.
- [ ] Confirmacao para escrita, compartilhamento e exclusao.
- [ ] Testes unitarios de parsing e confirmação.

### 3.3 GitHub

- [ ] Integração via token opcional em armazenamento seguro.
- [ ] Busca de repositorios, issues e pull requests autorizados.
- [ ] Leitura de arquivos e diffs somente de repositorios permitidos.
- [ ] Resumo heurístico sem executar código.
- [ ] Limites de tamanho e quantidade.
- [ ] Testes com mocks e fixtures.

### 3.4 Gemini opcional e visão local

- [ ] Adaptador opcional para Gemini com consentimento explicito.
- [ ] Parametros de provedor centralizados.
- [ ] Cliente de visão local descarregavel sob demanda.
- [ ] Importacao opcional de modelos e limites de memoria.
- [ ] Testar ausência de configuração, falha e download proibido.

### 3.5 Personalidade e voz

- [ ] Perfis de personalidade configuraveis.
- [ ] Interface para escolha de voz e intensidade.
- [ ] Captura e sintese locais opcionais já separadas.
- [ ] Descarregar modelos de voz após uso.
- [ ] Testes sem microfone ou dispositivo real.

### 3.6 APIs autorizadas da Meta

- [ ] Avaliar escopos necessários por integração.
- [ ] OAuth/configuração segura por conta.
- [ ] Leitura e envio com confirmação individual.
- [ ] Respeitar limites oficiais e revogação.
- [ ] Testes de escopo, rejeicao e preview.

## Etapa 4 — Robótica

- [ ] Arquitetura isolada para ROS 2.
- [ ] Adaptação de comandos em linguagem para ações estruturadas.
- [ ] Validação independente antes da execução.
- [ ] Gazebo como primeiro ambiente suportado.
- [ ] Modo simulação obrigatório nas primeiras implementacoes.
- [ ] Lista explicita de ações permitidas e limites fisicos.
- [ ] Confirmacao humana para toda operação real.
- [ ] Testes de validação, comandos proibidos e interrupcao.

## Segurança transversal

- nenhum serviço pago sera ativado sem autorizacao;
- nenhuma credencial sera enviada ao frontend ou inserida no GitHub/log;
- decisão do modelo sera separada da execução;
- confirmacao sera obrigatoria para envio, publicação, compartilhamento e exclusao;
- repositorios nao executarao arquivos ou scripts encontrados;
- integração nao usada ficara inativa;
- consumo sera monitorado e limitado;
- todos os modulos terao testes unitarios e documentacao.
