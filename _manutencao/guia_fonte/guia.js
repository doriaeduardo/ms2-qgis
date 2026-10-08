// Gera o Guia_MS2_QGIS_23508.docx (fluxo basico, Scripts 1->5, secoes manuais).
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, ImageRun, ExternalHyperlink, AlignmentType, BorderStyle, ShadingType,
} = require('docx');

const FIG = path.join(__dirname, 'fig');
const DIMS = JSON.parse(fs.readFileSync(path.join(__dirname, 'dims.json'), 'utf8'));
const AZUL = '1F4E79', CINZA = '595959';

// **negrito** dentro do texto
function runs(texto, extra = {}) {
  // URLs viram links clicaveis no PDF
  return texto.split(/(\*\*[^*]+\*\*|https?:\/\/\S+)/).filter(Boolean).map(t =>
    t.startsWith('**') ? new TextRun({ text: t.slice(2, -2), bold: true, font: 'Calibri', size: 22, ...extra })
    : /^https?:/.test(t) ? new ExternalHyperlink({ link: t, children: [new TextRun({ text: t, style: 'Hyperlink', color: '0563C1', underline: {}, font: 'Calibri', size: 22 })] })
                       : new TextRun({ text: t, font: 'Calibri', size: 22, ...extra }));
}
const P = (t, o = {}) => new Paragraph({ spacing: { after: o.after ?? 80 }, indent: o.ind ? { left: o.ind } : undefined, children: runs(t) });
const PK = t => new Paragraph({ spacing: { after: 80 }, keepNext: true, keepLines: true, children: runs(t) });
const PKS = t => new Paragraph({ spacing: { after: 60 }, indent: { left: 360 }, keepNext: true, keepLines: true, children: runs(t) });
const SUB = t => P(t, { ind: 360, after: 60 });
const H = t => new Paragraph({ spacing: { before: 280, after: 100 },
  children: [new TextRun({ text: t, bold: true, color: AZUL, size: 30, font: 'Calibri' })] });
const CAP = t => new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 180 },
  children: [new TextRun({ text: t, italics: true, color: CINZA, size: 17, font: 'Calibri' })] });
function IMG(nome, larguraPol) {
  const [w, h] = DIMS[nome];
  const pw = Math.round(larguraPol * 96);
  return new Paragraph({ alignment: AlignmentType.CENTER, keepNext: true, keepLines: true, spacing: { before: 60, after: 40 },
    children: [new ImageRun({ type: 'jpg', data: fs.readFileSync(path.join(FIG, nome)),
      transformation: { width: pw, height: Math.round(pw * h / w) } })] });
}
// caixa de destaque (borda esquerda azul + fundo claro)
const NOTA = t => new Paragraph({ spacing: { before: 60, after: 140 }, indent: { left: 120 },
  border: { left: { style: BorderStyle.SINGLE, size: 18, color: AZUL, space: 8 } },
  shading: { type: ShadingType.CLEAR, color: 'auto', fill: 'EAF1F8' }, children: runs(t) });

const c = [];
c.push(new Paragraph({ spacing: { after: 60 }, children: [new TextRun({ text: 'Como gerar a mancha de inundação por ruptura de barragem', bold: true, size: 40, color: AZUL, font: 'Calibri' })] }));
c.push(new Paragraph({ spacing: { after: 200 }, children: [new TextRun({ text: 'Pipeline MS 2.0 da ANA no QGIS — passo a passo com a barragem de exemplo (23508)', size: 24, color: CINZA, font: 'Calibri' })] }));

c.push(P('**Você vai precisar de:** QGIS 3.34 ou mais novo, o terreno ANADEM (arquivo removepits.tif, 67 GB — o link de download está no passo 5) e o pacote MS2_ferramenta (arquivo .zip).'));
c.push(NOTA('**O ponto que mais trava a instalação é colocar cada arquivo na pasta certa.** São três pastas diferentes: (1) a **pasta de scripts do QGIS**, que recebe os scripts e o ms2_config.json; (2) a **pasta de dados**, que chamamos de **raiz** (neste guia, Documentos\\Barragens), com o ANADEM e o cadastro SNISB; e (3) a **Pasta de Trabalho**, onde ficam os resultados de cada barragem. O ms2_config.json é o arquivo que diz ao QGIS onde está a pasta de dados.'));

// ---------------- Parte 1
c.push(H('Parte 1 — Instalar a ferramenta (só na primeira vez)'));
c.push(PK('1. Descompacte o MS2_ferramenta (.zip) numa pasta qualquer (por exemplo, Downloads). Dentro dele, a pasta **MS2_ferramenta\\scripts** tem 8 arquivos — são eles que vão para o QGIS.'));
c.push(IMG('f03b_scripts_pacote.jpg', 6.6)); c.push(CAP('A pasta scripts do pacote: 6 scripts (.py), o coeficientes_ana2024.json e o MDT_estilo_ANA.qml'));

