# Módulo 06 — PGM / AO VIVO

## Finalidade

Controlar programas locais e períodos AO VIVO independentes da grade da Cultura.

## Conceito

O PGM local possui autoridade própria por configuração local.

A grade online da Cultura não é fonte de verdade para início ou término de um PGM local.

## Dados esperados

- nome;
- dias da semana;
- horário de início;
- horário de fim;
- fonte de entrada;
- fonte de saída;
- indicador AO VIVO;
- ativo/inativo.

## Fluxo

1. Scheduler identifica início do PGM.
2. ATEM muda para a fonte local configurada.
3. O estado do PGM fica ativo.
4. Eventos permitidos podem ocorrer conforme prioridade.
5. Ao fim, o Scheduler restaura a fonte configurada.

## Atenção

A lógica acumulou regras de suspensão, ressincronização e retorno de fonte.

## Estado

**REVISAR ANTES DE MEXER**.
