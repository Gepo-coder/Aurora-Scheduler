# Módulo 04 — ATEM / StudioHD

## Finalidade

Comutar fisicamente as fontes de vídeo que chegam ao ar.

## Equipamento

ATEM Television Studio HD / StudioHD.

IP conhecido no ambiente:

`192.168.100.26`

## Mapeamento atual

- Input 1 — CULTURA-SP
- Input 2 — TVE-CURITIBA
- Input 7 — vMIX
- Input 8 — CASPAR-LOCAL

## Biblioteca

PyATEMMax.

Operações conhecidas:

```python
connect(ip, connTimeout=5)
waitForConnection(timeout=5)
setProgramInputVideoSource(0, source)
```

Leitura de PROGRAM:

```python
programInput[0].videoSource
```

## Responsabilidades

- colocar Cultura no ar;
- colocar Caspar local no ar;
- entrar e sair do vMix;
- restaurar fonte correta após eventos locais;
- disponibilizar estados para a interface;
- suportar keyer do logo MP1.

## Princípio operacional

A fonte de saída após um evento deve ser determinada pelo contexto operacional, e não por suposição.

Para o novo módulo BLOCO, a fonte de saída deverá ser explicitamente configurada no próprio bloco.

## Estado

**OPERACIONAL**.
