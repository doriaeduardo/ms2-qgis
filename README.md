# MS 2.0 ANA — Pipeline QGIS (mancha de inundação e perigo por ruptura de barragem)

Implementação aberta do Método Simplificado 2.0 da ANA em Processing Scripts do QGIS.
Gera, a partir de dados de uma barragem, a mancha de inundação e o perigo
hidrodinâmico (h×v) por ruptura, seguindo o método oficial da ANA.

> **Status:** cópia de trabalho para empacotamento.
> A versão que validou as 9 barragens está congelada em `../MS2_validado_2026-07-20/`
> (tag git `v0.1-validado-9barragens`).

## Instalação
Veja **[INSTALL.md](INSTALL.md)** — instalar o QGIS, copiar os scripts, criar o
`ms2_config.json`, colocar o ANADEM e rodar o passo a passo (Scripts 1→5).

## Conteúdo
- `scripts/ms2_1_cria_ambiente.py` … `ms2_5_perigo.py` — o pipeline (Scripts 1 a 5)
- `scripts/ms2_35_hidraulica_mancha_perigo.py` — atalho que roda 3+4+5 de uma vez
- `scripts/coeficientes_ana2024.json` — tabelas de decaimento de vazão
- `ms2_config.example.json` — modelo de configuração de caminhos

## Validação
O pipeline foi comparado com os produtos oficiais de técnicos da ANA em 9
barragens (IoU±1px entre 96% e 99%). Relatório em `../QGIS_MS2/`.

## Licença
GPL-3.0-or-later — veja **[LICENSE](LICENSE)**. Escolhida por compatibilidade
com o QGIS (também GPL). *A definição do detentor do copyright (pessoa física
ou a instituição) deve ser confirmada com a ANA antes de publicação.*

## Próximos passos
- [x] Config (`ms2_config.json`) para remover caminhos fixos
- [x] Script combinado 3-5
- [x] Manual de instalação (`INSTALL.md`)
- [x] Licença (GPL-3.0, texto completo incluído)
- [ ] Dado de exemplo (uma barragem para teste)
- [ ] Teste ponta a ponta num perfil de teste do QGIS
