# Como gerar o executável e publicar atualizações

## Primeira instalação
1. No GitHub, abra **Releases** e baixe `AppZen-windows.zip` da versão mais recente.
2. Extraia a pasta `AppZen` (ex.: em `C:\AppZen`) e abra `AppZen.exe`.
   Crie um atalho na área de trabalho se quiser.

## Publicar uma correção (nova versão)
1. Faça a correção no código (pull request, como de costume) e aprove na `main`.
2. Em `src/settings.py`, aumente `version` (ex.: `1.3.0` → `1.3.1`). Também em `pyproject.toml`.
3. No GitHub: **Releases → Draft a new release → Choose a tag** e digite `v1.3.1`
   (igual à versão), alvo `main`, depois **Publish release**.
4. Em ~10 minutos a aba **Actions** termina e o `AppZen-windows.zip` aparece na release.

## O que acontece no computador do usuário
Ao abrir o AppZen.exe, ele confere se há versão nova. Se houver, pergunta
"Deseja atualizar agora?". Com "Sim", baixa, fecha, troca os arquivos e reabre.
Memória diária, checkpoints e layouts personalizados são mantidos.
Sem internet, o app simplesmente abre normalmente.

## Gerar só para testar (sem publicar)
**Actions → Gerar executável Windows → Run workflow**. O zip fica disponível
para download no fim da execução (em "Artifacts").
