# MS 2.0 ANA — Pipeline QGIS (mancha de inundação e perigo por ruptura de barragem)

Implementação aberta do Método Simplificado 2.0 da ANA em Processing Scripts do QGIS.
Gera, a partir dos dados de uma barragem, a **mancha de inundação** e o **perigo
hidrodinâmico (h×v)** por ruptura, seguindo o método oficial da ANA.

### ⬇️ [Baixe a última versão](https://github.com/doriaeduardo/ms2-qgis/releases/latest)

Baixe o `MS2_ferramenta_vX.Y.zip` e siga o **[INSTALL.md](INSTALL.md)**.
Requer apenas **QGIS 3.34+** e o MDT **ANADEM** — nenhuma biblioteca Python
adicional (GDAL e numpy já vêm no QGIS).

## Validação

O pipeline foi comparado com os produtos oficiais de técnicos da ANA em
**10 barragens**, rodando a nossa implementação sobre a **mesma geometria de
entrada** (rio e seções transversais do técnico) e com os **mesmos parâmetros**
da planilha oficial:

- mancha de inundação reproduzida com **96–99% de concordância** (IoU ±1px);
- **vazão de pico (Froehlich)** e **decaimento MS1** idênticos à planilha oficial
  em todas as barragens.

A versão exata que produziu essa validação está marcada na tag
[`v0.1-validado-9barragens`](https://github.com/doriaeduardo/ms2-qgis/releases).

## Conteúdo

- `scripts/ms2_1_cria_ambiente.py` … `ms2_5_perigo.py` — o pipeline (Scripts 1 a 5)
- `scripts/ms2_35_hidraulica_mancha_perigo.py` — atalho que roda 3+4+5 de uma vez
- `scripts/coeficientes_ana2024.json` — tabelas de decaimento de vazão
- `scripts/MDT_estilo_ANA.qml` — estilo (cores) do terreno no padrão da ANA
- `ms2_config.example.json` — modelo de configuração de caminhos
- `exemplos/23508_Fazenda_Dois_Coracoes/` — barragem de exemplo para testar a instalação
- `dados/barragens_ana_processado.csv` — cadastro SNISB (opcional, busca automática de volume/altura)

## Como funciona

1. **Script 1 – Cria Ambiente**: recorta o MDT, calcula a vazão de pico (Froehlich)
   e o alcance máximo, e cria as camadas de rio/seções.
2. **Desenhe a geometria**: eixo do rio e seções transversais (padrão oficial da ANA
   = seções manuais).
3. **Script 2 – Rio e Seções**: extrai o perfil de cada seção a partir do MDT.
4. **Script 3 – Hidráulica**: Manning + correção de remanso + decaimento da vazão.
5. **Scripts 4 e 5 – Mancha e Perigo**: mapeiam a inundação e o perigo (h×v).
   *(ou use o atalho **3-5** que roda os três de uma vez)*

## Licença

GPL-3.0-or-later — veja **[LICENSE](LICENSE)**. Escolhida por compatibilidade com
o QGIS (também GPL).

## Créditos e procedência dos dados

- **ANADEM** (modelo de terreno): Laipelt, L. et al. *ANADEM: A Digital Terrain
  Model for South America.* Remote Sensing, 2024, 16(13), 2321.
  [doi:10.3390/rs16132321](https://doi.org/10.3390/rs16132321) — licença MIT.
- **Método Simplificado 2.0**: Agência Nacional de Águas e Saneamento Básico (ANA).
- Os dados de exemplo (rio e seções da barragem 23508) e o cadastro SNISB
  processado são derivados de trabalho da ANA, incluídos aqui para fins de teste
  e validação.
