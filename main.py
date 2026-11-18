
import requests

# ==========================================
# GUILHERME AI - VERSAO 1.0
# Inteligencia artificial local
# ==========================================

MODEL = "guilherme-ai"
API_URL = "http://localhost:11434/api/chat"

# Historico temporario da conversa
messages = []


# ==========================================
# FUNCAO DE COMUNICACAO COM O LLAMA
# ==========================================

def enviar_mensagem(pergunta):

    global messages

    # Adiciona a pergunta ao historico
    messages.append({
        "role": "user",
        "content": pergunta
    })

    try:

        # Envia a conversa para o Ollama
        resposta = requests.post(
            API_URL,
            json={
                "model": MODEL,
                "messages": messages,
                "stream": False,
                "keep_alive": "2m",
                "options": {
                    "temperature": 0.6,
                    "num_ctx": 4096
                }
            },
            timeout=180
        )

        resposta.raise_for_status()

        dados = resposta.json()

        # Extrai a resposta do modelo
        conteudo = dados["message"]["content"]

        # Guarda a resposta no historico
        messages.append({
            "role": "assistant",
            "content": conteudo
        })

        # Mantem os ultimos 10 registros
        if len(messages) > 10:
            messages = messages[-10:]

        return conteudo

    except requests.exceptions.ConnectionError:
        return (
            "Erro: nao consegui conectar ao Ollama. "
            "Verifique se ele esta funcionando."
        )

    except requests.exceptions.Timeout:
        return "A resposta demorou demais. Tente novamente."

    except requests.exceptions.HTTPError as erro:
        return f"Erro HTTP na comunicacao: {erro}"

    except (KeyError, ValueError):
        return "O modelo retornou uma resposta inesperada."

    except requests.exceptions.RequestException as erro:
        return f"Erro de comunicacao: {erro}"


# ==========================================
# INTERFACE DE CONVERSACAO
# ==========================================

def iniciar_aplicacao():

    print("\n" + "=" * 45)
    print("          GUILHERME AI - VERSAO 1.0")
    print("=" * 45)
    print("Modelo: Llama 3.2 3B")
    print("Execucao: Local")
    print("Digite /sair para encerrar.")
    print("=" * 45)

    while True:

        try:
            pergunta = input("\nVoce: ").strip()

            if pergunta.lower() == "/sair":
                print("\nEncerrando Guilherme AI...")
                break

            if not pergunta:
                continue

            print("\nGuilherme AI: ", end="", flush=True)

            resposta = enviar_mensagem(pergunta)

            print(resposta)

        except (KeyboardInterrupt, EOFError):
            print("\n\nEncerrando Guilherme AI...")
            break


# ==========================================
# INICIALIZACAO
# ==========================================

if __name__ == "__main__":
    iniciar_aplicacao()
