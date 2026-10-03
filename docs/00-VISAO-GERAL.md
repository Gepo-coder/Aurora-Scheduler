# Visão Geral do Sistema

## Finalidade

O Aurora-Scheduler coordena a automação de exibição da emissora, integrando:

```
TV Cultura / fontes externas
        ↓
     Scheduler
        ↓
regras / prioridades / estados
        ↓
     CasparCG
        ↓
Blackmagic DeckLink
        ↓
 ATEM / StudioHD
        ↓
        AR
```

## Núcleo operacional

O núcleo permanente do sistema é composto por:

- leitura da grade da TV Cultura;
- atualização periódica da grade;
- aplicação de OFFSET da Cultura;
- seleção explícita entre HTML e XML/TXT fallback;
- motor de eventos por horário;
- execução de mídia via CasparCG;
- comutação de fontes via ATEM/StudioHD;
- integração com vMix;
- controle de PGM local;
- persistência de estado e configurações;
- logs e tratamento de falhas.

## Fontes de sinal atualmente conhecidas

- ATEM 1 — CULTURA-SP
- ATEM 2 — TVE-CURITIBA
- ATEM 7 — vMIX
- ATEM 8 — CASPAR-LOCAL

## Fonte de grade

Prioridade consolidada:

1. HTML da TV Cultura, quando configurado e acessível.
2. XML/TXT somente como fallback quando o HTML estiver vazio ou falhar.
3. Nunca misturar HTML e XML/TXT na mesma grade operacional.

## OFFSET Cultura

O OFFSET é aplicado somente aos eventos derivados da grade da Cultura.

- atraso real da Cultura: OFFSET positivo;
- adiantamento real da Cultura: OFFSET negativo.

O OFFSET não deve alterar horários locais independentes, PGM locais ou BLOCOS locais.

## Estado do projeto

Versão operacional consolidada até a família V1.36.x.

A documentação separa:

- **OPERACIONAL** — já existente e usado;
- **REVISAR** — existente, mas deve ser auditado antes de mudanças estruturais;
- **ARQUIVADO** — lógica histórica que não pertence ao núcleo permanente;
- **REQUISITO / PROJETO** — função ainda a reconstruir.
