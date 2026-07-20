# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# MS 2.0 ANA  ->  Porte para QGIS
# Script 1 de 4: Cria Ambiente
#
# Equivalente a Cria_Ambiente.py da toolbox MS2.tbx (Marcio Bomfim / ANA, 2024).
#
# O que faz:
#   - cria a pasta de trabalho da barragem
#   - copia a planilha de calculo hidraulico (MetodoSimplificadoANA_v2.1.xlsm)
#     para dentro da pasta, renomeada como <ID>_MS2_Calculo.xlsm
#   - cria/abre o GeoPackage MS2.gpkg na pasta de trabalho
#   - cria as camadas de LINHA vazias <ID>_Rio e <ID>_SecTrans no CRS
#     SIRGAS 2000 / UTM do fuso e hemisferio escolhidos
#   - (opcional) carrega as duas camadas no projeto para digitalizacao
#
# Como usar no QGIS:
#   Caixa de Processamento -> menu Scripts -> Adicionar Script ao Repositorio...
#   (ou copie este arquivo para a pasta de scripts de processamento do perfil)
# ---------------------------------------------------------------------------

import os
import json
import glob
import shutil

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFile,
    QgsProcessingParameterString,
    QgsProcessingParameterNumber,
    QgsProcessingParameterEnum,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterCrs,
    QgsProcessingParameterRasterLayer,
    QgsProcessingOutputString,
    QgsProcessingException,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFields,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsRectangle,
    QgsWkbTypes,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsRasterBandStats,
    QgsColorRampShader,
    QgsRasterShader,
    QgsGradientColorRamp,
    QgsGradientStop,
    QgsSingleBandPseudoColorRenderer,
    QgsRasterMinMaxOrigin,
    QgsMarkerSymbol,
    QgsProject,
)

# Rampa de elevacao do MDE (equivalente ao "Stretch" de elevacao do ArcGIS):
# verde claro -> verde -> amarelo -> laranja -> vermelho -> branco
RAMPA_MDE = [
    (0.00, '#aadf7f'), (0.20, '#2e9e3f'), (0.40, '#ffff73'),
    (0.60, '#f5a623'), (0.80, '#d7191c'), (1.00, '#ffffff'),
]

# ---------------------------------------------------------------------------
# Configuracao de caminhos (ms2_config.json) - remove os caminhos fixos.
# O arquivo fica na pasta de scripts do perfil do QGIS (ao lado deste .py).
# Conteudo minimo:  { "raiz": "D:/GIS/Barragens" }
# Chaves opcionais para sobrescrever caminhos individuais:
#   mdt_dir, anadem, coeficientes, cadastro_csv, estilo_qml
# ---------------------------------------------------------------------------
def _ms2_config():
    import os, json
    try:
        from qgis.core import QgsApplication
        base = os.path.join(QgsApplication.qgisSettingsDirPath(), 'processing', 'scripts')
    except Exception:
        base = os.path.dirname(os.path.abspath(__file__))
    caminho = os.path.join(base, 'ms2_config.json')
    if not os.path.exists(caminho):
        raise RuntimeError(
            'ms2_config.json nao encontrado em %s - crie-o com {"raiz": "<sua pasta>"}.' % base)
    with open(caminho, encoding='utf-8') as f:
        return json.load(f)


def _cfg(chave):
    import os
    c = _ms2_config()
    raiz = c.get('raiz', '') or ''
    padrao = {
        'mdt_dir':      os.path.join(raiz, 'MDTs'),
        'anadem':       os.path.join(raiz, 'MDTs', 'Anadem-BR-removepits.tif'),
        'coeficientes': os.path.join(raiz, 'QGIS_MS2', 'coeficientes_ana2024.json'),
        'cadastro_csv': os.path.join(raiz, 'barragens_ana_processado.csv'),
        'estilo_qml':   os.path.join(raiz, 'QGIS_MS2', 'MDT_estilo_ANA.qml'),
    }
    return c.get(chave) or padrao.get(chave)


# ANADEM padrao (usado quando o MDE/MDT nao e' informado) - via ms2_config.json.
MDT_DIR_PADRAO = _cfg('mdt_dir')
# ANADEM do Brasil inteiro (fonte preferencial - recorta-se por barragem).
ANADEM_BR = _cfg('anadem')
# Fallback: mosaico VRT a partir de tiles, se o nacional nao existir.
ANADEM_VRT_PADRAO = os.path.join(MDT_DIR_PADRAO, "anadem_mosaic.vrt")
ANADEM_TILES_GLOB = "anadem_v1_*.tif"   # padrao dos tiles para montar o VRT
# Raio padrao (km) do recorte do MDE ao redor da barragem.
BUFFER_MDE_KM_PADRAO = 30

# Base do SNISB (busca automatica de volume/altura pelo codigo da barragem).
BASE_SNISB_CSV = _cfg('cadastro_csv')

# Estilo (QML) padrao da ANA para o MDE - rampa topografica oficial.
ESTILO_MDE_QML = _cfg('estilo_qml')


