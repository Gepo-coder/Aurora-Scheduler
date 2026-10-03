# Módulo 07 — BLOCOS

## Estado

**REQUISITO / PROJETO — reconstrução necessária.**

A implementação antiga de AVULSO FIXO/VINCULADO e execução encadeada não atendeu à operação e não deve ser mantida como referência funcional.

## Novo conceito

Um BLOCO é uma única unidade operacional formada por uma playlist sequencial de mídias locais.

Exemplo:

```
BLOCO_1
01 vinheta_emissora
02 comercial_1
03 comercial_2
04 chamada_1
05 vinheta_emissora_2
06 abertura_do_PGM
```

## Início

- AUTO — disparado por horário;
- MANUAL — operador pressiona PLAY.

## Execução

1. Scheduler seleciona CASPAR-LOCAL no ATEM.
2. CasparCG executa a playlist na ordem.
3. Não há retorno para Cultura entre os itens.
4. O bloco permanece protegido até o término da última mídia.

## Finalização

Ao terminar a última mídia:

1. bloco é considerado concluído;
2. ATEM muda para a **Fonte ao terminar**.

## Fonte ao terminar

É manual, obrigatória, armazenada no próprio bloco e nunca inferida automaticamente.

Exemplos:

```
Cultura → Caspar → playlist → vMix
```

```
vMix → Caspar → playlist → Cultura
```

## Proteção

Durante um bloco em execução, eventos normais não devem cortar a playlist no meio.

Somente STOP/ABORT explícito deve interromper.

## Representação na grade

O Scheduler deve enxergar o BLOCO como um único evento.

```
18:58:30 | BLOCO — ENTRADA PGM LOCAL | 02:14 | → vMIX
```

## Próxima etapa

Reconstruir o módulo do zero, removendo a dependência da lógica antiga AVULSO FIXO/VINCULADO.
