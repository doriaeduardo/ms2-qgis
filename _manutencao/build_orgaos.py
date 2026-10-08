# -*- coding: utf-8 -*-
"""
Build do pacote distribuivel aos orgaos fiscalizadores (MS 2.0 ANA no QGIS).

Gera MS2_ferramenta_v<VERSAO>.zip a partir da FONTE UNICA (esta pasta
MS2_ferramenta/), sem tocar nos originais. As diferencas do pacote dos orgaos
sao aplicadas numa copia temporaria (staging):

  1. ENTREGAR com padrao False no ms2_5_perigo.py (uso interno da ANA fica True);
  2. fora do zip: CLAUDE.md, _manutencao/, .git, __pycache__, ms2_config.json,
     *.zip, *.disabled, *.bak*, .gitignore e o importador 1b
     (ms2_1b_importar_geometria.py), que nao e' ensinado aos orgaos.

Depois confere o resultado (scripts compilam, ENTREGAR=False, nada pessoal,
nenhuma mencao a 1b/entrega/carimbo nos documentos) e so entao grava o zip.

Uso (Python 3 comum, so biblioteca padrao):
    python _manutencao/build_orgaos.py 0.4
    python _manutencao/build_orgaos.py 0.4 --saida D:/dist --sobrescrever
    python _manutencao/build_orgaos.py 0.4 --ignorar-docs   (so p/ teste: nao
        barra o build se os PDFs ainda mencionarem o 1b/entrega/carimbo)
"""
import argparse
import fnmatch
import os
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

FONTE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA_ZIP = 'MS2_ferramenta'   # pasta-raiz dentro do zip

# O que entra no pacote (relativo a FONTE). Tudo o mais fica de fora.
INCLUIR = ['INSTALL.md', 'README.md', 'LICENSE', 'ms2_config.example.json',
           'scripts', 'docs', 'dados', 'exemplos']

# Excluidos mesmo dentro das pastas incluidas.
EXCLUIR = ['__pycache__', '*.pyc', 'ms2_config.json', '*.zip', '*.disabled',
           '*.bak', '*.bak*', '.gitignore', 'ms2_1b_importar_geometria.py',
           'CLAUDE.md', '_manutencao', '.git', 'Thumbs.db', 'desktop.ini']

# Scripts que o pacote TEM que conter (os que o INSTALL.md manda copiar).
SCRIPTS_OBRIGATORIOS = ['ms2_1_cria_ambiente.py', 'ms2_2_rio_secoes.py',
                        'ms2_3_hidraulica.py', 'ms2_4_manchas.py',
                        'ms2_5_perigo.py', 'ms2_35_hidraulica_mancha_perigo.py',
                        'coeficientes_ana2024.json', 'MDT_estilo_ANA.qml']

# Termos que nao podem aparecer nos documentos dos orgaos (decisao do mantenedor).
TERMOS_PROIBIDOS_DOCS = [r'\b1b\b', r'importar rio', r'importar_geometria',
                         r'entreg\w* para a classifica', r'carimbo', r'rodada_id']

# Marcas de caminho pessoal/da maquina do mantenedor.
TERMOS_PESSOAIS = [r'Users[\\/]+Eduardo', r'doriaeduardoo@']


def _excluido(nome):
    return any(fnmatch.fnmatch(nome, p) for p in EXCLUIR)


def _copiar(stage):
    for item in INCLUIR:
        src = os.path.join(FONTE, item)
        if not os.path.exists(src):
            raise SystemExit('ERRO: item do pacote nao existe na fonte: %s' % item)
        dst = os.path.join(stage, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst, ignore=lambda d, nomes: [n for n in nomes if _excluido(n)])
        else:
            shutil.copy2(src, dst)


def _desligar_entregar(stage):
    caminho = os.path.join(stage, 'scripts', 'ms2_5_perigo.py')
    with open(caminho, 'rb') as f:
        txt = f.read().decode('utf-8')
    novo, n = re.subn(r'(self\.ENTREGAR,.*?defaultValue=)True', r'\1False', txt,
                      count=1, flags=re.S)
    if n != 1:
        raise SystemExit('ERRO: nao achei "defaultValue=True" do parametro ENTREGAR '
                         'no ms2_5_perigo.py - o script mudou? Ajuste o build.')
    with open(caminho, 'wb') as f:
        f.write(novo.encode('utf-8'))   # preserva as quebras de linha originais


def _texto_pdf(caminho):
    exe = shutil.which('pdftotext')
    if not exe:
        return None
    r = subprocess.run([exe, '-q', '-enc', 'UTF-8', caminho, '-'],
                       capture_output=True)
    return r.stdout.decode('utf-8', 'replace')


