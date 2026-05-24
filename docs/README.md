# Documentação Técnica do MACHS2

## Objetivo

Este conjunto de documentos descreve a implementação atual do MACHS2 a partir da inspeção direta do repositório, incluindo serviços, fluxos, tabelas, endpoints, scripts de validação e limitações do MVP local.

O foco do projeto, no estado atual do código, é um fluxo híbrido `fabeo`:

- o payload FHIR JSON é cifrado com `AES-GCM`;
- a DEK é encapsulada por CP-ABE via FABEO;
- blind indexes são derivados pelo KMS mínimo;
- a descriptografia autorizada ocorre por meio de `decrypt-package`.

Embora a proposta acadêmica mencione múltiplos modos criptográficos, o código inspecionado implementa operacionalmente apenas `fabeo`; os demais modos aparecem como intenção arquitetural ou como casos explicitamente rejeitados.

## Documentos disponíveis

- [`architecture.md`](./architecture.md): arquitetura geral, containers, dependências e comunicação.
- [`project-structure.md`](./project-structure.md): mapeamento dos diretórios e arquivos principais.
- [`api-reference.md`](./api-reference.md): referência dos endpoints públicos da Main API.
- [`internal-services.md`](./internal-services.md): endpoints internos do Minimal KMS e do FABEO Bridge.
- [`database.md`](./database.md): schemas, tabelas, colunas e armazenamento cifrado.
- [`authentication-and-authorization.md`](./authentication-and-authorization.md): login, sessão, JWT, USK e ABAC.
- [`cryptographic-flows.md`](./cryptographic-flows.md): modos, blind indexes e fluxos criptográficos.
- [`operation-flows.md`](./operation-flows.md): fluxos ponta a ponta e diagramas de sequência.
- [`running-locally.md`](./running-locally.md): execução local, variáveis de ambiente e troubleshooting.
- [`testing-and-benchmarking.md`](./testing-and-benchmarking.md): testes, benchmarks, validação e interpretação de métricas.
- [`security-notes-and-limitations.md`](./security-notes-and-limitations.md): ameaças consideradas, riscos residuais e limitações do MVP.

## Caminho recomendado de leitura

1. [`architecture.md`](./architecture.md)
2. [`project-structure.md`](./project-structure.md)
3. [`database.md`](./database.md)
4. [`api-reference.md`](./api-reference.md)
5. [`internal-services.md`](./internal-services.md)
6. [`authentication-and-authorization.md`](./authentication-and-authorization.md)
7. [`cryptographic-flows.md`](./cryptographic-flows.md)
8. [`operation-flows.md`](./operation-flows.md)
9. [`running-locally.md`](./running-locally.md)
10. [`testing-and-benchmarking.md`](./testing-and-benchmarking.md)
11. [`security-notes-and-limitations.md`](./security-notes-and-limitations.md)

## Escopo desta documentação

- Baseada no snapshot atual do código do repositório.
- Escrita para o MVP local, não para produção.
- Sem reproduzir segredos, tokens internos ou senhas do seed.
- Com destaque explícito para lacunas, comportamento experimental e inconsistências entre intenção arquitetural e implementação efetiva.