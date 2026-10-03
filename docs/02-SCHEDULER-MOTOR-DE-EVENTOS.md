# Módulo 02 — Scheduler / Motor de Eventos

## Finalidade

Executar ações no horário correto e manter o estado operacional do sistema.

## Responsabilidades

- acompanhar relógio do sistema;
- identificar próximo evento;
- calcular countdown;
- impedir repetição indevida;
- registrar eventos executados;
- respeitar prioridades;
- disparar CasparCG;
- coordenar ATEM;
- restaurar fonte após eventos locais;
- tratar virada de dia;
- atualizar a grade sem interromper a operação nominal.

## Estado mínimo esperado

- evento atual;
- próximo evento;
- horário;
- countdown;
- origem da grade;
- conexão CasparCG;
- conexão ATEM;
- fonte atual;
- eventos já executados;
- estado de PGM;
- estado de logo.

## Concorrência

A aplicação usa Tkinter com callbacks, timers e threads auxiliares.

Callbacks enviados por `after()` não devem capturar diretamente variáveis de exceção do bloco `except`, porque Python limpa essas variáveis após o bloco.

Correção consolidada:

```python
except Exception as exc:
    error_message = str(exc)
    self.after(0, lambda msg=error_message: self._refresh_error(msg))
```

## Estado

**OPERACIONAL / REVISAR ANTES DE REFATORAR**.
