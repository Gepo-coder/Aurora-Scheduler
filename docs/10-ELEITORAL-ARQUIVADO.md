# Módulo 10 — Eleitoral

## Estado

**ARQUIVADO / MÓDULO ESPECIAL.**

A lógica eleitoral foi necessária durante o período de inserções políticas, mas não deve permanecer misturada ao núcleo permanente do Scheduler.

## Regra histórica de grade

Para inserção estadual:

- `Veiculação == ESTADO`
- `Tipo == HORARIO POLITICO`

O horário oficial `Entrada` era preservado literalmente.

A lógica TRE selecionava a mídia, mas nunca criava ou deduzia horários inexistentes na grade oficial.

Eventos `NACIONAL` não eram usados para inserção local.

## Janelas protegidas históricas

- 13:00:00–13:25:00
- 20:30:00–20:55:00

Durante essas janelas, a fonte protegida era TVE-CURITIBA.

## Dias

A associação TRE/mídia funcionava SEG–DOM.

Janelas de PGM eleitoral eram SEG–SÁB.

## Prioridade histórica

ELEITORAL tinha precedência absoluta sobre automações locais.

## Motivo do arquivamento

O módulo:

- aumenta complexidade;
- possui regras temporais específicas de eleição;
- pode voltar a ser necessário em segundo turno ou futuras eleições;
- não deve interferir na automação cotidiana.

## Diretriz futura

Extrair a lógica eleitoral para módulo opcional, ativado somente por configuração explícita.