c.push(PK('2. No QGIS, abra a pasta do seu perfil: **Configurações → Perfis de Usuários → Abrir Pasta de Perfil Ativo**.'));
c.push(IMG('f02_menu_perfil.jpg', 4.6)); c.push(CAP('No seu QGIS o perfil normalmente se chama "default" (aqui aparece o perfil de teste "orgao_teste")'));
c.push(PK('3. O Explorador de Arquivos abre na pasta do perfil, que fica em C:\\Users\\<seu usuário>\\AppData\\Roaming\\QGIS\\QGIS3\\profiles\\default. A pasta AppData é **oculta**, por isso use sempre este menu para chegar até ela. Entre em **processing** e depois em **scripts** (se a pasta scripts não existir, crie-a).'));
c.push(IMG('f03a_pasta_perfil.jpg', 6.6)); c.push(CAP('A pasta do perfil, com o caminho completo na barra de endereço. Entre em processing → scripts'));
c.push(P('4. Copie para dentro dessa pasta scripts **todos os 8 arquivos** da pasta scripts do pacote (passo 1): selecione tudo (Ctrl+A), copie (Ctrl+C) e cole (Ctrl+V).'));

c.push(PK('5. Crie a **pasta de dados**: em **Documentos**, crie a pasta **Barragens** e, dentro dela, a pasta **MDTs**. Baixe o ANADEM pelo link liberado pela ANA — https://metadados.snirh.gov.br/files/5fd2b554-8576-4f14-b387-96036c69a08b/removepits.tif — e coloque o arquivo **removepits.tif** dentro de MDTs, **sem mudar o nome**. São 67 GB: use um gerenciador de downloads que retome o download se a conexão cair (por exemplo, o Free Download Manager, gratuito). Copie também o arquivo **barragens_ana_processado.csv** (pasta dados do pacote) para dentro de **Barragens** — não dentro de MDTs. É ele que preenche sozinho o volume, a altura e a coordenada a partir do código da barragem.'));
c.push(IMG('f04a_pasta_barragens.jpg', 6.6)); c.push(CAP('Documentos\\Barragens: a pasta MDTs e o barragens_ana_processado.csv, lado a lado'));
c.push(IMG('f04b_pasta_mdts.jpg', 6.6)); c.push(CAP('Documentos\\Barragens\\MDTs: o ANADEM (removepits.tif)'));

c.push(P('6. Descubra o caminho da pasta Barragens: com ela aberta no Explorador, clique na parte vazia da barra de endereço — o caminho aparece em texto (por exemplo, C:\\Users\\<seu usuário>\\Documents\\Barragens). Copie-o (Ctrl+C). Repare que "Documentos" aparece como **Documents** no caminho real.'));
c.push(PK('7. Abra o **Bloco de Notas** e escreva a linha abaixo, colando o seu caminho e **trocando todas as barras \\ por /**:'));
c.push(IMG('f05a_config_bloco.jpg', 5.6)); c.push(CAP('Conteúdo do ms2_config.json: { "raiz": "C:/Users/SEU_USUARIO/Documents/Barragens" }'));
c.push(PK('8. Salve com **Arquivo → Salvar como** (Ctrl+Shift+S). Navegue até a pasta scripts do passo 3 (dica: cole o caminho dela no campo Nome e tecle Enter), digite o nome **ms2_config.json** e, em **Tipo**, escolha **Todos os arquivos** (*.*). Clique em Salvar.'));
c.push(IMG('f05b_salvar_como.jpg', 4.6)); c.push(CAP('Salvar como: pasta scripts do perfil, nome ms2_config.json e Tipo "Todos os arquivos"'));
c.push(PK('9. Confira a pasta scripts: devem estar os 8 arquivos e o **ms2_config.json**, com o tipo **Arquivo Fonte JSON**. Se aparecer "Documento de texto", o arquivo ficou com o nome ms2_config.json.txt — renomeie (no Explorador, ligue Visualizar → Mostrar → Extensões de nomes de arquivos para ver o nome completo).'));
c.push(IMG('f05c_scripts_final.jpg', 6.6)); c.push(CAP('Pasta scripts pronta: 8 arquivos do pacote + ms2_config.json (Arquivo Fonte JSON)'));
c.push(PK('10. Feche e reabra o QGIS. Abra **Processamento → Caixa de Ferramentas** (Ctrl+Alt+T) e busque **MS 2.0**: devem aparecer os 6 algoritmos do grupo **MS 2.0 ANA**. Pronto — instalado.'));
c.push(IMG('f06_caixa_ferramentas.jpg', 2.6)); c.push(CAP('Grupo MS 2.0 ANA na Caixa de Ferramentas'));

