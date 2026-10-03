# Módulo 01 — Grade TV Cultura

## Finalidade

Obter a programação oficial da TV Cultura e transformá-la em eventos utilizáveis pelo Scheduler.

## Fonte principal

`https://cultura.uol.com.br/roteiro/`

Campos relevantes:

- Entrada
- Duração
- Veiculação
- Tipo
- Evento

## Prioridade de fonte

### HTML

Fonte principal quando estiver configurada, acessível e puder ser interpretada.

### XML/TXT

Usado somente quando o HTML estiver vazio ou houver falha real no acesso/leitura.

A grade operacional não deve combinar simultaneamente eventos de HTML e XML/TXT.

## Atualização

A atualização deve distinguir:

- consulta/ping ao site;
- modificação real da grade;
- alteração efetiva na assinatura dos eventos.

O campo visual “Atualizado em” não deve ser usado sozinho como prova de mudança da grade.

## Promoção da grade

- primeira leitura válida: promove;
- assinatura alterada com modificação válida: promove;
- assinatura igual: mantém;
- HTML inválido: tenta fallback XML/TXT.

## OFFSET

O OFFSET é global para os eventos Cultura.

Exemplo:

- horário publicado: 10:00:00
- Cultura 30 segundos atrasada
- OFFSET +30
- execução: 10:00:30

## Campos preservados

Os eventos devem manter, quando disponíveis:

- horário original;
- duração;
- veiculação;
- tipo;
- nome/evento.

Esses campos também alimentam outras automações, como o Logo MP1.

## Estado

**OPERACIONAL**, com prioridade HTML > XML/TXT consolidada na linha V1.35.9 / V1.36.x.
