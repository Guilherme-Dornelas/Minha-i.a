
import requests
import sqlite3

# ==========================================
# GUILHERME AI - VERSAO 3.0
# MEMORIA DE LONGO PRAZO
# ==========================================

MODEL = "guilherme-ai"
API_URL = "http://localhost:11434/api/chat"
DATABASE = "memory.db"

MAX_CONTEXT_MESSAGES = 10
MAX_MEMORIES_IN_CONTEXT = 20


# ==========================================
# 1. CONEXAO COM O BANCO DE DADOS
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

    conexao.commit()

    return conexao


# ==========================================
# 2. GERENCIAMENTO DAS MEMORIAS
# ==========================================

def salvar_memoria(conexao, informacao):

    cursor = conexao.execute(
        """
        INSERT INTO memorias (content)
        VALUES (?)
        """,
        (informacao,)
    )

    conexao.commit()

    return cursor.lastrowid


def listar_memorias(conexao):

    return conexao.execute(
        """
        SELECT id, content, created_at
        FROM memorias
        ORDER BY id ASC
        """
    ).fetchall()


def carregar_memorias(conexao):

    registros = conexao.execute(
        """
        SELECT id, content
        FROM memorias
        ORDER BY id DESC
        LIMIT ?
        """,
        (MAX_MEMORIES_IN_CONTEXT,)
    ).fetchall()

    return list(reversed(registros))


def excluir_memoria(conexao, memoria_id):

    cursor = conexao.execute(
        "DELETE FROM memorias WHERE id = ?",
        (memoria_id,)
    )

    conexao.commit()

    return cursor.rowcount > 0


def excluir_todas_memorias(conexao):

    conexao.execute("DELETE FROM memorias")
    conexao.commit()


# ==========================================
# 3. HISTORICO DE CONVERSAS
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
        {"role": registro["role"],
         "content": registro["content"]}
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
# 4. CONSTRUIR CONTEXTO DA INTELIGENCIA
# ==========================================

def construir_contexto(conexao):

    memorias = carregar_memorias(conexao)

    if memorias:

        informacoes = "\n".join(
            f"- {memoria['content']}"
            for memoria in memorias
        )

    else:

        informacoes = "Nenhuma memoria foi cadastrada."

    return f"""
    As informacoes abaixo foram salvas pelo usuario
    como memorias de longo prazo.

    MEMORIAS DO USUARIO:

    {informacoes}

    INSTRUCOES:
    - Utilize essas informacoes quando forem relevantes.
    - Nao invente informacoes pessoais.
    - Nao afirme que sabe algo que nao esta registrado.
    - Se duas informacoes entrarem em conflito,
      solicite esclarecimento ao usuario.
    - As memorias sao referencias e podem estar desatualizadas.
    """


# ==========================================
# 5. COMUNICACAO COM O LLAMA
# ==========================================

def enviar_mensagem(conexao, pergunta):

    historico = carregar_historico(conexao)

    contexto = construir_contexto(conexao)

    mensagens = [
        {
            "role": "system",
            "content": contexto
        }
    ]

    mensagens.extend(historico)

    mensagens.append({
        "role": "user",
        "content": pergunta
    })

    mensagens = mensagens[-(MAX_CONTEXT_MESSAGES + 1):]

    # Garante que as instrucoes de memoria
    # permaneçam no inicio do contexto.
    mensagens.insert(0, {
        "role": "system",
        "content": contexto
    })

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

        salvar_mensagem(conexao, "user", pergunta)

        salvar_mensagem(conexao, "assistant", conteudo)

        return conteudo

    except requests.exceptions.ConnectionError:
        return "Erro: nao consegui conectar ao Ollama."

    except requests.exceptions.Timeout:
        return "A resposta demorou demais."

    except requests.exceptions.HTTPError as erro:
        return f"Erro HTTP: {erro}"

    except (KeyError, ValueError):
        return "Resposta inesperada do modelo."

    except requests.exceptions.RequestException as erro:
        return f"Erro de comunicacao: {erro}"


