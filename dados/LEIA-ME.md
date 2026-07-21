# Cadastro SNISB (opcional)

`barragens_ana_processado.csv` — cadastro do SNISB processado. O Script 1 o usa
para **buscar volume e altura automaticamente pelo codigo da barragem** (quando
esses campos sao deixados em branco).

## Onde colocar
Copie este arquivo para a pasta `raiz` definida no seu `ms2_config.json`
(ex.: `C:/Users/voce/Documents/Barragens/barragens_ana_processado.csv`).
Ou aponte o caminho no config: `{ "raiz": "...", "cadastro_csv": "..." }`.

E' **opcional**: sem ele, basta informar volume e altura manualmente no Script 1.

---
**Procedencia:** derivado do cadastro publico do SNISB/ANA. Antes de publicar o
repositorio, confirme com a ANA a permissao de redistribuir estes dados.