def _conferir(stage, ignorar_docs):
    erros, avisos = [], []

    # 1) scripts obrigatorios presentes e o 1b ausente
    pasta_s = os.path.join(stage, 'scripts')
    for s in SCRIPTS_OBRIGATORIOS:
        if not os.path.exists(os.path.join(pasta_s, s)):
            erros.append('falta scripts/%s' % s)
    for raiz, _, nomes in os.walk(stage):
        for n in nomes:
            if _excluido(n):
                erros.append('arquivo excluido entrou no pacote: %s'
                             % os.path.relpath(os.path.join(raiz, n), stage))

    # 2) todos os .py compilam
    for n in sorted(os.listdir(pasta_s)):
        if n.endswith('.py'):
            try:
                py_compile.compile(os.path.join(pasta_s, n), doraise=True,
                                   cfile=os.path.join(tempfile.gettempdir(), '_ms2_build.pyc'))
            except py_compile.PyCompileError as e:
                erros.append('scripts/%s nao compila: %s' % (n, e.msg))

    # 3) ENTREGAR desligado
    with open(os.path.join(pasta_s, 'ms2_5_perigo.py'), encoding='utf-8') as f:
        p5 = f.read()
    if not re.search(r'self\.ENTREGAR,.*?defaultValue=False', p5, flags=re.S):
        erros.append('ENTREGAR nao ficou com padrao False no ms2_5_perigo.py')

    # 4) nada pessoal em arquivos de texto; termos proibidos nos documentos
    for raiz, _, nomes in os.walk(stage):
        for n in nomes:
            p = os.path.join(raiz, n)
            rel = os.path.relpath(p, stage).replace('\\', '/')
            ext = os.path.splitext(n)[1].lower()
            if ext in ('.py', '.md', '.json', '.txt', '.prj', '.cpg', '.qml'):
                with open(p, encoding='utf-8', errors='replace') as f:
                    txt = f.read()
            elif ext == '.pdf':
                txt = _texto_pdf(p)
                if txt is None:
                    avisos.append('pdftotext nao encontrado - %s nao foi conferido' % rel)
                    continue
            else:
                continue
            for t in TERMOS_PESSOAIS:
                if re.search(t, txt, flags=re.I):
                    erros.append('%s contem caminho/dado pessoal (%s)' % (rel, t))
            if ext in ('.md', '.pdf'):
                for t in TERMOS_PROIBIDOS_DOCS:
                    m = re.search(t, txt, flags=re.I)
                    if m:
                        linha = txt[max(0, m.start() - 60):m.end() + 60].replace('\n', ' ')
                        msg = '%s menciona recurso fora do escopo dos orgaos (%s): "...%s..."' % (
                            rel, t, linha.strip())
                        (avisos if ignorar_docs else erros).append(msg)
    return erros, avisos


def _zipar(stage, destino):
    with zipfile.ZipFile(destino, 'w', zipfile.ZIP_DEFLATED) as z:
        for raiz, dirs, nomes in os.walk(stage):
            dirs.sort()
            for n in sorted(nomes):
                p = os.path.join(raiz, n)
                arc = PASTA_ZIP + '/' + os.path.relpath(p, stage).replace('\\', '/')
                z.write(p, arc)


def main():
    # console do Windows (cp1252) nao imprime setas/acentos dos PDFs
    try:
        sys.stdout.reconfigure(errors='replace')
    except AttributeError:
        pass
    ap =argparse.ArgumentParser(description='Gera o zip do MS 2.0 para os orgaos.')
    ap.add_argument('versao', help='ex.: 0.4  (gera MS2_ferramenta_v0.4.zip)')
    ap.add_argument('--saida', default=FONTE, help='pasta do zip (padrao: MS2_ferramenta/)')
    ap.add_argument('--sobrescrever', action='store_true', help='substitui zip existente')
    ap.add_argument('--ignorar-docs', action='store_true',
                    help='rebaixa a aviso as mencoes a 1b/entrega/carimbo nos docs (so p/ teste)')
    a = ap.parse_args()

    if not re.fullmatch(r'\d+\.\d+(\.\d+)?', a.versao):
        raise SystemExit('ERRO: versao invalida "%s" (use p.ex. 0.4)' % a.versao)
    destino = os.path.join(os.path.abspath(a.saida), 'MS2_ferramenta_v%s.zip' % a.versao)
    if os.path.exists(destino) and not a.sobrescrever:
        raise SystemExit('ERRO: %s ja existe (use --sobrescrever)' % destino)

    with tempfile.TemporaryDirectory(prefix='ms2_build_') as tmp:
        stage = os.path.join(tmp, PASTA_ZIP)
        os.makedirs(stage)
        _copiar(stage)
        _desligar_entregar(stage)
        erros, avisos = _conferir(stage, a.ignorar_docs)
        for m in avisos:
            print('AVISO:', m)
        if erros:
            for m in erros:
                print('ERRO: ', m)
            raise SystemExit('\nBuild ABORTADO (%d erro(s)); nenhum zip gravado.' % len(erros))
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        _zipar(stage, destino)

    with zipfile.ZipFile(destino) as z:
        nomes = z.namelist()
    print('\nOK: %s (%d arquivos, %.1f MB)' % (destino, len(nomes),
                                             os.path.getsize(destino) / 1e6))
    for n in nomes:
        print('   ', n)
    if a.ignorar_docs and avisos:
        print('\nATENCAO: gerado com --ignorar-docs. NAO distribuir este zip.')


if __name__ == '__main__':
    main()