class CriaAmbiente(QgsProcessingAlgorithm):
    """1 - Cria Ambiente (MS 2.0 ANA / QGIS)."""

    PASTA = 'PASTA'
    ID_BAR = 'ID_BAR'
    CRS_COORD = 'CRS_COORD'
    LON = 'LON'
    LAT = 'LAT'
    FUSO = 'FUSO'
    HEMISFERIO = 'HEMISFERIO'
    MDE = 'MDE'
    BUFFER = 'BUFFER'
    VOLUME = 'VOLUME'
    ALTURA = 'ALTURA'
    PLANILHA = 'PLANILHA'
    CARREGAR = 'CARREGAR'

    OUT_GPKG = 'OUT_GPKG'
    OUT_PASTA = 'OUT_PASTA'
    OUT_MDE = 'OUT_MDE'
    OUT_CONFIG = 'OUT_CONFIG'

    # -- infra do Processing -------------------------------------------------
    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def flags(self):
        # Roda na THREAD PRINCIPAL: operacoes de canvas/projeto (zoom, CRS,
        # carregar camadas) so funcionam de forma confiavel na thread principal.
        # Sem isto, a ferramenta roda em background e o enquadramento falha.
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    def createInstance(self):
        return CriaAmbiente()

    def name(self):
        # id interno, sem espacos
        return 'ms2_1_cria_ambiente'

    def displayName(self):
        return self.tr('1 - Cria Ambiente')

    def group(self):
        return self.tr('MS 2.0 ANA')

    def groupId(self):
        return 'ms2ana'

    def shortHelpString(self):
        return self.tr(
            'Cria a estrutura de pastas e camadas para iniciar a modelagem de '
            'uma barragem pelo Metodo Simplificado 2.0 da ANA.\n\n'
            'Gera a pasta da barragem, copia a planilha de calculo hidraulico '
            'e cria o GeoPackage MS2.gpkg com as camadas de linha vazias '
            '<ID>_Rio e <ID>_SecTrans, prontas para digitalizacao.\n\n'
            'Equivalente a ferramenta "1 - Cria Ambiente" da toolbox MS2.tbx '
            '(ArcGIS).'
        )

    # -- parametros ----------------------------------------------------------
    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            self.PASTA,
            self.tr('Pasta de Trabalho'),
            behavior=QgsProcessingParameterFile.Folder))

        self.addParameter(QgsProcessingParameterString(
            self.ID_BAR,
            self.tr('ID da Barragem (sem espacos/acentos)')))

        # Coordenada da barragem em campos separados + seletor de CRS.
        # Se informada, o fuso e o hemisferio sao calculados automaticamente.
        self.addParameter(QgsProcessingParameterCrs(
            self.CRS_COORD,
            self.tr('Sistema de coordenadas da barragem'),
            defaultValue='EPSG:4326'))

        self.addParameter(QgsProcessingParameterNumber(
            self.LON,
            self.tr('Longitude / Easting (X) - vazio = busca no SNISB'),
            type=QgsProcessingParameterNumber.Double,
            optional=True))

        self.addParameter(QgsProcessingParameterNumber(
            self.LAT,
            self.tr('Latitude / Northing (Y) - vazio = busca no SNISB'),
            type=QgsProcessingParameterNumber.Double,
            optional=True))

        # Usados somente se a coordenada acima NAO for informada.
        self.addParameter(QgsProcessingParameterNumber(
            self.FUSO,
            self.tr('Fuso UTM manual (so se nao usar a coordenada)'),
            type=QgsProcessingParameterNumber.Integer,
            defaultValue=22, minValue=11, maxValue=25))

        self.addParameter(QgsProcessingParameterEnum(
            self.HEMISFERIO,
            self.tr('Hemisferio manual (so se nao usar a coordenada)'),
            options=['Sul (S)', 'Norte (N)'],
            defaultValue=0))

        self.addParameter(QgsProcessingParameterRasterLayer(
            self.MDE,
            self.tr('MDE/MDT de preferencia (deixe em branco = recorte do ANADEM)'),
            optional=True))

        self.addParameter(QgsProcessingParameterNumber(
            self.BUFFER,
            self.tr('Raio do recorte do MDE ao redor da barragem (km)'),
            type=QgsProcessingParameterNumber.Double,
            defaultValue=BUFFER_MDE_KM_PADRAO, minValue=2, maxValue=120))

        # Volume/altura: se em branco, busca no SNISB pelo codigo da barragem.
        self.addParameter(QgsProcessingParameterNumber(
            self.VOLUME,
            self.tr('Volume do reservatorio (hm3) - vazio = busca no SNISB'),
            type=QgsProcessingParameterNumber.Double, optional=True, minValue=0))

        self.addParameter(QgsProcessingParameterNumber(
            self.ALTURA,
            self.tr('Altura da barragem (m) - vazio = busca no SNISB'),
            type=QgsProcessingParameterNumber.Double, optional=True, minValue=0))

        self.addParameter(QgsProcessingParameterFile(
            self.PLANILHA,
            self.tr('Planilha modelo MetodoSimplificadoANA_v2.1.xlsm'),
            extension='xlsm',
            optional=True))

        self.addParameter(QgsProcessingParameterBoolean(
            self.CARREGAR,
            self.tr('Carregar camadas no projeto'),
            defaultValue=True))

        self.addOutput(QgsProcessingOutputString(self.OUT_GPKG, self.tr('GeoPackage')))
        self.addOutput(QgsProcessingOutputString(self.OUT_PASTA, self.tr('Pasta da barragem')))
        self.addOutput(QgsProcessingOutputString(self.OUT_MDE, self.tr('MDE/MDT usado')))
        self.addOutput(QgsProcessingOutputString(self.OUT_CONFIG, self.tr('Arquivo de configuracao')))

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _epsg_sirgas_utm(fuso, hem_sul):
        """Retorna o codigo EPSG do SIRGAS 2000 / UTM.

        Sul  (17-25): 31977-31985  ->  31960 + fuso
        Norte(11-22): 31965-31976  ->  31954 + fuso
        """
        if hem_sul:
            if not (17 <= fuso <= 25):
                raise QgsProcessingException(
                    'Fuso %d invalido para o hemisferio Sul (use 17 a 25).' % fuso)
            return 31960 + fuso
        else:
            if not (11 <= fuso <= 22):
                raise QgsProcessingException(
                    'Fuso %d invalido para o hemisferio Norte (use 11 a 22).' % fuso)
            return 31954 + fuso

    @staticmethod
    def _abrir_ou_criar_gpkg(gpkg, primeira):
        """Abre o GeoPackage para escrita; cria do zero se 'primeira'."""
        from osgeo import ogr
        drv = ogr.GetDriverByName('GPKG')
        if primeira:
            if os.path.exists(gpkg):
                drv.DeleteDataSource(gpkg)
            ds = drv.CreateDataSource(gpkg)
        else:
            ds = ogr.Open(gpkg, 1)  # update
        if ds is None:
            raise QgsProcessingException('Nao foi possivel abrir/criar o GeoPackage: %s' % gpkg)
        return ds

    @staticmethod
    def _num_br(s):
        """Converte texto numerico em padrao BR ('0,047') para float; None se invalido."""
        if s is None:
            return None
        s = str(s).strip().replace('.', '').replace(',', '.') if ',' in str(s) else str(s).strip()
        try:
            v = float(s)
            return v
        except ValueError:
            return None

    def _buscar_snisb(self, id_bar, feedback):
        """Busca dados no CSV do SNISB pelo codigo da barragem (digitos do ID).
        Retorna dict {vol, alt, lat, lon, nome} (valores None se nao achados)."""
        import csv, re
        vazio = {'vol': None, 'alt': None, 'lat': None, 'lon': None, 'nome': None}
        cod = ''.join(re.findall(r'\d+', id_bar))
        if not cod or not os.path.exists(BASE_SNISB_CSV):
            return vazio
        try:
            with open(BASE_SNISB_CSV, encoding='utf-8', errors='replace') as f:
                r = csv.reader(f, delimiter=';')
                h = next(r)
                def col(nome):
                    return h.index(nome) if nome in h else None
                ic_cod = 0
                ic_cap_u = col('Capacidade_Usada'); ic_cap = col('Capacidade_hm3')
                ic_alt_u = col('Altura_m_Usada'); ic_alt_t = col('Altura_Terreno_m')
                ic_alt_f = col('Altura_Fundacao_m'); ic_nome = col('Nome_da_Barragem')
                ic_lat = col('Latitude'); ic_lon = col('Longitude')
                for x in r:
                    if x and x[ic_cod].strip() == cod:
                        vol = self._num_br(x[ic_cap_u]) if ic_cap_u is not None else None
                        if not vol:
                            vol = self._num_br(x[ic_cap]) if ic_cap is not None else None
                        alturas = [self._num_br(x[i]) for i in (ic_alt_u, ic_alt_t, ic_alt_f)
                                   if i is not None]
                        alturas = [a for a in alturas if a and a > 0]
                        return {
                            'vol': vol,
                            'alt': max(alturas) if alturas else None,
                            'lat': self._num_br(x[ic_lat]) if ic_lat is not None else None,
                            'lon': self._num_br(x[ic_lon]) if ic_lon is not None else None,
                            'nome': x[ic_nome] if ic_nome is not None else None,
                        }
        except Exception as e:
            feedback.pushWarning('Falha ao consultar o SNISB: %s' % e)
        return vazio

    @staticmethod
    def _calcular_dmax(volume_hm3):
        """Dmax (km) pela formula da planilha (LNEC/USACE) - depende so do volume."""
        V = float(volume_hm3)
        raw = 8.870e-8 * V**3 - 2.602e-4 * V**2 + 2.648e-1 * V + 6.737
        return min(100.0, max(5.0, raw))

    @staticmethod
    def _vazao_pico(volume_hm3, altura_m):
        """Vazao de pico de ruptura por Froehlich (1995), em m3/s. Conforme
        praxe confirmada pela ANA, este passo usa SEMPRE o Froehlich - a
        envoltoria MMC NAO e aplicada (calculada apenas como referencia)."""
        Vm3 = float(volume_hm3) * 1e6
        qp_froe = 0.607 * (Vm3) ** 0.295 * (float(altura_m)) ** 1.24 if altura_m else None
        qp_mmc = 0.0039042 * (Vm3) ** (1.0 / 1.2313)  # referencia (nao usada)
        qmax = qp_froe if qp_froe is not None else qp_mmc  # ANA: sempre Froehlich
        return qmax, qp_froe, qp_mmc

    def _criar_camada_linha(self, gpkg, layer_name, epsg, primeira, feedback):
        """Cria uma camada de LINHA vazia no GeoPackage, via ogr (grava o SRS
        corretamente, ao contrario do QgsVectorFileWriter para SIRGAS-UTM)."""
        from osgeo import ogr, osr
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(int(epsg))
        ds = self._abrir_ou_criar_gpkg(gpkg, primeira)
        lyr = ds.CreateLayer(layer_name, srs, ogr.wkbLineString,
                             options=['OVERWRITE=YES', 'GEOMETRY_NAME=geom'])
        if lyr is None:
            ds = None
            raise QgsProcessingException('Erro ao criar a camada %s.' % layer_name)
        ds = None
        feedback.pushInfo('Camada criada: %s (EPSG:%d)' % (layer_name, epsg))

    def _criar_pin_barragem(self, gpkg, layer_name, epsg, x, y, id_bar, feedback):
        """Cria a camada de PONTO (pin) com a posicao da barragem, via ogr."""
        from osgeo import ogr, osr
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(int(epsg))
        ds = self._abrir_ou_criar_gpkg(gpkg, False)
        lyr = ds.CreateLayer(layer_name, srs, ogr.wkbPoint,
                             options=['OVERWRITE=YES', 'GEOMETRY_NAME=geom'])
        lyr.CreateField(ogr.FieldDefn('ID', ogr.OFTString))
        feat = ogr.Feature(lyr.GetLayerDefn())
        feat.SetField('ID', id_bar)
        pt = ogr.Geometry(ogr.wkbPoint)
        pt.AddPoint(float(x), float(y))
        feat.SetGeometry(pt)
        lyr.CreateFeature(feat)
        feat = None
        ds = None
        feedback.pushInfo('Pin da barragem criado: %s (%.2f, %.2f)'
                          % (layer_name, x, y))

    @staticmethod
    def _fonte_anadem(feedback):
        """Retorna o caminho da fonte ANADEM (nacional ou VRT de tiles)."""
        if os.path.exists(ANADEM_BR):
            return ANADEM_BR
        # fallback: mosaico VRT dos tiles
        if not os.path.exists(ANADEM_VRT_PADRAO):
            tiles = sorted(glob.glob(os.path.join(MDT_DIR_PADRAO, ANADEM_TILES_GLOB)))
            if tiles:
                try:
                    from osgeo import gdal
                    gdal.BuildVRT(ANADEM_VRT_PADRAO, tiles)
                    feedback.pushInfo('Mosaico ANADEM (VRT) gerado de %d tile(s).' % len(tiles))
                except Exception as e:
                    feedback.pushWarning('Falha ao montar o VRT do ANADEM: %s' % e)
                    return ''
        return ANADEM_VRT_PADRAO if os.path.exists(ANADEM_VRT_PADRAO) else ''

    def _preparar_mde(self, parameters, context, feedback, lon, lat, crs,
                      buffer_km, pasta_barragem, id_bar):
        """Resolve o MDE: usa o informado, ou RECORTA o ANADEM ao redor da
        barragem (reprojetando para o UTM da barragem) e salva <ID>_MDE.tif.

        Retorna (caminho_mde, origem).
        """
        # 1) MDE selecionado pelo usuario -> usa direto
        mde_layer = self.parameterAsRasterLayer(parameters, self.MDE, context)
        if mde_layer is not None:
            caminho = mde_layer.source().split('|')[0]
            feedback.pushInfo('MDE/MDT selecionado: %s' % caminho)
            return caminho, 'selecionado'

        # 2) fonte ANADEM
        fonte = self._fonte_anadem(feedback)
        if not fonte:
            feedback.pushWarning('Nenhuma fonte ANADEM encontrada em %s.' % MDT_DIR_PADRAO)
            return '', 'ausente'

        # sem coordenada -> nao da pra recortar; usa a fonte direta
        if lon is None:
            feedback.pushInfo('Sem coordenada - usando a fonte ANADEM direta: %s' % fonte)
            return fonte, 'fonte direta'

        # 3) recorta janela ao redor da barragem e reprojeta para o UTM
        out = os.path.join(pasta_barragem, id_bar + '_MDE.tif')
        db = float(buffer_km) / 111.0   # graus aprox. (1 grau ~ 111 km)
        try:
            from osgeo import gdal
            gdal.UseExceptions()
            gdal.Warp(
                out, fonte,
                outputBoundsSRS='EPSG:4326',
                outputBounds=[lon - db, lat - db, lon + db, lat + db],
                dstSRS=crs.authid(),
                xRes=30, yRes=30,
                resampleAlg='bilinear',
                srcNodata=-9999, dstNodata=-9999,
                creationOptions=['COMPRESS=DEFLATE', 'TILED=YES', 'BIGTIFF=IF_SAFER'])
            # checa se ha dado valido no recorte
            ds = gdal.Open(out)
            st = ds.GetRasterBand(1).GetStatistics(True, True)
            ds = None
            if st and st[1] > st[0]:
                feedback.pushInfo(
                    'MDE recortado do ANADEM (raio %.0f km) -> %s  [%.0f a %.0f m]'
                    % (buffer_km, out, st[0], st[1]))
                return out, 'ANADEM (recorte %.0f km)' % buffer_km
            else:
                feedback.pushWarning(
                    'ATENCAO: o recorte do MDE nao tem dado valido - a barragem '
                    'pode estar FORA da cobertura do ANADEM.')
                return out, 'ANADEM (recorte sem dado)'
        except Exception as e:
            feedback.pushWarning('Falha ao recortar o MDE (%s). Usando fonte direta.' % e)
            return fonte, 'fonte direta (recorte falhou)'

    def _checar_cobertura(self, mde_path, lon, lat, feedback):
        """Avisa se a coordenada da barragem esta fora do MDE."""
        if not mde_path or lon is None:
            return
        rl = QgsRasterLayer(mde_path, 'mde_chk')
        if not rl.isValid():
            feedback.pushWarning('Nao foi possivel abrir o MDE para checar cobertura.')
            return
        tr = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem('EPSG:4326'), rl.crs(),
            QgsProject.instance())
        p = tr.transform(QgsPointXY(lon, lat))
        if rl.extent().contains(p):
            feedback.pushInfo('Cobertura do MDE: OK (barragem dentro da area do MDE).')
        else:
            feedback.pushWarning(
                'ATENCAO: a barragem parece estar FORA da area do MDE escolhido. '
                'Verifique o MDE/MDT antes de rodar o Script 2.')

    @staticmethod
    def _rampa_gradiente():
        """Monta o QgsGradientColorRamp a partir de RAMPA_MDE."""
        cor_ini = QColor(RAMPA_MDE[0][1])
        cor_fim = QColor(RAMPA_MDE[-1][1])
        stops = [QgsGradientStop(p, QColor(c)) for p, c in RAMPA_MDE[1:-1]]
        return QgsGradientColorRamp(cor_ini, cor_fim, False, stops)

    @staticmethod
    def _forcar_updated_canvas(mde):
        """Ajusta o minMaxOrigin do renderizador para extensao = Updated Canvas."""
        r = mde.renderer()
        if r is None or not hasattr(r, 'minMaxOrigin'):
            return
        mmo = QgsRasterMinMaxOrigin()
        mmo.setLimits(QgsRasterMinMaxOrigin.MinMax)
        mmo.setExtent(QgsRasterMinMaxOrigin.UpdatedCanvas)
        mmo.setStatAccuracy(QgsRasterMinMaxOrigin.Estimated)
        r.setMinMaxOrigin(mmo)

    def _aplicar_simbologia_mde(self, mde, pin_xy, crs, feedback):
        """Aplica a simbologia padrao da ANA (QML) ao MDE.

        Usa o estilo oficial (ESTILO_MDE_QML) e ajusta o min/max para
        extensao estatistica = Updated Canvas. Se o QML nao existir, cai
        numa rampa de elevacao equivalente embutida.
        """
        # 1) tenta o QML oficial da ANA
        if os.path.exists(ESTILO_MDE_QML):
            try:
                msg, ok = mde.loadNamedStyle(ESTILO_MDE_QML)
                if ok:
                    self._forcar_updated_canvas(mde)
                    mde.triggerRepaint()
                    feedback.pushInfo(
                        'Simbologia ANA (QML) aplicada ao MDE (min/max = Updated Canvas).')
                    return
                else:
                    feedback.pushWarning('Falha ao carregar o QML da ANA: %s' % msg)
            except Exception as e:
                feedback.pushWarning('Erro ao aplicar o QML da ANA: %s' % e)
        else:
            feedback.pushInfo('QML da ANA nao encontrado - usando rampa embutida.')

        # 2) fallback: rampa de elevacao embutida
        try:
            # min/max inicial numa janela ao redor da barragem (so para abrir bem)
            ext = None
            if pin_xy is not None:
                half = 6000.0  # m ao redor da barragem (no CRS UTM da barragem)
                rect = QgsRectangle(pin_xy[0] - half, pin_xy[1] - half,
                                    pin_xy[0] + half, pin_xy[1] + half)
                tr = QgsCoordinateTransform(crs, mde.crs(),
                                            QgsProject.instance().transformContext())
                ext = tr.transformBoundingBox(rect)

            st = mde.dataProvider().bandStatistics(
                1, QgsRasterBandStats.All, ext if ext is not None else mde.extent(), 0)
            vmin, vmax = st.minimumValue, st.maximumValue
            if vmax <= vmin:
                st = mde.dataProvider().bandStatistics(1, QgsRasterBandStats.All)
                vmin, vmax = st.minimumValue, st.maximumValue
            if vmax <= vmin:
                feedback.pushInfo('Sem variacao de cota para simbolizar o MDE.')
                return

            fn = QgsColorRampShader(vmin, vmax)
            fn.setColorRampType(QgsColorRampShader.Interpolated)
            fn.setClassificationMode(QgsColorRampShader.Continuous)
            fn.setSourceColorRamp(self._rampa_gradiente())
            fn.classifyColorRamp(5, -1)
            shader = QgsRasterShader()
            shader.setRasterShaderFunction(fn)

            renderer = QgsSingleBandPseudoColorRenderer(mde.dataProvider(), 1, shader)
            renderer.setClassificationMin(vmin)
            renderer.setClassificationMax(vmax)

            # extensao estatistica = Updated Canvas
            mmo = QgsRasterMinMaxOrigin()
            mmo.setLimits(QgsRasterMinMaxOrigin.MinMax)
            mmo.setExtent(QgsRasterMinMaxOrigin.UpdatedCanvas)
            mmo.setStatAccuracy(QgsRasterMinMaxOrigin.Estimated)
            renderer.setMinMaxOrigin(mmo)

            mde.setRenderer(renderer)
            mde.triggerRepaint()
            feedback.pushInfo('Simbologia de elevacao aplicada (min/max = Updated Canvas).')
        except Exception as e:
            feedback.pushInfo('Nao foi possivel aplicar a simbologia ao MDE: %s' % e)

    # -- execucao ------------------------------------------------------------
    def processAlgorithm(self, parameters, context, feedback):
        self._zoom = None   # (pin_xy_utm, crs_utm) - definido se houver coordenada
        pasta = self.parameterAsFile(parameters, self.PASTA, context)
        id_bar = self.parameterAsString(parameters, self.ID_BAR, context).strip()
        planilha = self.parameterAsFile(parameters, self.PLANILHA, context)
        carregar = self.parameterAsBool(parameters, self.CARREGAR, context)

        if not id_bar:
            raise QgsProcessingException('Informe o ID da Barragem.')
        if ' ' in id_bar:
            raise QgsProcessingException('O ID da Barragem nao pode conter espacos.')

        # Busca unica no SNISB (volume, altura, lat, lon, nome) pelo codigo do ID.
        snisb = self._buscar_snisb(id_bar, feedback)
        if snisb['nome']:
            feedback.pushInfo(
                'SNISB: %s | vol=%s hm3 | alt=%s m | lat=%s | lon=%s'
                % (snisb['nome'], snisb['vol'], snisb['alt'], snisb['lat'], snisb['lon']))

        # Coordenada: manual (parametros) tem prioridade; senao usa a do SNISB.
        x_raw = parameters.get(self.LON, None)
        y_raw = parameters.get(self.LAT, None)
        coord_manual = (x_raw not in (None, '') and y_raw not in (None, ''))

        lon = lat = None
        usar_ponto = False
        if coord_manual:
            x_in = self.parameterAsDouble(parameters, self.LON, context)
            y_in = self.parameterAsDouble(parameters, self.LAT, context)
            crs_in = self.parameterAsCrs(parameters, self.CRS_COORD, context)
            if not crs_in.isValid():
                crs_in = QgsCoordinateReferenceSystem('EPSG:4326')
            p_geo = QgsCoordinateTransform(
                crs_in, QgsCoordinateReferenceSystem('EPSG:4326'),
                QgsProject.instance()).transform(QgsPointXY(x_in, y_in))
            lon, lat = p_geo.x(), p_geo.y()
            usar_ponto = True
            feedback.pushInfo('Coordenada (manual, %s) -> lon/lat %.6f, %.6f'
                              % (crs_in.authid(), lon, lat))
        elif snisb['lon'] is not None and snisb['lat'] is not None:
            lon, lat = snisb['lon'], snisb['lat']
            usar_ponto = True
            feedback.pushInfo('Coordenada obtida do SNISB: lon/lat %.6f, %.6f' % (lon, lat))

        if usar_ponto:
            fuso = int((lon + 180.0) / 6.0) + 1
            hem_sul = lat < 0
            feedback.pushInfo('UTM deduzido: %d%s' % (fuso, 'S' if hem_sul else 'N'))
        else:
            fuso = self.parameterAsInt(parameters, self.FUSO, context)
            hem_idx = self.parameterAsEnum(parameters, self.HEMISFERIO, context)  # 0=Sul 1=Norte
            hem_sul = (hem_idx == 0)
            feedback.pushInfo('Sem coordenada - fuso/hemisferio manuais: UTM %d%s'
                              % (fuso, 'S' if hem_sul else 'N'))

        # CRS
        epsg = self._epsg_sirgas_utm(fuso, hem_sul)
        crs = QgsCoordinateReferenceSystem('EPSG:%d' % epsg)
        if not crs.isValid():
            raise QgsProcessingException('CRS EPSG:%d invalido.' % epsg)
        feedback.pushInfo('CRS: SIRGAS 2000 / UTM %d%s (EPSG:%d)' % (
            fuso, 'S' if hem_sul else 'N', epsg))

        # Posicao da barragem (em UTM) para o pin - so quando ha coordenada.
        pin_xy = None
        if usar_ponto:
            tr = QgsCoordinateTransform(
                QgsCoordinateReferenceSystem('EPSG:4326'), crs,
                QgsProject.instance())
            p_utm = tr.transform(QgsPointXY(lon, lat))
            pin_xy = (p_utm.x(), p_utm.y())

        # 1) volume/altura (parametro tem prioridade; senao usa o SNISB) e Dmax
        volume_hm3 = parameters.get(self.VOLUME, None)
        volume_hm3 = self.parameterAsDouble(parameters, self.VOLUME, context) if volume_hm3 not in (None, '') else None
        altura_m = parameters.get(self.ALTURA, None)
        altura_m = self.parameterAsDouble(parameters, self.ALTURA, context) if altura_m not in (None, '') else None

        nome_snisb = snisb['nome']
        if not volume_hm3:
            volume_hm3 = snisb['vol']
        if not altura_m:
            altura_m = snisb['alt']

        dmax_km = espac_m = qmax = None
        if volume_hm3 and volume_hm3 > 0:
            dmax_km = self._calcular_dmax(volume_hm3)
            espac_m = dmax_km * 1000.0 / 20.0
            qmax, _qf, _qm = self._vazao_pico(volume_hm3, altura_m)
            feedback.pushInfo(
                'Dmax (extensao da mancha) = %.2f km | espacamento secoes = %.0f m (21 secoes)'
                % (dmax_km, espac_m))
            if qmax:
                feedback.pushInfo('Vazao de pico Qmax (Froehlich) = %.1f m3/s'
                                  ' [ref. MMC nao usada = %.1f m3/s]'
                                  % (qmax, _qm if _qm else 0.0))
        else:
            feedback.pushWarning(
                'Volume nao encontrado (informe o "Volume" ou cadastre no SNISB) - '
                'Dmax nao calculado.')

        # 2) pasta da barragem
        pasta_barragem = os.path.join(pasta, id_bar)
        if not os.path.exists(pasta_barragem):
            os.makedirs(pasta_barragem)
            feedback.pushInfo('Pasta criada: %s' % pasta_barragem)
        else:
            feedback.pushInfo('Pasta ja existe: %s' % pasta_barragem)

        # 2) copia da planilha de calculo
        if planilha:
            destino = os.path.join(pasta_barragem, id_bar + '_MS2_Calculo.xlsm')
            if not os.path.exists(destino):
                shutil.copy(planilha, destino)
                feedback.pushInfo('Planilha copiada para: %s' % destino)
            else:
                feedback.pushInfo('Planilha ja existe (mantida): %s' % destino)
        else:
            feedback.pushWarning(
                'Planilha modelo nao informada - copie manualmente o '
                'MetodoSimplificadoANA_v2.1.xlsm para a pasta da barragem.')

        # 2b) MDE/MDT: usa o informado, ou recorta o ANADEM ao redor da barragem.
        # Se o Dmax for conhecido, garante que o recorte cubra toda a extensao.
        buffer_km = self.parameterAsDouble(parameters, self.BUFFER, context)
        if dmax_km:
            buffer_km = max(buffer_km, dmax_km + 2.0)
            feedback.pushInfo('Raio do recorte do MDE = %.1f km (cobre o Dmax).' % buffer_km)
        mde_path, mde_origem = self._preparar_mde(
            parameters, context, feedback,
            lon if usar_ponto else None, lat if usar_ponto else None,
            crs, buffer_km, pasta_barragem, id_bar)
        if mde_origem == 'selecionado' and usar_ponto:
            self._checar_cobertura(mde_path, lon, lat, feedback)

        # 3) GeoPackage + camadas vazias
        gpkg = os.path.join(pasta, 'MS2.gpkg')
        rio_name = id_bar + '_Rio'
        sec_name = id_bar + '_SecTrans'

        pin_name = id_bar + '_Barragem'

        gpkg_existe = os.path.exists(gpkg)
        # _Rio: cria o arquivo se ainda nao existir
        self._criar_camada_linha(gpkg, rio_name, epsg, not gpkg_existe, feedback)
        # _SecTrans: sempre adiciona como nova camada no mesmo gpkg
        self._criar_camada_linha(gpkg, sec_name, epsg, False, feedback)
        # _Barragem (pin): so quando ha coordenada
        tem_pin = False
        if pin_xy is not None:
            self._criar_pin_barragem(gpkg, pin_name, epsg, pin_xy[0], pin_xy[1],
                                     id_bar, feedback)
            tem_pin = True
        else:
            feedback.pushWarning(
                'Sem coordenada informada - pin da barragem nao foi criado.')

        # 4) carrega no projeto
        if carregar:
            nomes = [rio_name, sec_name]
            if tem_pin:
                nomes.append(pin_name)
            for nome in nomes:
                uri = '%s|layername=%s' % (gpkg, nome)
                lyr = QgsVectorLayer(uri, nome, 'ogr')
                if lyr.isValid():
                    # estiliza o pin com um marcador vermelho visivel
                    if nome == pin_name:
                        sym = QgsMarkerSymbol.createSimple({
                            'name': 'triangle',
                            'color': '255,0,0,255',
                            'outline_color': '0,0,0,255',
                            'outline_width': '0.4',
                            'size': '5',
                        })
                        lyr.renderer().setSymbol(sym)
                        lyr.triggerRepaint()
                    QgsProject.instance().addMapLayer(lyr)
                    feedback.pushInfo('Camada carregada no projeto: %s' % nome)
                else:
                    feedback.pushWarning('Nao foi possivel carregar a camada %s' % nome)

            # carrega o MDE por ultimo (fica abaixo dos vetores)
            if mde_path:
                rl = QgsRasterLayer(mde_path, id_bar + '_MDE')
                if rl.isValid():
                    self._aplicar_simbologia_mde(rl, pin_xy, crs, feedback)
                    rl.setOpacity(0.7)
                    QgsProject.instance().addMapLayer(rl)
                    feedback.pushInfo('MDE carregado no projeto: %s' % os.path.basename(mde_path))
                else:
                    feedback.pushWarning('MDE nao pode ser carregado: %s' % mde_path)

            # Guarda o alvo do zoom (em UTM, no CRS da barragem) para o
            # postProcessAlgorithm. Posicionar em UTM com o projeto no mesmo CRS
            # dispensa qualquer transformacao (que nesta instalacao falha as
            # vezes), garantindo que a barragem caia SEMPRE no lugar certo.
            if pin_xy is not None:
                self._zoom = (pin_xy, crs)

        # 5) salva a configuracao da barragem (lida pelo Script 2)
        config = {
            'id': id_bar,
            'epsg': epsg,
            'crs': 'EPSG:%d' % epsg,
            'fuso': fuso,
            'hemisferio': 'S' if hem_sul else 'N',
            'lon': lon if usar_ponto else None,
            'lat': lat if usar_ponto else None,
            'x_utm': pin_xy[0] if pin_xy else None,
            'y_utm': pin_xy[1] if pin_xy else None,
            'mde': mde_path,
            'mde_origem': mde_origem,
            'nome_snisb': nome_snisb,
            'volume_hm3': volume_hm3,
            'altura_m': altura_m,
            'dmax_km': round(dmax_km, 3) if dmax_km else None,
            'espacamento_secoes_m': round(espac_m, 1) if espac_m else None,
            'n_secoes': 21 if dmax_km else None,
            'qmax_m3s': round(qmax, 1) if qmax else None,
            'gpkg': gpkg,
            'rio': rio_name,
            'sectrans': sec_name,
            'pin': pin_name if tem_pin else None,
        }
        config_path = os.path.join(pasta_barragem, id_bar + '_MS2.json')
        with open(config_path, 'w', encoding='utf-8') as fp:
            json.dump(config, fp, indent=2, ensure_ascii=False)
        feedback.pushInfo('Configuracao salva: %s' % config_path)

        feedback.pushInfo('\n***** FIM - Ambiente criado para "%s" *****\n' % id_bar)
        feedback.pushInfo(
            'Proximo passo: digitalize o eixo do rio em "%s" e as secoes '
            'transversais em "%s" e rode o Script 2 (Rio_Secoes).'
            % (rio_name, sec_name))

        return {
            self.OUT_GPKG: gpkg,
            self.OUT_PASTA: pasta_barragem,
            self.OUT_MDE: mde_path,
            self.OUT_CONFIG: config_path,
        }

    def postProcessAlgorithm(self, context, feedback):
        """Roda na THREAD PRINCIPAL, depois de tudo carregado. Aqui sim e'
        seguro mexer no canvas/projeto.

        Coloca o projeto no MESMO CRS UTM da barragem e centraliza nas
        coordenadas UTM do pin - sem nenhuma transformacao de coordenadas
        (que nesta instalacao do QGIS falha de forma intermitente). Assim a
        barragem cai sempre no lugar certo; o satelite e' a unica camada que
        depende de reprojecao interna do QGIS."""
        try:
            alvo = getattr(self, '_zoom', None)
            if alvo is None:
                return {}
            pin_xy, crs_utm = alvo
            from qgis.utils import iface
            if iface is None:
                return {}
            proj = QgsProject.instance()
            proj.setCrs(crs_utm)                       # projeto no UTM da barragem
            canvas = iface.mapCanvas()
            canvas.setCenter(QgsPointXY(pin_xy[0], pin_xy[1]))   # UTM direto
            canvas.zoomScale(30000)
            canvas.refresh()
            feedback.pushInfo('Projeto em %s e mapa centrado na barragem (UTM %.1f, %.1f).'
                              % (crs_utm.authid(), pin_xy[0], pin_xy[1]))
        except Exception as e:
            feedback.pushInfo('Nao foi possivel centrar o mapa: %s' % e)
        return {}
