# Módulo 05 — Logo MP1

## Finalidade

Acionar automaticamente o logo carregado no Media Player 1 do ATEM durante a programação normal da TV Cultura.

## Regra operacional

O logo deve ficar ligado quando forem simultaneamente verdadeiros:

- fonte operacional: Cultura;
- campo **Veiculação** vazio;
- campo **Tipo** igual a `PROGRAMA`.

```
CULTURA
+ Veiculação == ""
+ Tipo == "PROGRAMA"
→ MP1 ON
```

Ao sair dessa condição:

```
→ MP1 OFF
```

## Fonte dos dados

Veiculação e Tipo vêm do parser da grade da TV Cultura.

## Integração ATEM

A arte do logo continua preparada previamente no Media Player 1 do ATEM.

O Scheduler controla o keyer necessário para colocar ou retirar o logo do ar.

## Interface

- `LOGO MP1: ON`
- `LOGO MP1: OFF`

## Estado

**OPERACIONAL na linha V1.36.2**, sujeito a validação prática no ar.
