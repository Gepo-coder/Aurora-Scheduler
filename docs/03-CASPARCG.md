# Módulo 03 — CasparCG

## Finalidade

Executar as mídias locais enviadas pelo Scheduler.

## Ambiente conhecido

- CasparCG Server 2.4.3
- AMCP TCP 5250
- Canal 1
- Layer 1
- Modo 1080i5994
- Media path: `D:/media/`

## Saída

Blackmagic DeckLink com áudio embutido.

Configuração conhecida:

- device 4;
- embedded audio;
- low latency;
- buffer-depth 3;
- 1080i5994.

## Comando básico

```
PLAY 1-1 "TESTE"
```

Resposta esperada:

```
#202 PLAY OK
```

## Caminhos de mídia

Físico:

```
D:\media\2026\ELEICOES26\COISA_DE_PELE-TSE.mp4
```

AMCP:

```
PLAY 1-1 "2026/ELEICOES26/COISA_DE_PELE-TSE"
```

## Skip de claquete

Valor histórico padrão: 7 segundos.

Em 59.94, aproximadamente 420 frames.

## Duração

Pode ser obtida por ffprobe.

## Retorno de fonte

CasparCG executa a mídia; o Scheduler coordena a comutação no ATEM e a restauração da fonte correta.

## Estado

**OPERACIONAL**.
