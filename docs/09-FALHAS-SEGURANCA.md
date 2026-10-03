# Módulo 09 — Falhas e Segurança Operacional

## Finalidade

Definir o comportamento esperado quando partes do sistema deixam de responder.

## Cultura indisponível

Se HTML falhar:

1. tentar XML/TXT fallback;
2. substituir a grade Cultura inteira pelo fallback;
3. nunca misturar eventos de duas fontes.

## CasparCG offline

O Scheduler não deve assumir que uma mídia foi ao ar sem confirmação operacional do CasparCG.

## ATEM offline

Sem ATEM, não há garantia de comutação física correta.

## Mídia ausente

Evento local sem mídia válida não deve ser marcado silenciosamente como exibido.

## Threads / callbacks

Exceções em threads devem ser transferidas para callbacks Tkinter por valor estável.

## Virada de dia

- limpar estados diários apropriados;
- invalidar grade operacional do dia anterior;
- forçar nova seleção HTML > XML/TXT.

## Logs

Devem permitir reconstruir:

- horário;
- evento;
- comando enviado;
- resposta CasparCG;
- fonte ATEM antes/depois;
- erro;
- recuperação.

## Estado

**OPERACIONAL / NECESSITA DOCUMENTAÇÃO CONTÍNUA DE FALHAS REAIS**.
