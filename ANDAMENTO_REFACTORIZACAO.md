# Andamento da refatoracao

**Projeto:** Aplicativo JadLog/Zendesk  
**Atualizado em:** 09/11/2026  
**Status geral:** refatoracao incremental em andamento  
**Branch publicada:** [`copilot/refactor-services`](https://github.com/tallymatiassilva-tech/APP-ZEN/tree/copilot/refactor-services)  
**Ultimo commit publicado:** [`971dca4`](https://github.com/tallymatiassilva-tech/APP-ZEN/commit/971dca4681b76e4253134928dc617d0b0edaeac6)

## Objetivo

Reduzir gradualmente as responsabilidades de `src/app_legacy.py`, movendo regras de negocio e processamento para servicos menores e testaveis. A refatoracao busca preservar o comportamento existente, as regras por UF e a interface atual, sem reescrever o aplicativo de uma vez.

## Trabalho realizado

### Servicos e regras de negocio

- Extraidas regras de classificacao e extracao de documentos, incluindo DAR, termos, notas fiscais, chaves NF-e, codigos de barras, vencimentos e dados monetarios.
- Reunidos os roteadores e servicos de extracao por UF, incluindo regras especificas para AC, AL, AM, AP e MS, alem do fluxo geral.
- Melhorada a validacao de guias AP, incluindo extracao de CPF/CNPJ do campo 05, comparacao de documentos e atualizacao de status.
- Extraidos utilitarios de normalizacao e formatacao de texto, datas, documentos e valores, preservando variantes legadas quando os formatos diferem.
- Extraidas operacoes de PDF, como leitura de texto, recorte e mesclagem.
- Criados servicos para leitura de PDFs locais, processamento de lotes e montagem dos dados do relatorio.
- Extraida a compilacao do relatorio, incluindo atualizacao da memoria de termos e preparacao dos itens e linhas da planilha.
- Extraida a importacao e mesclagem de planilhas de conferencia CSV/Excel.
- Mantidos servicos de armazenamento de memoria diaria e checkpoints.

### Zendesk, anexos e layouts

- Extraidos o cliente da API Zendesk, autenticacao/cookie e operacoes de tickets, comentarios e downloads.
- Extraido o gerenciamento de layouts configuraveis.
- Extraidos a coleta de anexos de tickets, classificacao de arquivos, download paralelo, deteccao de duplicatas e organizacao em pastas.
- Preservadas regras de quarentena AL e propagacao de vencimento para documentos AP.
- Extraidos o processamento de PDFs e a agregacao dos registros de tickets para a planilha.
- O processamento por ticket agora pode obter os dados, classificar anexos e salvar os arquivos por meio dos servicos, recebendo callbacks da interface para logs e tratamento de eventos.

### Conciliação Fraction

- Extraidas a preparacao de itens pendentes, aplicacao dos resultados na linha e atualizacao da memoria.
- Extraidas a consulta de CT-e, selecao de resultados, tentativas, cache, parsing de paginas, links de detalhe e fallback de tracking.
- Preservada a coordenacao de interface e o sinal de cookie expirado no app.

### Funcionalidades removidas a pedido

- Removida do app a funcionalidade de consolidar planilhas.
- Removida da interface a resposta automatica de tickets Zendesk. O metodo do cliente Zendesk foi mantido no servico; a remocao foi do fluxo de interface solicitado.

## Validacao

Na arvore preparada para publicacao, a ultima validacao executada foi:

- `python -m pytest -q`: **171 testes aprovados**.
- Ruff direcionado para ordenacao de imports: aprovado.
- `compileall` nos modulos alterados: aprovado.
- `git diff --check`: aprovado.

Os testes utilizam dados e respostas simuladas. **Nao foram feitos testes manuais com PDFs reais nem chamadas reais ao Zendesk ou ao Fraction.**

## Publicacao no GitHub

As alteracoes foram publicadas na branch [`copilot/refactor-services`](https://github.com/tallymatiassilva-tech/APP-ZEN/tree/copilot/refactor-services), sem alterar `main`.

Commits publicados nesta etapa:

- [`8bc5b81` - extracao dos fluxos restantes de processamento](https://github.com/tallymatiassilva-tech/APP-ZEN/commit/8bc5b813b830eeaa7808f002d095742d0214fdee)
- [`971dca4` - extracao de fluxos de relatorio](https://github.com/tallymatiassilva-tech/APP-ZEN/commit/971dca4681b76e4253134928dc617d0b0edaeac6)

O commit `971dca4` inclui, entre outros ajustes, a orquestracao de anexos por ticket, o processamento de PDFs locais para relatorio e a compilacao/persistencia dos dados do relatorio.

## O que falta

1. **Concluir a extracao da coordenacao de conciliacao Fraction** que ainda permanece em `src/app_legacy.py`, mantendo no app os callbacks de interface, logs, progresso e cancelamento.
2. **Revisar a atualizacao do relatorio apos a conciliacao** e o salvamento do relatorio final; mover regras para servicos apenas quando isso reduzir acoplamento sem duplicar logica ja existente.
3. **Executar testes de regressao e checagens focadas** a cada etapa. Os testes com dados reais e a validacao manual da interface continuam pendentes.
4. **Revisar a compatibilidade antes de integrar a branch em `main`**. O historico e o conteudo local e remoto divergiram; `main` nao foi modificada nesta publicacao.

## Fora do escopo de extracao

`src/app_legacy.py` continuara sendo o ponto de coordenacao da interface grafica. Construcoes de telas, widgets, dialogos, eventos da GUI e callbacks de exibicao nao precisam ser removidos do legado so para reduzir o numero de linhas. O criterio e deslocar regras e processamento testaveis, mantendo a interface e o fluxo de uso.

