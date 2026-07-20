# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# MS 2.0 ANA  ->  Porte para QGIS
# Script combinado 3-5: Hidraulica + Mancha + Perigo (tudo de uma vez)
#
# Conveniencia: roda em sequencia os Scripts 3 (hidraulica), 4 (mancha) e
# 5 (perigo), chamando cada um por dentro (processing.run), com um unico
# conjunto de parametros. NAO substitui os Scripts 3/4/5 individuais, que
# continuam disponiveis para calibracao passo a passo.
#
# Pre-requisito: ambiente ja criado (Script 1) e secoes/perfis (Script 2).
# ---------------------------------------------------------------------------

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFile,
    QgsProcessingParameterString,
    QgsProcessingParameterNumber,
    QgsProcessingParameterEnum,
    QgsProcessingOutputString,
    QgsProcessingException,
)
import processing


class HidraulicaManchaPerigo(QgsProcessingAlgorithm):
    """3-5 - Hidraulica + Mancha + Perigo (MS 2.0 ANA / QGIS)."""

    PASTA = 'PASTA'
    ID_BAR = 'ID_BAR'
    MANNING = 'MANNING'
    INCERTEZA = 'INCERTEZA'
    FENDA = 'FENDA'
    METODO_QX = 'METODO_QX'
    SLOPE_MIN = 'SLOPE_MIN'
    SUAVIZAR = 'SUAVIZAR'
    FECHAMENTO = 'FECHAMENTO'
    OUT_MANCHA = 'OUT_MANCHA'
    OUT_PERIGO = 'OUT_PERIGO'

    def tr(self, s):
        return QCoreApplication.translate('Processing', s)

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    def createInstance(self):
        return HidraulicaManchaPerigo()

    def name(self):
        return 'ms2_35_hidraulica_mancha_perigo'

    def displayName(self):
        return self.tr('3-5 - Hidraulica + Mancha + Perigo (tudo)')

    def group(self):
        return self.tr('MS 2.0 ANA')

    def groupId(self):
        return 'ms2ana'

    def shortHelpString(self):
        return self.tr(
            'Roda em sequencia a hidraulica (Script 3), a mancha (Script 4) e o '
            'perigo hidrodinamico (Script 5) com um unico conjunto de parametros. '
            'Exige o ambiente ja criado (Script 1) e as secoes/perfis (Script 2). '
            'Os Scripts 3, 4 e 5 individuais continuam disponiveis para calibracao '
            'passo a passo (permitem conferir a hidraulica antes de mapear).')

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            self.PASTA, self.tr('Pasta de Trabalho'),
            behavior=QgsProcessingParameterFile.Folder))
        self.addParameter(QgsProcessingParameterString(
            self.ID_BAR, self.tr('ID da Barragem')))
        # --- parametros da hidraulica (Script 3) ---
        self.addParameter(QgsProcessingParameterNumber(
            self.MANNING, self.tr('Coeficiente de Manning (n)'),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.035,
            minValue=0.005, maxValue=0.5))
        self.addParameter(QgsProcessingParameterNumber(
            self.INCERTEZA, self.tr('Margem de incerteza no WSE (m)'),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.0,
            minValue=0.0, maxValue=10.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.FENDA, self.tr('Profundidade da fenda (m)'),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.05,
            minValue=0.0, maxValue=5.0))
        self.addParameter(QgsProcessingParameterEnum(
            self.METODO_QX, self.tr('Metodo de decaimento da vazao (Qx)'),
            options=['ANA 2024/2023 (exp/potencia)', 'ANA 2014 (MS1)'],
            defaultValue=1))
        self.addParameter(QgsProcessingParameterNumber(
            self.SLOPE_MIN, self.tr('Piso de declividade (m/m)'),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.00001,
            minValue=0.0, maxValue=0.01))
        # --- parametros da mancha/perigo (Scripts 4 e 5, compartilhados) ---
        self.addParameter(QgsProcessingParameterNumber(
            self.SUAVIZAR, self.tr('Suavizacao do contorno (0 = nenhuma)'),
            type=QgsProcessingParameterNumber.Integer, defaultValue=2,
            minValue=0, maxValue=10))
        self.addParameter(QgsProcessingParameterNumber(
            self.FECHAMENTO, self.tr('Fechamento/merge (m) - une vaos finos (artefatos)'),
            type=QgsProcessingParameterNumber.Double, defaultValue=25.0,
            minValue=0.0, maxValue=200.0))
        self.addOutput(QgsProcessingOutputString(self.OUT_MANCHA, self.tr('Camada da mancha')))
        self.addOutput(QgsProcessingOutputString(self.OUT_PERIGO, self.tr('Camada de perigo')))

    # -----------------------------------------------------------------------
    def processAlgorithm(self, parameters, context, feedback):
        pasta = self.parameterAsFile(parameters, self.PASTA, context)
        id_bar = self.parameterAsString(parameters, self.ID_BAR, context).strip()
        manning = self.parameterAsDouble(parameters, self.MANNING, context)
        incerteza = self.parameterAsDouble(parameters, self.INCERTEZA, context)
        fenda = self.parameterAsDouble(parameters, self.FENDA, context)
        metodo_qx = self.parameterAsEnum(parameters, self.METODO_QX, context)
        slope_min = self.parameterAsDouble(parameters, self.SLOPE_MIN, context)
        suavizar = self.parameterAsInt(parameters, self.SUAVIZAR, context)
        fechamento = self.parameterAsDouble(parameters, self.FECHAMENTO, context)

        def _run(alg, params, etapa):
            if feedback.isCanceled():
                raise QgsProcessingException('Cancelado.')
            feedback.pushInfo('=== %s ===' % etapa)
            return processing.run('script:' + alg, params, context=context,
                                  feedback=feedback, is_child_algorithm=True)

        feedback.setProgressText('1/3 - Hidraulica (Script 3)...')
        _run('ms2_3_hidraulica', {
            'PASTA': pasta, 'ID_BAR': id_bar, 'MANNING': manning,
            'INCERTEZA': incerteza, 'FENDA': fenda, 'METODO_QX': metodo_qx,
            'SLOPE_MIN_P': slope_min}, 'Script 3 - Hidraulica')
        feedback.setProgress(33)

        feedback.setProgressText('2/3 - Mancha (Script 4)...')
        r4 = _run('ms2_4_manchas', {
            'PASTA': pasta, 'ID_BAR': id_bar,
            'SUAVIZAR': suavizar, 'FECHAMENTO': fechamento}, 'Script 4 - Mancha')
        feedback.setProgress(66)

        feedback.setProgressText('3/3 - Perigo (Script 5)...')
        r5 = _run('ms2_5_perigo', {
            'PASTA': pasta, 'ID_BAR': id_bar,
            'FECHAMENTO': fechamento, 'SUAVIZAR': suavizar}, 'Script 5 - Perigo')
        feedback.setProgress(100)
        feedback.pushInfo('Concluido: hidraulica + mancha + perigo.')

        return {
            self.OUT_MANCHA: r4.get('OUT_MANCHA', ''),
            self.OUT_PERIGO: r5.get('OUT_PERIGO', ''),
        }
