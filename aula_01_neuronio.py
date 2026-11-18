# ==========================================
# PROJETO: MINHA IA
# AULA 01: PRIMEIRO NEURONIO ARTIFICIAL
# ==========================================

# 1. Dados de treinamento
# Nosso neurônio aprenderá a operação lógica AND.

dados_treinamento = [
    ([0, 0], 0),
    ([0, 1], 0),
    ([1, 0], 0),
    ([1, 1], 1)
]


# 2. Inicialização dos parâmetros

pesos = [0.0, 0.0]

vies = 0.0

taxa_aprendizado = 0.1

limite = 0.5


# 3. Função de ativação e previsão

def prever(entradas, pesos, vies):

    soma = sum(
        entrada * peso
        for entrada, peso in zip(entradas, pesos)
    )

    soma += vies

    if soma >= limite:
        return 1

    return 0


# 4. Processo de aprendizagem

print("INICIANDO TREINAMENTO...\n")

for epoca in range(1, 21):

    erros = 0

    for entradas, resultado_esperado in dados_treinamento:

        resultado = prever(entradas, pesos, vies)

        erro = resultado_esperado - resultado

        if erro != 0:
            erros += 1

        # Atualização dos pesos

        for i in range(len(pesos)):

            pesos[i] += (
                taxa_aprendizado * erro * entradas[i]
            )

        # Atualização do viés

        vies += taxa_aprendizado * erro

    print(f"Epoca {epoca}: {erros} erro(s)")

    if erros == 0:
        break


# 5. Teste final

print("\nTREINAMENTO CONCLUIDO!")

print("\nRESULTADOS:")

for entradas, resultado_esperado in dados_treinamento:

    resultado = prever(entradas, pesos, vies)

    print(f"Entrada: {entradas} | Resultado: {resultado}")

print("\nPESOS FINAIS:", pesos)
print("VIES FINAL:", vies)