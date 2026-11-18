
import requests
import sqlite3
import json
import math
from pathlib import Path

# ==========================================
# GUILHERME AI 4.0 - SISTEMA RAG
# ==========================================

MODEL = "guilherme-ai"
EMBED_MODEL = "nomic-embed-text"

CHAT_URL = "http://localhost:11434/api/chat"
EMBED_URL = "http://localhost:11434/api/embed"

DATABASE = "memory.db"
KNOWLEDGE_DIR = Path("biblioteca")

MAX_CONTEXT_MESSAGES = 6
MAX_MEMORIES = 10
CHUNK_SIZE = 700
CHUNK_OVERLAP = 100
TOP_K = 4


# ==========================================
# 1. BANCO DE DADOS
# ==========================================

def conectar_banco():

    conexao = sqlite3.connect(DATABASE)
    conexao.row_factory = sqlite3.Row

    conexao.execute("""
        CREATE TABLE IF NOT EXISTS mensagens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conexao.execute("""
        CREATE TABLE IF NOT EXISTS memorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conexao.execute("""
        CREATE TABLE IF NOT EXISTS conhecimentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fonte TEXT NOT NULL,
            conteudo TEXT NOT NULL,
            embedding TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conexao.commit()

    return conexao


# ==========================================
# 2. GERACAO DE EMBEDDINGS
# ==========================================

def gerar_embeddings(textos):

    resposta = requests.post(
        EMBED_URL,
        json={
            "model": EMBED_MODEL,
            "input": textos
        },
        timeout=300
    )

    resposta.raise_for_status()

    return resposta.json()["embeddings"]


# ==========================================
# 3. DIVIDIR DOCUMENTOS EM TRECHOS
# ==========================================

def dividir_texto(texto):

    texto = " ".join(texto.split())

    trechos = []

    inicio = 0

    while inicio < len(texto):

        fim = inicio + CHUNK_SIZE

        trecho = texto[inicio:fim].strip()

        if trecho:
            trechos.append(trecho)

        if fim >= len(texto):
            break

        inicio = fim - CHUNK_OVERLAP

    return trechos


# ==========================================
# 4. INDEXAR DOCUMENTOS
# ==========================================

def indexar_documentos(conexao):

    KNOWLEDGE_DIR.mkdir(exist_ok=True)

    arquivos = list(KNOWLEDGE_DIR.rglob("*.txt"))

    if not arquivos:

        print("\nNenhum arquivo TXT encontrado.")
        return

    total = 0

    for arquivo in arquivos:

        print(f"\nLendo: {arquivo.name}")

        try:

            try:
                texto = arquivo.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                texto = arquivo.read_text(encoding="cp1252")

            trechos = dividir_texto(texto)

            if not trechos:
                print("Documento vazio. Ignorado.")
                continue

            # Remove os registros anteriores
            # dessa mesma fonte para evitar duplicacao.

            conexao.execute(
                "DELETE FROM conhecimentos WHERE fonte = ?",
                (str(arquivo),)
            )

            conexao.commit()

            # Processa pequenos lotes para economizar RAM.

            for inicio in range(0, len(trechos), 16):

                lote = trechos[inicio:inicio + 16]

                embeddings = gerar_embeddings(lote)

                for trecho, embedding in zip(lote, embeddings):

                    conexao.execute(
                        """
                        INSERT INTO conhecimentos
                        (fonte, conteudo, embedding)
                        VALUES (?, ?, ?)
                        """,
                        (
                            str(arquivo),
                            trecho,
                            json.dumps(embedding)
                        )
                    )

                conexao.commit()

            total += len(trechos)

            print(
                f"Documento indexado: {len(trechos)} trechos."
            )

        except requests.exceptions.RequestException as erro:

            print(f"Erro ao gerar embeddings: {erro}")

        except (OSError, ValueError) as erro:

            print(f"Erro ao ler documento: {erro}")

    print("\n================================")
    print("INDEXACAO CONCLUIDA!")
    print("Total de trechos:", total)
    print("================================")


# ==========================================
# 5. COMPARAR SIMILARIDADE
# ==========================================

def similaridade(vetor_a, vetor_b):

    produto = sum(
        a * b for a, b in zip(vetor_a, vetor_b)
    )

    norma_a = math.sqrt(sum(a * a for a in vetor_a))
    norma_b = math.sqrt(sum(b * b for b in vetor_b))

    if norma_a == 0 or norma_b == 0:
        return 0

    return produto / (norma_a * norma_b)


# ==========================================
# 6. PESQUISAR NA BIBLIOTECA
# ==========================================

def pesquisar_conhecimento(conexao, pergunta):

    pergunta_embedding = gerar_embeddings([pergunta])[0]

    registros = conexao.execute(
        """
        SELECT id, fonte, conteudo, embedding
        FROM conhecimentos
        """
    ).fetchall()

    resultados = []

    for registro in registros:

        vetor = json.loads(registro["embedding"])

        pontuacao = similaridade(
            pergunta_embedding,
            vetor
        )

        resultados.append({
            "fonte": registro["fonte"],
            "conteudo": registro["conteudo"],
            "pontuacao": pontuacao
        })

    resultados.sort(
        key=lambda item: item["pontuacao"],
        reverse=True
    )

    return resultados[:TOP_K]


# ==========================================
# 7. MEMORIA DE LONGO PRAZO
# ==========================================

def carregar_memorias(conexao):

    registros = conexao.execute(
        """
        SELECT content
        FROM memorias
        ORDER BY id DESC
        LIMIT ?
        """,
        (MAX_MEMORIES,)
    ).fetchall()

    return [registro["content"] for registro in registros]


# ==========================================
# 8. HISTORICO DE CONVERSAS
# ==========================================

def carregar_historico(conexao):

    registros = conexao.execute(
        """
        SELECT role, content
        FROM mensagens
        ORDER BY id DESC
        LIMIT ?
        """,
        (MAX_CONTEXT_MESSAGES,)
    ).fetchall()

    return [
        {
            "role": registro["role"],
            "content": registro["content"]
        }
        for registro in reversed(registros)
    ]


def salvar_mensagem(conexao, role, content):

    conexao.execute(
        """
        INSERT INTO mensagens (role, content)
        VALUES (?, ?)
        """,
        (role, content)
    )

    conexao.commit()


# ==========================================
# 9. GERAR RESPOSTA COM RAG
# ==========================================

def conversar(conexao, pergunta):

    try:

        # Pesquisa os documentos relevantes.

        resultados = pesquisar_conhecimento(
            conexao,
            pergunta
        )

        # Organiza os documentos encontrados.

        if resultados:

            documentos = "\n\n".join(
                f"Fonte: {item['fonte']}\n"
                f"Conteudo: {item['conteudo']}"
                for item in resultados
            )

        else:

            documentos = (
                "Nenhum trecho de documento foi encontrado."
            )

        # Recupera as memorias pessoais.

        memorias = carregar_memorias(conexao)

        texto_memorias = "\n".join(
            f"- {memoria}" for memoria in memorias
        )

        # Monta as instrucoes do modelo.

        sistema = f"""
Voce e a Guilherme AI.

Responda em portugues brasileiro.
Seja clara, didatica e organizada.
Nao invente informacoes.

MEMORIAS DO USUARIO:
{texto_memorias or "Nenhuma memoria cadastrada."}

DOCUMENTOS RECUPERADOS:
{documentos}

REGRAS SOBRE DOCUMENTOS:
- Utilize os documentos quando forem relevantes.
- Nao invente informacoes que nao estejam neles.
- Diferencie informacoes documentais de conhecimento geral.
- Se nao encontrar a resposta nos documentos,
  informe que nao encontrou.
- Identifique as fontes utilizadas quando possivel.
"""

        mensagens = [
            {
                "role": "system",
                "content": sistema
            }
        ]

        mensagens.extend(carregar_historico(conexao))

        mensagens.append({
            "role": "user",
            "content": pergunta
        })

        resposta = requests.post(
            CHAT_URL,
            json={
                "model": MODEL,
                "messages": mensagens,
                "stream": False,
                "keep_alive": "2m",
                "options": {
                    "temperature": 0.3,
                    "num_ctx": 4096
                }
            },
            timeout=300
        )

        resposta.raise_for_status()

        conteudo = resposta.json()["message"]["content"]

        salvar_mensagem(conexao, "user", pergunta)

        salvar_mensagem(conexao, "assistant", conteudo)

        return conteudo

    except requests.exceptions.ConnectionError:

        return "Erro: verifique se o Ollama esta funcionando."

    except requests.exceptions.Timeout:

        return "Tempo de processamento excedido."

    except requests.exceptions.HTTPError as erro:

        return f"Erro HTTP: {erro}"

    except (KeyError, ValueError) as erro:

        return f"Erro ao processar os dados: {erro}"

    except requests.exceptions.RequestException as erro:

        return f"Erro de comunicacao: {erro}"


# ==========================================
# 10. INTERFACE
# ==========================================

def mostrar_fontes(conexao):

    fontes = conexao.execute(
        """
        SELECT DISTINCT fonte
        FROM conhecimentos
        ORDER BY fonte
        """
    ).fetchall()

    print("\n===== DOCUMENTOS INDEXADOS =====")

    if not fontes:
        print("Nenhum documento indexado.")
        return

    for fonte in fontes:
        print("-", fonte["fonte"])

    print("================================")


def iniciar_aplicacao():

    conexao = conectar_banco()

    KNOWLEDGE_DIR.mkdir(exist_ok=True)

    print("\n=============================================")
    print("       GUILHERME AI - VERSAO 4.0")
    print("=============================================")
    print("Modelo:", MODEL)
    print("Embeddings:", EMBED_MODEL)
    print("Sistema: RAG")
    print("Execucao: Local")
    print("---------------------------------------------")
    print("/indexar  - Indexar documentos TXT")
    print("/fontes   - Consultar documentos")
    print("/sair     - Encerrar")
    print("=============================================")

    try:

        while True:

            pergunta = input("\nVoce: ").strip()

            if not pergunta:
                continue

            comando = pergunta.lower()

            if comando == "/sair":

                print("\nEncerrando Guilherme AI...")
                break

            elif comando == "/indexar":

                indexar_documentos(conexao)

            elif comando == "/fontes":

                mostrar_fontes(conexao)

            else:

                print("\nGuilherme AI: ", end="", flush=True)

                resposta = conversar(
                    conexao,
                    pergunta
                )

                print(resposta)

    except (KeyboardInterrupt, EOFError):

        print("\n\nEncerrando Guilherme AI...")

    finally:

        conexao.close()


# ==========================================
# INICIAR A APLICACAO
# ==========================================

if __name__ == "__main__":
    iniciar_aplicacao()
