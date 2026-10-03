# Aurora-Scheduler

Sistema de automação para TV com integração entre a grade da TV Cultura, CasparCG, Blackmagic DeckLink, ATEM/StudioHD e fontes locais.

## Versão operacional validada

**V1.36.6 — LOGO INTERVALOS CORRIGIDO**

Validada em teste operacional em 03/10/2026.

Principais pontos consolidados nesta versão:

- grade integral da Cultura quando o período eleitoral estiver desabilitado;
- prioridade HTML com XML/TXT apenas como fallback;
- logo MP1 controlado pelo DSK1 do ATEM;
- logo entra 3 segundos após o início de uma linha válida de PROGRAMA;
- logo sai 5 segundos antes do fim efetivo da linha;
- início da próxima linha da grade encerra a condição anterior, evitando logo ativo em chamadas, classificações e intervalos.

## Documentação

- [Visão Geral do Sistema](docs/00-VISAO-GERAL.md)
- [Módulo 01 — Grade TV Cultura](docs/01-GRADE-TV-CULTURA.md)
- [Módulo 02 — Scheduler / Motor de Eventos](docs/02-SCHEDULER-MOTOR-DE-EVENTOS.md)
- [Módulo 03 — CasparCG](docs/03-CASPARCG.md)
- [Módulo 04 — ATEM / StudioHD](docs/04-ATEM-STUDIOHD.md)
- [Módulo 05 — Logo MP1](docs/05-LOGO-MP1.md)
- [Módulo 06 — PGM / AO VIVO](docs/06-PGM-AO-VIVO.md)
- [Módulo 07 — BLOCOS](docs/07-BLOCOS.md)
- [Módulo 08 — Interface e Configurações](docs/08-INTERFACE-CONFIGURACOES.md)
- [Módulo 09 — Falhas e Segurança Operacional](docs/09-FALHAS-SEGURANCA.md)
- [Módulo 10 — Eleitoral (Arquivado)](docs/10-ELEITORAL-ARQUIVADO.md)
- [Histórico de alterações](CHANGELOG.md)

## Estado da documentação

A documentação separa:

- **OPERACIONAL** — já existente e usado;
- **REVISAR** — existente, mas deve ser auditado antes de mudanças estruturais;
- **ARQUIVADO** — lógica histórica que não pertence ao núcleo permanente;
- **REQUISITO / PROJETO** — função ainda a reconstruir.

O módulo de BLOCO permanece como **REQUISITO / PROJETO** até a reconstrução da lógica de playlist sequencial.
