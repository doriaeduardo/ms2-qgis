# Instalação — Pipeline MS 2.0 ANA (QGIS)

Guia para instalar e rodar o pipeline de mancha de inundação e perigo hidrodinâmico
por ruptura de barragem (Método Simplificado 2.0 da ANA) em uma máquina nova.

Não é preciso instalar Python nem bibliotecas: tudo o que os scripts usam
(GDAL, numpy) já vem dentro do QGIS.

---

## 1. Requisitos

- **QGIS LTR** — versão 3.34 ou superior (testado no 3.44). Grátis: https://qgis.org
- **ANADEM** — o Modelo Digital de Elevação nacional de 30 m, arquivo
  `Anadem-BR-removepits.tif` (fonte de terreno padrão; arquivo grande).
- *(Opcional)* `barragens_ana_processado.csv` — cadastro SNISB, para buscar
  volume/altura automaticamente pelo código da barragem.

---

## 2. Copiar os scripts para o QGIS

1. Abra o QGIS.
2. Menu **Configurações → Perfis de Usuário → Abrir Pasta do Perfil Ativo**.
3. Dentro dela, entre em `processing\scripts\` (crie a pasta se não existir).
4. Copie para essa pasta:
   - os 6 scripts: `ms2_1_cria_ambiente.py`, `ms2_2_rio_secoes.py`,
     `ms2_3_hidraulica.py`, `ms2_4_manchas.py`, `ms2_5_perigo.py` e
     `ms2_35_hidraulica_mancha_perigo.py` (o combinado 3-5);
   - o arquivo `coeficientes_ana2024.json`.
5. Reinicie o QGIS.

Os scripts aparecem na **Caixa de Ferramentas de Processamento** (menu
Processar → Caixa de Ferramentas), no grupo **MS 2.0 ANA**.

---

## 3. Criar o `ms2_config.json`

Na **mesma pasta** `processing\scripts\`, crie um arquivo chamado
`ms2_config.json` com uma linha apontando a pasta onde ficarão seus dados:

```json
{ "raiz": "D:/GIS/Barragens" }
```

- Use barras normais `/` (ou barras duplas `\\`).
- O `coeficientes_ana2024.json` é encontrado **automaticamente** ao lado dos
  scripts — não precisa configurar.
- *(Opcional)* sobrescrever caminhos individuais, por exemplo o ANADEM num
  drive de rede:

```json
{
  "raiz": "D:/GIS/Barragens",
  "anadem": "//servidor/GIS/Anadem-BR-removepits.tif"
}
```

Chaves aceitas para sobrescrita: `mdt_dir`, `anadem`, `coeficientes`,
`cadastro_csv`, `estilo_qml`.

> Dica: há um modelo pronto em `ms2_config.example.json` — copie, renomeie
> para `ms2_config.json` e ajuste o `raiz`.

---

## 4. Colocar o ANADEM (e a estrutura de pastas)

Dentro da pasta `raiz` definida acima, crie uma subpasta `MDTs` e coloque o
ANADEM nela. Estrutura mínima:

```
D:/GIS/Barragens/            <- "raiz" do config
  MDTs/
    Anadem-BR-removepits.tif
  barragens_ana_processado.csv   (opcional)
```

*(Opcional)* Para a busca automática de volume/altura pelo código SNISB, copie
`dados/barragens_ana_processado.csv` (incluído no pacote) para a pasta `raiz`.
Sem ele, tudo funciona igual — basta informar volume e altura manualmente no
Script 1.

---

## 5. Rodar — passo a passo

Na Caixa de Ferramentas → **MS 2.0 ANA**, na ordem:

1. **1 - Cria Ambiente**
   Informe o ID da barragem, a coordenada (ou deixe buscar no SNISB pelo
   código), o fuso UTM, o volume (hm³) e a altura (m). Escolha a *Pasta de
   Trabalho* (onde ficarão as saídas e o `MS2.gpkg`). Gera: recorte do ANADEM,
   vazão de pico Qmax (Froehlich), alcance Dmax e as camadas vazias de
   rio/seções no GeoPackage.

2. **Desenhe a geometria**
   Digitalize o **eixo do rio** (camada `<ID>_Rio`) e as **seções
   transversais** (camada `<ID>_SecTrans`) no GeoPackage.
   *(Padrão oficial da ANA = seções manuais.)*

3. **2 - Rio e Seções**
   Extrai o perfil de cada seção amostrando o MDE (equivalente ao StackProfile).

4. **3 - Hidráulica**
   Manning + correção de remanso + decaimento da vazão. Defina o `n` (Manning) e
   o **método de decaimento Qx** — o padrão é **ANA 2014 (MS1)**, praxe atual da
   ANA. Confira o CSV de resultados antes de mapear.

5. **4 - Manchas** e **5 - Perigo**
   Geram a mancha de inundação e o perigo hidrodinâmico (h×v).

> **Atalho:** em vez dos passos 4 e 5 (e do 3), você pode rodar
> **3-5 - Hidráulica + Mancha + Perigo (tudo)**, que executa os três de uma vez
> com um único conjunto de parâmetros. Os individuais continuam disponíveis
> para calibração passo a passo (permitem conferir a hidráulica antes de mapear).

**Saídas:** na *Pasta de Trabalho*, em `<ID>/` (rasters de profundidade,
velocidade, h×v, perigo) e no `MS2.gpkg` (mancha e perigo vetoriais).

---

## 6. Problemas comuns

- **"ms2_config.json não encontrado"** (aparece **ao rodar** o Script 1) → crie
  o arquivo do passo 3 na pasta `processing\scripts\`. Os algoritmos carregam
  normalmente mesmo sem ele; o Script 1 só precisa dele para localizar o ANADEM.
- **"Nenhuma fonte ANADEM encontrada"** → confira se o
  `Anadem-BR-removepits.tif` está em `raiz/MDTs/` (ou ajuste `anadem` no config).
- **Shapefile do técnico sem `.shx`** → o QGIS/GDAL recupera automaticamente
  ativando `SHAPE_RESTORE_SHX=YES` (Configurações do GDAL) ou reexportando o
  shapefile completo.
- **Os algoritmos não aparecem** → confirme que os `.py` estão em
  `processing\scripts\` e reinicie o QGIS.
