# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# MS 2.0 ANA  ->  Porte para QGIS
# Script 2 de 4: Rio_Secoes (preparacao da geometria + perfis das secoes)
#
# Equivalente a RioSecoes.py da toolbox MS2.tbx (ANA), no fluxo de
# DIGITALIZACAO MANUAL: o tecnico desenha o rio (montante->jusante) e as
# secoes transversais; este script processa o que foi desenhado.
#
# O que faz:
#   - le o <ID>_MS2.json (MDE, CRS, Dmax) gerado pelo Script 1
#   - orienta o rio (barragem -> jusante)
#   - ordena as secoes pela distancia ao longo do rio (S0 na barragem)
#   - mede a distancia de cada secao e o comprimento de cada trecho
#   - extrai o perfil de cada secao amostrando o MDE (equivalente StackProfile)
#   - grava a tabela no formato 'SecoesBrutas' (CSV) + tabela de secoes (CSV)
#   - adiciona os campos ID, Di_m, dist_trecho_m em _SecTrans e prepara
#     cotamax/Velocidade (preenchidos depois pelo Script 3 - hidraulica)
# ---------------------------------------------------------------------------

import os
import csv
import json
import math

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFile,
    QgsProcessingParameterString,
    QgsProcessingParameterNumber,
    QgsProcessingParameterBoolean,
    QgsProcessingOutputString,
    QgsProcessingException,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    edit,
)


