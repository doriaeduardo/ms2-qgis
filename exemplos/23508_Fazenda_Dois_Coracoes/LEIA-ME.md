# Exemplo — Barragem 23508 (Fazenda Dois Corações / Ouro Branco-RN)

Barragem pequena, boa para **testar a instalação de ponta a ponta**. Contém o
eixo do rio e as seções transversais já desenhados; você roda o pipeline por
cima e confere se o resultado bate com os valores esperados abaixo.

## Arquivos
- `B23508_Rio.shp` — eixo do rio (1 linha, ~6.721 m)
- `B23508_Secoes_Transversais.shp` — 55 seções transversais

Ambos em **EPSG 31984** (SIRGAS 2000 / UTM 24S).

## Dados da barragem (para o Script 1)
| Parâmetro | Valor |
|---|---|
| Código SNISB | 23508 |
| Coordenada (UTM 24S) | X = 731612, Y = 9260473 |
| Volume | 0,119 hm³ |
| Altura | 3 m |
| Fuso / Hemisfério | 24 / Sul |
| Manning (n) | 0,035 |
| Decaimento (Qx) | ANA 2014 (MS1) |

## Passo a passo do teste
1. **Script 1 – Cria Ambiente**: informe os dados acima (ID `23508`, coordenada,
   fuso 24, volume 0,119, altura 3). Escolha uma Pasta de Trabalho.
   *Esperado:* Qmax (Froehlich) ≈ **74,5 m³/s**.
2. **Importe a geometria**: substitua as camadas `23508_Rio` e `23508_SecTrans`
   (vazias, criadas pelo Script 1, no GeoPackage) pela geometria deste exemplo
   (`B23508_Rio` e `B23508_Secoes_Transversais`).
3. **Script 2 – Rio e Seções**: extrai os perfis (55 seções).
4. **Script 3-5 (tudo)** ou os Scripts 3, 4 e 5: use n = 0,035 e método Qx = MS1.

## Resultado esperado
- Mancha de inundação ≈ **120–127 ha** (122 ha com o ANADEM usado na validação;
  126 ha com o `removepits.tif` do link oficial — a diferença é uma borda de
  menos de 1 pixel).
- Comparada com o produto oficial do técnico da ANA para esta barragem:
  **IoU ≈ 79%**, **IoU±1px ≈ 96%**, extensão do perigo ≈ 81%.
- Se você chegar perto desses números, a instalação está correta.

---
**Procedência dos dados:** rio e seções produzidos por técnico da ANA (usados
aqui apenas para teste/validação). Antes de tornar o repositório público,
confirme com a ANA a permissão para redistribuir estes arquivos de dados — o
código é GPL, mas os dados são de terceiros.
