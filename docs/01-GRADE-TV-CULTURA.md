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

## Grade integral

Quando o período eleitoral estiver desabilitado, o Scheduler passa a manter e exibir a **grade integral da Cultura**, sem limitar a visualização apenas a linhas políticas/estaduais.

Isso inclui, conforme recebido da fonte:

- PROGRAMA;
- chamadas;
- classificações indicativas;
- pacotes;
- boletins;
- intervalos;
- demais eventos presentes na grade.

Essas linhas integrais não devem ser tratadas automaticamente como inserts locais. Elas também funcionam como referência de estado para outros módulos.

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

Esses campos alimentam outras automações, inclusive o módulo Logo MP1.

## Estado

**OPERACIONAL**, com grade integral e prioridade HTML > XML/TXT consolidadas na V1.36.6.