// ---------------- Parte 2
c.push(H('Parte 2 — Rodar o exemplo (barragem 23508)'));
c.push(PK('11. Crie a pasta onde ficarão os resultados — por exemplo, **Documentos\\Barragens\\Resultados**. Abra **MS 2.0 ANA → 1 - Cria Ambiente**, informe essa pasta em **Pasta de Trabalho** e digite **23508** em **ID da Barragem**. Deixe o resto como está e clique em **Executar**.'));
c.push(IMG('f07a_script1_param.jpg', 4.6)); c.push(CAP('1 - Cria Ambiente: só a Pasta de Trabalho e o ID'));
c.push(PK('12. Confira o **Log**: tem que aparecer a linha **SNISB: Fazenda Dois Corações | vol=0.119 hm3 ...**, o Dmax de 6,77 km e a vazão de pico Qmax de 74,5 m³/s. Se a linha SNISB não aparecer, o barragens_ana_processado.csv não está na pasta Barragens (passo 5) ou o caminho do ms2_config.json está errado (passo 7).'));
c.push(IMG('f07b_script1_log.jpg', 4.6)); c.push(CAP('Log do Script 1: dados do SNISB, Dmax, Qmax e o estilo do terreno aplicado'));
c.push(PK('13. O resultado: o terreno é recortado e aparecem o pino da barragem e as camadas 23508_Rio e 23508_SecTrans (ainda vazias).'));
c.push(IMG('f07c_terreno.jpg', 6.6)); c.push(CAP('Terreno recortado e centrado na barragem; camadas de rio e seções criadas'));

c.push(P('14. Traga para o QGIS os arquivos **B23508_Rio** e **B23508_Secoes_Transversais** (pasta exemplos do pacote) — arraste-os do Explorador para o mapa, ou use Camada → Adicionar camada → Adicionar camada vetorial. Depois copie a geometria deles para as camadas vazias do passo 13:'));
c.push(SUB('a) No painel Camadas, clique em B23508_Rio, selecione todas as feições (Ctrl+A) e copie (Ctrl+C).'));
c.push(SUB('b) Clique na camada 23508_Rio, ligue a edição (ícone do lápis), cole (Ctrl+V), salve a edição (ícone do disquete) e desligue o lápis.'));
c.push(PKS('c) Repita a) e b) copiando de B23508_Secoes_Transversais para 23508_SecTrans (são 55 seções).'));
c.push(IMG('f08a_barra_edicao.jpg', 5.6)); c.push(CAP('Barra de edição: o lápis amarelo liga/desliga a edição; o disquete salva; à direita dele fica o botão de desenhar linha'));
c.push(IMG('f08b_camadas.jpg', 2.6)); c.push(CAP('Durante a edição, a camada mostra um lápis ao lado do nome'));

c.push(PK('15. Abra **MS 2.0 ANA → 2 - Rio e Seções**. Preencha a Pasta de Trabalho e o ID (23508) e clique em Executar. No Log deve aparecer **Rio: 6721 m | 55 secao(oes)**.'));
c.push(IMG('f09a_script2_param.jpg', 4.6)); c.push(CAP('2 - Rio e Seções'));
c.push(IMG('f09b_rio_secoes.jpg', 6.6)); c.push(CAP('Rio (linha ao centro) e as 55 seções transversais sobre o terreno'));
c.push(PK('16. Abra **MS 2.0 ANA → 3-5 - Hidráulica + Mancha + Perigo (tudo)**. Preencha a Pasta de Trabalho e o ID. Deixe o Coeficiente de Manning em **0,035** e o Método de decaimento em **ANA 2014 (MS1)**. Clique em Executar.'));
c.push(IMG('f10_script35_param.jpg', 4.6)); c.push(CAP('3-5: Manning 0,035 e decaimento ANA 2014 (MS1)'));
c.push(PK('17. Pronto! Aparecem a mancha de inundação e o perigo hidrodinâmico por faixas. Para a 23508, a mancha fica em torno de **120–127 ha** (o valor exato varia um pouco com a versão do ANADEM) — se chegou perto disso, a instalação está correta.'));
c.push(IMG('f11_resultado.jpg', 6.6)); c.push(CAP('Resultado final: perigo hidrodinâmico por faixas e mancha (~122 ha)'));

