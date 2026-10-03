# Changelog

## V1.36.6 — 03/10/2026

### Validado operacionalmente

- Logo MP1 passou a usar a linha atual da grade integral como autoridade de estado.
- DSK1 é o keyer correto para colocar o logo no ar.
- Entrada do logo: 3 segundos após o início de uma linha válida de PROGRAMA.
- Saída do logo: 5 segundos antes do fim efetivo.
- O início da próxima linha da grade encerra o estado anterior, mesmo quando a duração nominal do PROGRAMA é maior.
- Chamadas, classificações, intervalos e demais tipos desligam o logo.
- Grade integral da Cultura disponível quando o período eleitoral está desabilitado.

### Resultado

Funcionamento do logo confirmado em teste operacional.

---

## V1.36.5

- Introdução da grade integral quando o período eleitoral está desabilitado.
- Primeira implementação da temporização +3 s / -5 s para o logo.
- Identificada sobreposição causada pelo uso da duração nominal do PROGRAMA.

## V1.36.4

- Correção da leitura de constantes do ATEM.
- DSK1 passou a responder ao comando de ON.
- Diagnóstico confirmou que a saída precisava considerar a linha atual da grade.

## V1.36.3

- Migração do conceito de keyer para DSK1.

## V1.36.2

- Primeira implementação do controle automático do logo MP1.
