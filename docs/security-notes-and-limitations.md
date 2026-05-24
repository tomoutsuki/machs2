# Notas de Segurança e Limitações

## Objetivo

Registrar o modelo de ameaça implícito no MVP, os riscos residuais observáveis no código e as principais limitações arquiteturais da implementação atual.

## Ameaças consideradas pelo MVP

### Em foco

- usuário autenticado com atributos insuficientes tentando descriptografar uma entrada;
- observador do banco tentando encontrar plaintext FHIR diretamente nas tabelas;
- separação entre descoberta por metadados e acesso ao payload.

### Fora de foco no estado atual

- hardening de perímetro Internet;
- multi-tenancy;
- HSM ou custódia avançada de chaves;
- conformidade regulatória completa;
- resistência formal a side channels.

## Propriedades de segurança buscadas

- payload FHIR não armazenado em plaintext no banco;
- descriptografia liberada apenas a sessões com atributos adequados;
- blind index derivado sem expor o valor normalizado ao banco;
- custódia de MQK/MSK fora das tabelas de EHR.

## Limitações arquiteturais observadas

### 1. Apenas `fabeo` está operacionalmente implementado

Embora a proposta de pesquisa mencione múltiplos modos, o código atual:

- aceita apenas `fabeo` na API;
- cria apenas o schema `fabeo`;
- grava apenas em `fabeo.entries`.

### 2. O payload retorna em plaintext pela Main API

`decrypt-package` devolve `resource_json` já decifrado ao cliente autorizado.

Consequência:

- a confidencialidade em repouso é tratada;
- a superfície de exposição em aplicação e transporte continua existindo.

### 3. Busca e metadados são menos restritos que o decrypt

Usuários autenticados conseguem:

- fazer `search`;
- consultar `cipher`;

sem provar satisfação da política da entrada.

Consequência:

- há vazamento controlado de metadados para usuários autenticados;
- a autorização forte só ocorre no unwrap CP-ABE.

### 4. Logout é apenas client-side

`POST /auth/logout`:

- apaga o cookie;
- não invalida JWT;
- não apaga `session_usk`.

Consequência:

- não há revogação imediata no servidor.

### 5. Dupla noção de expiração

Há TTL de JWT e TTL de `session_usk`.

Consequência:

- o comportamento real depende do menor prazo;
- a sessão criptográfica pode expirar antes do token.

### 6. USKs reais ficam em memória do bridge

O bridge usa `SESSION_KEYS` em memória de processo.

Consequência:

- reinício do container pode invalidar sessões ainda persistidas em `public.session_usk`;
- não há persistência durável nem replicação desse estado.

### 7. Token interno estático

KMS e bridge aceitam chamadas internas com um `x-internal-token` estático vindo do ambiente.

Consequência:

- o modelo é suficiente para laboratório local;
- é fraco para produção sem rotação, segmentação e mTLS.

### 8. Revogação por epoch é experimental e incompleta

Problemas observados:

- a Main API usa `settings.current_epoch` estático carregado no startup;
- o KMS muda um `CURRENT_EPOCH` próprio em memória;
- não há recriptografia automática;
- não há atualização global coordenada das sessões e entradas.

Consequência:

- não é correto tratar o mecanismo atual como revogação robusta.

### 9. Validação FHIR é mínima

O código verifica apenas:

- JSON objeto;
- presença de `resourceType`;
- `resourceType` em um conjunto suportado.

Consequência:

- não há validação profunda de perfis, cardinalidades, terminologias ou semântica clínica.

### 10. Stack FABEO depende de ambiente legado

O container upstream usa:

- Ubuntu 16.04;
- Python 2.7;
- Charm 0.43.

Consequência:

- manutenção e portabilidade são frágeis;
- há risco operacional maior em rebuilds futuros.

## Pontos simulados ou incompletos

### Modos alternativos

`aes_gcm`, `tde`, `column_level` e `app_level` aparecem como intenção arquitetural, mas não como fluxos públicos ativos.

### Revogação

Há endpoint e testes associados, mas a trilha é explicitamente experimental.

### Documentação legada inconsistente

Alguns artefatos antigos do repositório citam bridge com comportamento simulado determinístico. No `server.py` inspecionado, o fluxo ativo é CP-ABE real com `PairingGroup` e `FABEO22CPABE`.

### Scripts demo legados

`scripts/demo/insider_tests.py` usa usernames que não coincidem com o seed atual, o que sugere acúmulo de artefatos de fases anteriores do MVP.

## Riscos residuais

- exposição de metadados (`policy_expression`, `owner_username`, blind indexes);
- falta de trilha de auditoria formal para decrypts negados ou autorizados;
- dependência de segredo estático em ambiente;
- ausência de revogação server-side de sessão no logout;
- divergência possível entre epoch do KMS e epoch da Main API;
- falta de foreign keys e validações relacionais mais rígidas no banco.

## Recomendações para evolução futura

1. Implementar invalidação server-side de sessão e logout real.
2. Persistir e gerenciar chaves de sessão com estratégia mais robusta que memória local do bridge.
3. Sincronizar epoch entre Main API, KMS e entradas com recriptografia controlada.
4. Adicionar trilha de auditoria para tentativas de decrypt.
5. Restringir ou particionar melhor metadados expostos por `search` e `cipher`.
6. Introduzir mTLS ou mecanismo mais forte para chamadas internas.
7. Substituir a stack legada do bridge por base suportada e mantida.
8. Definir, implementar e testar de forma isolada os demais modos criptográficos, se continuarem no escopo acadêmico.
9. Fortalecer a validação FHIR além do conjunto mínimo atual.

## Leitura correta do MVP

O MACHS2 atual deve ser interpretado como:

- um ambiente local de pesquisa;
- orientado a validar a viabilidade de um fluxo híbrido `AES-GCM + CP-ABE/FABEO`;
- útil para experimentos de ABAC, blind index e observação de banco;
- não pronto para produção.