class RioSecoes(QgsProcessingAlgorithm):
    """2 - Rio_Secoes (MS 2.0 ANA / QGIS)."""

    PASTA = 'PASTA'
    ID_BAR = 'ID_BAR'
    PASSO = 'PASSO'
    CARREGAR = 'CARREGAR'

    OUT_SECOESBRUTAS = 'OUT_SECOESBRUTAS'
    OUT_SECOES = 'OUT_SECOES'

    def tr(self, s):
        return QCoreApplication.translate('Processing', s)

    def flags(self):
        # thread principal (mexe em camadas/projeto)
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    def createInstance(self):
        return RioSecoes()

    def name(self):
        return 'ms2_2_rio_secoes'

    def displayName(self):
        return self.tr('2 - Rio_Secoes')

    def group(self):
        return self.tr('MS 2.0 ANA')

    def groupId(self):
        return 'ms2ana'

    def shortHelpString(self):
        return self.tr(
            'Processa o rio e as secoes transversais DIGITALIZADAS MANUALMENTE '
            '(fluxo da ANA). Ordena as secoes de montante para jusante, mede as '
            'distancias, extrai o perfil de cada secao do MDE e gera a tabela '
            'no formato SecoesBrutas, pronta para a etapa hidraulica (Script 3).'
            '\n\nLe os dados do <ID>_MS2.json criado pelo Script 1.')

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            self.PASTA, self.tr('Pasta de Trabalho'),
            behavior=QgsProcessingParameterFile.Folder))
        self.addParameter(QgsProcessingParameterString(
            self.ID_BAR, self.tr('ID da Barragem (mesmo do Script 1)')))
        self.addParameter(QgsProcessingParameterNumber(
            self.PASSO,
            self.tr('Passo de amostragem do perfil (m) - vazio/0 = resolucao do MDE'),
            type=QgsProcessingParameterNumber.Double,
            optional=True, defaultValue=0, minValue=0))
        self.addParameter(QgsProcessingParameterBoolean(
            self.CARREGAR, self.tr('Carregar resultados no projeto'), defaultValue=True))

        self.addOutput(QgsProcessingOutputString(self.OUT_SECOESBRUTAS, self.tr('Tabela SecoesBrutas')))
        self.addOutput(QgsProcessingOutputString(self.OUT_SECOES, self.tr('Tabela de secoes')))

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _linha_unica(layer):
        """Une todas as feicoes da camada de linha numa unica geometria simples."""
        geoms = [f.geometry() for f in layer.getFeatures() if not f.geometry().isEmpty()]
        if not geoms:
            return None
        g = geoms[0]
        for extra in geoms[1:]:
            g = g.combine(extra)
        if g.isMultipart():
            merged = g.mergeLines()
            if merged and not merged.isEmpty():
                g = merged
        return g

    @staticmethod
    def _polilinha(geom):
        """Retorna a lista de QgsPointXY da geometria de linha (1a parte se multipart)."""
        if geom.isMultipart():
            partes = geom.asMultiPolyline()
            return partes[0] if partes else []
        return geom.asPolyline()

    def _orientar_rio(self, rio_geom, pin_xy, feedback):
        """Garante que o rio comece na barragem (ponto mais proximo do pin)."""
        pts = self._polilinha(rio_geom)
        if len(pts) < 2:
            raise QgsProcessingException('O rio precisa ter ao menos 2 vertices.')
        d_ini = math.hypot(pts[0].x() - pin_xy[0], pts[0].y() - pin_xy[1])
        d_fim = math.hypot(pts[-1].x() - pin_xy[0], pts[-1].y() - pin_xy[1])
        if d_fim < d_ini:
            feedback.pushInfo('Rio invertido para iniciar na barragem.')
            return QgsGeometry.fromPolylineXY(pts[::-1])
        return QgsGeometry.fromPolylineXY(pts)

    @staticmethod
    def _amostrar_perfil(sec_geom, mde_provider, passo):
        """Amostra a cota do MDE ao longo da secao (equivalente ao StackProfile).
        Retorna lista de (dist_along, cota)."""
        L = sec_geom.length()
        perfil = []
        d = 0.0
        while d <= L + 1e-6:
            p = sec_geom.interpolate(d)
            if p and not p.isEmpty():
                xy = p.asPoint()
                val, ok = mde_provider.sample(QgsPointXY(xy.x(), xy.y()), 1)
                if ok and val is not None and not (isinstance(val, float) and math.isnan(val)):
                    perfil.append((round(d, 3), round(float(val), 4)))
            d += passo
        return perfil

    @staticmethod
    def _suavizar_perfil(perfil, limiar=1.5, passadas=2):
        """Remove entalhes isolados de 1 ponto (pixel fundo isolado) que estreitam
        artificialmente a secao e inflam o WSE do Manning. Se um ponto interno for
        mais que 'limiar' (m) abaixo de AMBOS os vizinhos, sobe ao menor dos vizinhos.
        Aproxima o perfil ao StackProfile do tecnico (fundo largo)."""
        if len(perfil) < 3:
            return perfil
        ds = [d for d, _ in perfil]
        zs = [z for _, z in perfil]
        for _ in range(passadas):
            for i in range(1, len(zs) - 1):
                viz = zs[i - 1] if zs[i - 1] < zs[i + 1] else zs[i + 1]
                if zs[i] < viz - limiar:
                    zs[i] = viz
        return [(ds[i], round(zs[i], 4)) for i in range(len(perfil))]

    # -- execucao ------------------------------------------------------------
    def processAlgorithm(self, parameters, context, feedback):
        self._carregar_trechos = None
        pasta = self.parameterAsFile(parameters, self.PASTA, context)
        id_bar = self.parameterAsString(parameters, self.ID_BAR, context).strip()
        passo = self.parameterAsDouble(parameters, self.PASSO, context)
        carregar = self.parameterAsBool(parameters, self.CARREGAR, context)

        # 1) le a configuracao do Script 1
        pasta_barragem = os.path.join(pasta, id_bar)
        config_path = os.path.join(pasta_barragem, id_bar + '_MS2.json')
        if not os.path.exists(config_path):
            raise QgsProcessingException(
                'Config %s nao encontrado. Rode o Script 1 antes.' % config_path)
        with open(config_path, encoding='utf-8') as fp:
            cfg = json.load(fp)

        gpkg = cfg.get('gpkg') or os.path.join(pasta, 'MS2.gpkg')
        mde_path = cfg.get('mde')
        pin_xy = (cfg.get('x_utm'), cfg.get('y_utm'))
        if not mde_path or not os.path.exists(mde_path):
            raise QgsProcessingException('MDE nao encontrado: %s' % mde_path)
        if pin_xy[0] is None:
            raise QgsProcessingException('Config sem coordenada da barragem (x_utm/y_utm).')

        # 2) carrega rio e secoes
        rio = QgsVectorLayer('%s|layername=%s' % (gpkg, cfg['rio']), 'rio', 'ogr')
        sec = QgsVectorLayer('%s|layername=%s' % (gpkg, cfg['sectrans']), 'sec', 'ogr')
        if not rio.isValid() or not sec.isValid():
            raise QgsProcessingException('Nao foi possivel abrir as camadas _Rio/_SecTrans.')
        if rio.featureCount() < 1:
            raise QgsProcessingException('O rio (%s) esta vazio - digitalize-o.' % cfg['rio'])
        if sec.featureCount() < 1:
            raise QgsProcessingException('Nenhuma secao em %s - digitalize as secoes.' % cfg['sectrans'])

        # 3) rio como linha unica, orientado barragem -> jusante
        rio_geom = self._linha_unica(rio)
        if rio_geom is None:
            raise QgsProcessingException('Geometria do rio invalida.')
        rio_geom = self._orientar_rio(rio_geom, pin_xy, feedback)
        comp_rio = rio_geom.length()
        feedback.pushInfo('Rio: %.0f m | %d secao(oes) a processar' % (comp_rio, sec.featureCount()))

        # 4) para cada secao: ponto de cruzamento e distancia ao longo do rio
        registros = []  # (fid, Di, sec_geom)
        sem_cruzar = []
        for f in sec.getFeatures():
            g = f.geometry()
            inter = g.intersection(rio_geom)
            if inter.isEmpty():
                sem_cruzar.append(f.id())
                continue
            pc = inter.centroid().asPoint()
            di = rio_geom.lineLocatePoint(QgsGeometry.fromPointXY(pc))
            registros.append([f.id(), di, g])
        if sem_cruzar:
            feedback.pushWarning('%d secao(oes) NAO cruzam o rio e foram ignoradas (fids: %s).'
                                 % (len(sem_cruzar), sem_cruzar))
        if not registros:
            raise QgsProcessingException('Nenhuma secao cruza o rio. Verifique a digitalizacao.')

        # 5) ordena montante -> jusante (Di crescente) e numera S0..Sn
        registros.sort(key=lambda r: r[1])

        # passo de amostragem
        mde_layer = QgsRasterLayer(mde_path, 'mde')
        if not mde_layer.isValid():
            raise QgsProcessingException('MDE invalido: %s' % mde_path)
        if not passo or passo <= 0:
            passo = abs(mde_layer.rasterUnitsPerPixelX()) or 30.0
        feedback.pushInfo('Passo de amostragem do perfil: %.1f m' % passo)
        mde_prov = mde_layer.dataProvider()

        # 6) monta SecoesBrutas + tabela de secoes + perfis
        linhas_brutas = []   # rows do SecoesBrutas
        linhas_secoes = []   # resumo por secao
        rowid = 0
        di_ant = 0.0
        fid_to_ordem = {}
        for ordem, (fid, di, g) in enumerate(registros):
            fid_to_ordem[fid] = ordem
            dist_trecho = di - di_ant
            di_ant = di
            perfil = self._suavizar_perfil(self._amostrar_perfil(g, mde_prov, passo))
            if len(perfil) < 3:
                feedback.pushWarning('Secao %d com poucos pontos de perfil (%d).'
                                     % (ordem, len(perfil)))
            cotas = [z for _, z in perfil]
            cota_min = min(cotas) if cotas else None
            for (dist_along, z) in perfil:
                rowid += 1
                linhas_brutas.append([rowid, ordem, dist_along, z, 0, 0, ordem, 'Surface', 0, 'mde'])
            linhas_secoes.append([ordem, round(di, 2), round(dist_trecho, 2),
                                   round(cota_min, 3) if cota_min is not None else '',
                                   len(perfil)])

        n_sec = len(registros)

        # 7) escreve os CSVs na pasta da barragem
        p_brutas = os.path.join(pasta_barragem, id_bar + '_SecoesBrutas.csv')
        with open(p_brutas, 'w', newline='', encoding='utf-8') as fp:
            w = csv.writer(fp)
            w.writerow(['Rowid', 'OBJECTID', 'FIRST_DIST', 'FIRST_Z', 'SEC_DIST',
                        'SEC_Z', 'LINE_ID', 'SRC_TYPE', 'SRC_ID', 'SRC_NAME'])
            w.writerows(linhas_brutas)

        p_secoes = os.path.join(pasta_barragem, id_bar + '_secoes.csv')
        with open(p_secoes, 'w', newline='', encoding='utf-8') as fp:
            w = csv.writer(fp)
            w.writerow(['ID', 'Di_m', 'dist_trecho_m', 'cota_min_m', 'n_pts_perfil'])
            w.writerows(linhas_secoes)

        feedback.pushInfo('SecoesBrutas: %d linhas | secoes: %d' % (len(linhas_brutas), n_sec))
        feedback.pushInfo('CSV perfis: %s' % p_brutas)
        feedback.pushInfo('CSV secoes: %s' % p_secoes)

        # 8) grava campos ID / Di_m / dist_trecho_m em _SecTrans (e prepara cotamax/Velocidade)
        sec_edit = QgsVectorLayer('%s|layername=%s' % (gpkg, cfg['sectrans']), cfg['sectrans'], 'ogr')
        nomes = [fld.name() for fld in sec_edit.fields()]
        novos = []
        for nome, tipo in [('ID', QVariant.Int), ('Di_m', QVariant.Double),
                           ('dist_trecho_m', QVariant.Double),
                           ('cotamax', QVariant.Double), ('Velocidade', QVariant.Double)]:
            if nome not in nomes:
                novos.append(QgsField(nome, tipo))
        if novos:
            sec_edit.dataProvider().addAttributes(novos)
            sec_edit.updateFields()
        idx_id = sec_edit.fields().indexOf('ID')
        idx_di = sec_edit.fields().indexOf('Di_m')
        idx_dt = sec_edit.fields().indexOf('dist_trecho_m')
        di_por_fid = {fid: (di, (di - (registros[i-1][1] if i > 0 else 0.0)))
                      for i, (fid, di, g) in enumerate(registros)}
        with edit(sec_edit):
            for f in sec_edit.getFeatures():
                if f.id() in fid_to_ordem:
                    ordem = fid_to_ordem[f.id()]
                    di, dt = di_por_fid[f.id()]
                    sec_edit.changeAttributeValue(f.id(), idx_id, int(ordem))
                    sec_edit.changeAttributeValue(f.id(), idx_di, float(round(di, 2)))
                    sec_edit.changeAttributeValue(f.id(), idx_dt, float(round(dt, 2)))
        feedback.pushInfo('Campos ID/Di_m/dist_trecho_m gravados em %s.' % cfg['sectrans'])

        # 9) atualiza o config
        cfg['n_secoes_digitalizadas'] = n_sec
        cfg['passo_perfil_m'] = round(passo, 2)
        cfg['secoesbrutas_csv'] = p_brutas
        cfg['secoes_csv'] = p_secoes
        with open(config_path, 'w', encoding='utf-8') as fp:
            json.dump(cfg, fp, indent=2, ensure_ascii=False)

        if carregar:
            self._carregar_trechos = (gpkg, cfg['sectrans'])

        feedback.pushInfo('\n***** FIM - Script 2 concluido para "%s" *****' % id_bar)
        feedback.pushInfo('Proximo passo: Script 3 (Hidraulica - ANA 2024) le esses CSVs '
                          'e calcula cotamax/Velocidade por secao.')
        return {self.OUT_SECOESBRUTAS: p_brutas, self.OUT_SECOES: p_secoes}

    def postProcessAlgorithm(self, context, feedback):
        try:
            alvo = getattr(self, '_carregar_trechos', None)
            if alvo:
                gpkg, sec_name = alvo
                from qgis.utils import iface
                if iface is not None:
                    # recarrega a SecTrans (para refletir os novos campos)
                    lyr = QgsProject.instance().mapLayersByName(sec_name)
                    for l in lyr:
                        l.reload()
                        l.triggerRepaint()
        except Exception as e:
            feedback.pushInfo('Aviso pos-processamento: %s' % e)
        return {}