// ---------------- Parte 3
c.push(H('Parte 3 — Agora desenhe você mesmo (exercício)'));
c.push(P('Na Parte 2, o rio e as seções vieram prontos (desenhados por um técnico da ANA) e serviram para conferir a instalação. Numa barragem real, é você quem desenha os dois — é a etapa que exige prática de SIG e a que mais influencia o resultado. Refaça a 23508 desenhando:'));
c.push(P('18. Abra um projeto novo (Projeto → Novo) e rode de novo o 1 - Cria Ambiente com o ID 23508, mas escolha **outra Pasta de Trabalho** (ex.: Documentos\\Barragens\\23508_desenho) — na mesma pasta, as camadas da Parte 2 seriam apagadas. No log, a linha **Dmax (extensao da mancha) = 6.77 km | espacamento secoes = 338 m** indica que o rio deve ter cerca de 6,8 km e as seções devem ficar a no máximo ~340 m uma da outra.'));
c.push(P('19. **Rio** (camada 23508_Rio):'));
c.push(SUB('a) No painel Camadas, clique em 23508_Rio e ligue a edição (ícone do lápis).'));
c.push(SUB('b) Clique no botão **Adicionar Linha** (à direita do disquete, ver a barra de edição do passo 14). Comece junto ao pino da barragem e vá clicando pelo fundo do vale, rio abaixo, até cerca de 6,8 km (o Dmax). Clique com o botão direito para terminar e confirme com OK.'));
c.push(SUB('c) Salve a edição (disquete). O rio é uma linha só, sempre pelo ponto mais baixo do vale.'));
c.push(P('20. **Seções** (camada 23508_SecTrans):'));
c.push(SUB('a) Clique em 23508_SecTrans, ligue a edição e use Adicionar Linha. Cada seção é uma reta (um clique em cada lado e botão direito para terminar) que atravessa o vale de uma encosta à outra, perpendicular ao rio.'));
c.push(SUB('b) Regras: toda seção tem que cruzar o rio (as que não cruzam são ignoradas); as seções não podem se cruzar; cada uma deve ir além da área que pode inundar, até terreno mais alto dos dois lados; comece perto da barragem e vá até o fim do rio; ponha mais seções onde o vale estreita, alarga ou faz curva.'));
c.push(SUB('c) Salve a edição e desligue o lápis.'));
c.push(P('21. Rode o 2 - Rio e Seções e o 3-5, como nos passos 15 e 16, com a nova Pasta de Trabalho.'));
c.push(P('22. Compare com a Parte 2: arraste os arquivos B23508_Rio e B23508_Secoes_Transversais (pasta exemplos) por cima do seu desenho — compare com a figura do passo 15 — e veja no log a linha "Area inundada". O resultado não precisa ser igual aos 120–127 ha da Parte 2: a diferença vem do desenho. Se ficar muito diferente, procure onde o seu desenho se afasta do técnico (seções curtas que não chegam ao terreno alto, rio fora do fundo do vale, seções muito espaçadas).'));
c.push(P('Numa barragem real, o processo é este: Parte 2 com o rio e as seções desenhados como na Parte 3 — só que sem o desenho do técnico para conferir.'));

// ---------------- Problemas
c.push(H('Se algo der errado'));
c.push(P('• **Os algoritmos não aparecem na Caixa de Ferramentas** → os arquivos não estão na pasta scripts do perfil certo. Refaça os passos 2 a 4 (sempre pelo menu Abrir Pasta de Perfil Ativo) e reinicie o QGIS.'));
c.push(P('• **Volume, altura e coordenada não são preenchidos (não aparece a linha SNISB no log)** → o barragens_ana_processado.csv não está dentro da pasta raiz (Barragens), ou o caminho no ms2_config.json está errado. Confira os passos 5 a 9.'));
c.push(P('• **"Nenhuma fonte ANADEM encontrada" ou "MDE não pode ser carregado"** → o ANADEM não está em Barragens\\MDTs ou não se chama exatamente removepits.tif (confira a extensão .tif; se o download não terminou, o arquivo fica incompleto — baixe de novo).'));
c.push(P('• **O Script 1 dá erro logo no início, citando o ms2_config.json ou JSON** → o arquivo tem barra invertida simples (\\) — use / — ou ficou com o nome ms2_config.json.txt.'));

const doc = new Document({
  styles: { default: { document: { run: { font: 'Calibri', size: 22 } } } },
  sections: [{ properties: { page: { size: { width: 12240, height: 15840 },
    margin: { top: 907, right: 1020, bottom: 907, left: 1020 } } }, children: c }],
});
Packer.toBuffer(doc).then(b => { fs.writeFileSync(path.join(__dirname, 'Guia_MS2_QGIS_23508.docx'), b); console.log('ok', b.length); });
