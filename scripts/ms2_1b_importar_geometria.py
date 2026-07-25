# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# MS 2.0 ANA  ->  Porte para QGIS
# Script 1b: Importar rio e secoes (substitui o copiar-e-colar manual)
#
# Copia a geometria do rio e das secoes transversais - de arquivos (.shp,
# .gpkg, etc.) ou de camadas ja carregadas no projeto - para dentro das
# camadas <ID>_Rio e <ID>_SecTrans criadas pelo Script 1. Se as camadas de
# entrada estiverem em outro sistema de coordenadas, sao reprojetadas.
#
# Pre-requisito: rodar o Script 1 (Cria Ambiente) antes.
# ---------------------------------------------------------------------------

import os
import json

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFile,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsProcessingOutputString,
    QgsProcessingException,
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsCoordinateTransform,
    QgsProject,
    QgsWkbTypes,
)


class ImportarGeometria(QgsProcessingAlgorithm):
    """1b - Importar rio e secoes (MS 2.0 ANA / QGIS)."""

    PASTA = 'PASTA'
    ID_BAR = 'ID_BAR'
    RIO = 'RIO'
    SECOES = 'SECOES'
    OUT = 'OUT'

    def tr(self, s):
        return QCoreApplication.translate('Processing', s)

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    def createInstance(self):
        return ImportarGeometria()

    def name(self):
        return 'ms2_1b_importar_geometria'

    def displayName(self):
        return self.tr('1b - Importar rio e secoes')

    def group(self):
        return self.tr('MS 2.0 ANA')

    def groupId(self):
        return 'ms2ana'

    def shortHelpString(self):
        return self.tr(
            'Copia o rio e as secoes transversais (de arquivos ou de camadas ja '
            'carregadas) para dentro das camadas <ID>_Rio e <ID>_SecTrans criadas '
            'pelo Script 1 - substitui o copiar-e-colar manual. Reprojeta se '
            'necessario. Rode o Script 1 (Cria Ambiente) antes. Depois, siga para '
            'o Script 2 (Rio e Secoes).')

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            self.PASTA, self.tr('Pasta de Trabalho'),
            behavior=QgsProcessingParameterFile.Folder))
        self.addParameter(QgsProcessingParameterString(
            self.ID_BAR, self.tr('ID da Barragem')))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.RIO, self.tr('Rio (arquivo ou camada de linha)'),
            types=[QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.SECOES, self.tr('Secoes transversais (arquivo ou camada de linhas)'),
            types=[QgsProcessing.TypeVectorLine]))
        self.addOutput(QgsProcessingOutputString(self.OUT, self.tr('Resumo')))

    # -----------------------------------------------------------------------
    def processAlgorithm(self, parameters, context, feedback):
        pasta = self.parameterAsFile(parameters, self.PASTA, context)
        id_bar = self.parameterAsString(parameters, self.ID_BAR, context).strip()
        rio_src = self.parameterAsVectorLayer(parameters, self.RIO, context)
        sec_src = self.parameterAsVectorLayer(parameters, self.SECOES, context)

        if not id_bar:
            raise QgsProcessingException('Informe o ID da Barragem.')
        cfg_path = os.path.join(pasta, id_bar, id_bar + '_MS2.json')
        if not os.path.exists(cfg_path):
            raise QgsProcessingException(
                'Config nao encontrado: %s.\nRode o Script 1 (Cria Ambiente) antes.' % cfg_path)
        cfg = json.load(open(cfg_path, encoding='utf-8'))
        gpkg = cfg['gpkg']

        def importar(src, layername, rotulo):
            if src is None or not src.isValid():
                raise QgsProcessingException('Camada de %s invalida.' % rotulo)
            tgt = QgsVectorLayer('%s|layername=%s' % (gpkg, layername), layername, 'ogr')
            if not tgt.isValid():
                raise QgsProcessingException(
                    'Camada destino "%s" nao encontrada - rode o Script 1 antes.' % layername)
            ct = None
            if src.crs() != tgt.crs():
                ct = QgsCoordinateTransform(src.crs(), tgt.crs(), QgsProject.instance())
                feedback.pushInfo('Reprojetando %s: %s -> %s.'
                                  % (rotulo, src.crs().authid(), tgt.crs().authid()))
            prov = tgt.dataProvider()
            # limpa o destino (evita duplicar se rodar de novo)
            ids = [f.id() for f in tgt.getFeatures()]
            if ids:
                prov.deleteFeatures(ids)
            novos = []
            for f in src.getFeatures():
                g = QgsGeometry(f.geometry())
                if g.isEmpty():
                    continue
                if QgsWkbTypes.hasZ(g.wkbType()) or QgsWkbTypes.hasM(g.wkbType()):
                    ab = g.get()
                    ab.dropZValue()
                    ab.dropMValue()
                if ct is not None:
                    g.transform(ct)
                nf = QgsFeature(tgt.fields())
                nf.setGeometry(g)
                novos.append(nf)
            if novos:
                prov.addFeatures(novos)
            tgt.updateExtents()
            return len(novos)

        n_rio = importar(rio_src, cfg['rio'], 'rio')
        n_sec = importar(sec_src, cfg['sectrans'], 'secoes')

        msg = 'Importado: rio = %d feicao(oes), secoes = %d.' % (n_rio, n_sec)
        feedback.pushInfo(msg)
        if n_rio < 1:
            feedback.pushWarning('Atencao: o rio ficou vazio - verifique o arquivo de entrada.')
        if n_sec < 2:
            feedback.pushWarning('Atencao: menos de 2 secoes - verifique o arquivo de entrada.')
        feedback.pushInfo('Proximo passo: Script 2 - Rio e Secoes.')
        return {self.OUT: msg}
