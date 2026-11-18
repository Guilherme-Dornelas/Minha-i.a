
import requests
import sqlite3

# ==========================================
# GUILHERME AI 2.0
# IA LOCAL COM MEMORIA PERSISTENTE
# ==========================================

MODEL = "guilherme-ai"
API_URL = "http://localhost:11434/api/chat"
DATABASE = "memory.db"

MAX_CONTEXT_MESSAGES = 10


# ==========================================
# BANCO DE DADOS
# ==========================================

def conectar_banco():

    conexao = sqlite3.connect(DATABASE)

    conexao.execute("""
        CREATE TABLE IF NOT EXISTS mensagens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conexao.commit()

    return conexao


# ==========================================
# SALVAR MEMORIA
# ==========================================

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
# RECUPERAR MEMORIA
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

    registros.reverse()

    return [
        {"role": role, "content": content}
        for role, content in registros
    ]


# ==========================================
# COMUNICACAO COM O LLAMA
# ==========================================

def enviar_mensagem(conexao, pergunta):

    historico = carregar_historico(conexao)

    mensagens = historico + [
        {
            "role": "user",
            "content": pergunta
        }
    ]

    mensagens = mensagens[-MAX_CONTEXT_MESSAGES:]

    try:

        resposta = requests.post(
            API_URL,
            json={
                "model": MODEL,
                "messages": mensagens,
                "stream": False,
                "keep_alive": "2m",
                "options": {
                    "temperature": 0.4,
                    "num_ctx": 4096
                }
            },
            timeout=300
        )

        resposta.raise_for_status()

        dados = resposta.json()

        conteudo = dados["message"]["content"]

        # Salva a conversa no banco
        salvar_mensagem(conexao, "user", pergunta)

        salvar_mensagem(conexao, "assistant", conteudo)

        return conteudo

    except requests.exceptions.ConnectionError:
        return "Erro: Ollama nao esta acessivel."

    except requests.exceptions.Timeout:
        return "A resposta demorou demais."

    except requests.exceptions.HTTPError as erro:
        return f"Erro HTTP: {erro}"

    except (KeyError, ValueError):
        return "Resposta inesperada do modelo."

    except requests.exceptions.RequestException as erro:
        return f"Erro de comunicacao: {erro}"


# ==========================================
# APLICACAO PRINCIPAL
# ==========================================

def iniciar_aplicacao():

    conexao = conectar_banco()

    print("\n" + "=" * 45)
    print("       GUILHERME AI - VERSAO 2.0")
    print("=" * 45)
    print("Modelo:", MODEL)
    print("Memoria: SQLite")
    print("Execucao: Local")
    print("Digite /sair para encerrar.")
    print("Digite /limpar para apagar o historico.")
    print("=" * 45)

    while True:

        try:

            pergunta = input("\nVoce: ").strip()

            if pergunta.lower() == "/sair":

                print("\nEncerrando Guilherme AI...")
                break

            if pergunta.lower() == "/limpar":

                conexao.execute(
                    "DELETE FROM mensagens"
                )

                conexao.commit()

                print("\nHistorico apagado permanentemente.")

                continue

            if not pergunta:
                continue

            print("\nGuilherme AI: ", end="", flush=True)

            resposta = enviar_mensagem(
                conexao,
                pergunta
            )

            print(resposta)

        except (KeyboardInterrupt, EOFError):

            print("\n\nEncerrando Guilherme AI...")
            break

    conexao.close()


# ==========================================
# INICIALIZACAO
# ==========================================

if __name__ == "__main__":
    iniciar_aplicacao()