# ==========================================
# 6. INTERFACE DA APLICACAO
# ==========================================

def mostrar_memorias(conexao):

    memorias = listar_memorias(conexao)

    print("\n===== MINHAS MEMORIAS =====")

    if not memorias:
        print("Nenhuma memoria cadastrada.")
        return

    for memoria in memorias:

        print(
            f"\nID: {memoria['id']}"
            f"\nInformacao: {memoria['content']}"
            f"\nData: {memoria['created_at']}"
        )

    print("\n===========================")


def mostrar_ajuda():

    print("""
    COMANDOS DA GUILHERME AI 3.0

    /lembrar texto
        Salva uma nova memoria.

    /memorias
        Mostra todas as memorias.

    /esquecer ID
        Exclui uma memoria especifica.

    /esquecer tudo
        Exclui todas as memorias.

    /ajuda
        Mostra os comandos.

    /sair
        Encerra a aplicacao.
    """)


# ==========================================
# 7. EXECUCAO PRINCIPAL
# ==========================================

def iniciar_aplicacao():

    conexao = conectar_banco()

    print("\n" + "=" * 45)
    print("       GUILHERME AI - VERSAO 3.0")
    print("=" * 45)

    print("Modelo:", MODEL)
    print("Memoria: SQLite")
    print("Memoria de longo prazo: Ativada")
    print("Execucao: Local")

    print("\nDigite /ajuda para consultar os comandos.")

    print("=" * 45)

    try:

        while True:

            pergunta = input("\nVoce: ").strip()

            if not pergunta:
                continue

            comando = pergunta.lower()

            # ENCERRAR
            if comando == "/sair":

                print("\nEncerrando Guilherme AI...")
                break

            # AJUDA
            elif comando == "/ajuda":

                mostrar_ajuda()

            # CADASTRAR MEMORIA
            elif comando.startswith("/lembrar"):

                informacao = pergunta[len("/lembrar"):].strip()

                if not informacao:
                    print("Informe o que deseja guardar.")
                    continue

                if len(informacao) > 500:
                    print("A memoria deve ter no maximo 500 caracteres.")
                    continue

                memoria_id = salvar_memoria(
                    conexao,
                    informacao
                )

                print(
                    f"\nMemoria salva com sucesso! ID: {memoria_id}"
                )

            # CONSULTAR MEMORIAS
            elif comando == "/memorias":

                mostrar_memorias(conexao)

            # EXCLUIR MEMORIA
            elif comando.startswith("/esquecer"):

                argumento = pergunta[len("/esquecer"):].strip()

                if argumento.lower() == "tudo":

                    confirmacao = input(
                        "Digite APAGAR para confirmar "
                        "a exclusao de todas as memorias: "
                    )

                    if confirmacao == "APAGAR":

                        excluir_todas_memorias(conexao)

                        print("\nTodas as memorias foram excluidas.")

                    else:

                        print("\nOperacao cancelada.")

                else:

                    try:

                        memoria_id = int(argumento)

                        sucesso = excluir_memoria(
                            conexao,
                            memoria_id
                        )

                        if sucesso:
                            print("\nMemoria excluida com sucesso.")
                        else:
                            print("\nID de memoria nao encontrado.")

                    except ValueError:
                        print("Use /esquecer seguido do ID da memoria.")

            # CONVERSA NORMAL
            else:

                print("\nGuilherme AI: ", end="", flush=True)

                resposta = enviar_mensagem(
                    conexao,
                    pergunta
                )

                print(resposta)

    except (KeyboardInterrupt, EOFError):

        print("\n\nEncerrando Guilherme AI...")

    finally:

        conexao.close()


# ==========================================
# INICIAR PROGRAMA
# ==========================================

if __name__ == "__main__":
    iniciar_aplicacao()
