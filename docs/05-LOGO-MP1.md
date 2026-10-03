# Módulo 05 — Logo MP1

## Finalidade

Acionar automaticamente o logo carregado no Media Player 1 do ATEM durante a programação normal da TV Cultura.

## Integração correta

O logo é colocado no ar pelo **DSK1 — Downstream Keyer 1** do ATEM.

O Media Player 1 fornece a arte/fonte do logo e o Scheduler controla o estado ON/OFF do DSK1.

## Regra operacional

O logo só pode ficar ligado quando forem simultaneamente verdadeiros:

- PROGRAM do ATEM está na fonte Cultura;
- a **linha atual** da grade possui **Veiculação vazia**;
- o **Tipo** da linha atual é `PROGRAMA`.

```
CULTURA
+ linha atual
+ Veiculação == ""
+ Tipo == "PROGRAMA"
→ janela válida do logo
```

## Temporização

Dentro de uma linha válida de PROGRAMA:

- **ON:** 3 segundos após o início;
- **OFF:** 5 segundos antes do fim efetivo.

```
INÍCIO PROGRAMA
      +3 s
       ↓
    DSK1 ON
       │
       │
    DSK1 OFF
       ↑
      -5 s
FIM EFETIVO
```

## Fim efetivo da linha

A duração declarada do PROGRAMA não é usada isoladamente.

Se a próxima linha da grade começar antes do término nominal do programa, o início dessa próxima linha encerra o estado da linha anterior.

Isso evita que o logo permaneça ligado em:

- chamadas;
- classificação indicativa;
- pacotes;
- boletins;
- intervalos;
- qualquer outra linha cujo Tipo não seja PROGRAMA.

## Comportamento fora da condição

Qualquer condição abaixo força o logo para OFF:

- ATEM fora da Cultura;
- Veiculação preenchida;
- Tipo diferente de PROGRAMA;
- período entre linhas;
- janela final de 5 segundos do PROGRAMA.

## Interface

A interface apresenta o estado do controle como:

- `LOGO MP1 / DSK1: ON`
- `LOGO MP1 / DSK1: OFF`

## Validação

**V1.36.6 — validada em teste operacional em 03/10/2026.**

Resultado confirmado: entrada e retirada automática do logo funcionando corretamente.
