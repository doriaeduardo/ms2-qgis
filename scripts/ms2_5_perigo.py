# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# MS 2.0 ANA  ->  Porte para QGIS
# Script 5 de 5: Perigo Hidrodinamico (h x v)
#
# Porta o PerigoHidrodinamico.py da toolbox MS2.tbx (ANA):
#   TIN da Velocidade (por secao) -> raster de velocidade
#   h x v = profundidade x velocidade  (perigo hidrodinamico)
#   classifica nas 5 FAIXAS OFICIAIS DA ANA e aplica a simbologia padrao
#
# Faixas ANA (m2/s):  <0,5 | 0,5-1 | 1-5 | 5-10 | >10
# Gera <ID>_velocidade.tif, <ID>_hv.tif (estilizado + .qml), <ID>_perigo.tif
# e a camada vetorial <ID>_Perigo (5 classes) no GeoPackage.
# ---------------------------------------------------------------------------

import os
import json

from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFile,
    QgsProcessingParameterString,
    QgsProcessingParameterNumber,
    QgsProcessingOutputString,
    QgsProcessingException,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsGeometry,
    QgsColorRampShader,
    QgsRasterShader,
    QgsSingleBandPseudoColorRenderer,
    QgsProject,
)
import processing

# Faixas oficiais da ANA: (limite_superior, codigo, cor, rotulo)
FAIXAS_ANA = [
    (0.5,   1, '#9ecae1', '< 0,5'),
    (1.0,   2, '#4daf4a', '0,5 - 1'),
    (5.0,   3, '#ffff00', '1 - 5'),
    (10.0,  4, '#ff7f00', '5 - 10'),
    (1e12,  5, '#e31a1c', '> 10'),
]


class Perigo(QgsProcessingAlgorithm):
    """5 - Perigo Hidrodinamico (MS 2.0 ANA / QGIS)."""

    PASTA = 'PASTA'
    ID_BAR = 'ID_BAR'
    FECHAMENTO = 'FECHAMENTO'
    SUAVIZAR = 'SUAVIZAR'
    OUT_PERIGO = 'OUT_PERIGO'

    def tr(self, s):
        return QCoreApplication.translate('Processing', s)

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    def createInstance(self):
        return Perigo()

    def name(self):
        return 'ms2_5_perigo'

    def displayName(self):
        return self.tr('5 - Perigo Hidrodinamico')

    def group(self):
        return self.tr('MS 2.0 ANA')

    def groupId(self):
        return 'ms2ana'

    def shortHelpString(self):
        return self.tr(
            'Calcula o perigo hidrodinamico (profundidade x velocidade) e o '
            'classifica nas 5 faixas oficiais da ANA (<0,5 | 0,5-1 | 1-5 | 5-10 '
            '| >10 m2/s), aplicando a simbologia padrao. Interpola a velocidade '
            'das secoes (TIN) e multiplica pela profundidade (Script 4).')

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            self.PASTA, self.tr('Pasta de Trabalho'),
            behavior=QgsProcessingParameterFile.Folder))
        self.addParameter(QgsProcessingParameterString(
            self.ID_BAR, self.tr('ID da Barragem')))
        self.addParameter(QgsProcessingParameterNumber(
            self.FECHAMENTO,
            self.tr('Fechamento/merge do vetor (m) - une vaos finos; vaos > 2x preservados'),
            type=QgsProcessingParameterNumber.Double, defaultValue=25.0, minValue=0.0, maxValue=200.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.SUAVIZAR, self.tr('Suavizacao do contorno do vetor (0 = nenhuma)'),
            type=QgsProcessingParameterNumber.Integer, defaultValue=2, minValue=0, maxValue=10))
        self.addOutput(QgsProcessingOutputString(self.OUT_PERIGO, self.tr('Camada de perigo')))

    # -- shader das faixas ANA (raster de h x v) ----------------------------
    @staticmethod
    def _shader_ana():
        fn = QgsColorRampShader(0, FAIXAS_ANA[-2][0], None, QgsColorRampShader.Discrete)
        itens = [QgsColorRampShader.ColorRampItem(lim, QColor(cor), rot)
                 for (lim, cod, cor, rot) in FAIXAS_ANA]
        fn.setColorRampItemList(itens)
        sh = QgsRasterShader()
        sh.setRasterShaderFunction(fn)
        return sh

    # -----------------------------------------------------------------------
    def processAlgorithm(self, parameters, context, feedback):
        self._add = []
        pasta = self.parameterAsFile(parameters, self.PASTA, context)
        id_bar = self.parameterAsString(parameters, self.ID_BAR, context).strip()
        fechamento = self.parameterAsDouble(parameters, self.FECHAMENTO, context)
        suavizar = self.parameterAsInt(parameters, self.SUAVIZAR, context)

        pb = os.path.join(pasta, id_bar)
        cfg_path = os.path.join(pb, id_bar + '_MS2.json')
        if not os.path.exists(cfg_path):
            raise QgsProcessingException('Config nao encontrado: %s' % cfg_path)
        cfg = json.load(open(cfg_path, encoding='utf-8'))
        gpkg = cfg['gpkg']
        crs_id = cfg['crs']
        prof_path = cfg.get('profundidade_tif')
        if not prof_path or not os.path.exists(prof_path):
            raise QgsProcessingException(
                'Raster de profundidade nao encontrado - rode o Script 4 (Manchas) antes.')

        sec = QgsVectorLayer('%s|layername=%s' % (gpkg, cfg['sectrans']), 'sec', 'ogr')
        fidx = sec.fields().indexOf('Velocidade')
        if fidx < 0:
            raise QgsProcessingException('_SecTrans sem o campo Velocidade - rode o Script 3.')
        if sum(1 for f in sec.getFeatures() if f['Velocidade'] is not None) < 2:
            raise QgsProcessingException('Menos de 2 secoes com Velocidade - rode o Script 3.')

        prof = QgsRasterLayer(prof_path, 'prof')
        ext = prof.extent()
        pix = abs(prof.rasterUnitsPerPixelX()) or 30.0
        ext_str = '%f,%f,%f,%f [%s]' % (ext.xMinimum(), ext.xMaximum(),
                                        ext.yMinimum(), ext.yMaximum(), crs_id)

        # 1) TIN da velocidade -> raster
        interp = '%s::~::0::~::%d::~::2' % (sec.source(), fidx)
        velo_tif = os.path.join(pb, id_bar + '_velocidade.tif')
        feedback.pushInfo('Interpolando a velocidade (TIN)...')
        processing.run('qgis:tininterpolation', {
            'INTERPOLATION_DATA': interp, 'METHOD': 0,
            'EXTENT': ext_str, 'PIXEL_SIZE': pix, 'OUTPUT': velo_tif},
            context=context, feedback=None)

        # mancha do Script 4: o perigo deve ser um SUBSET dela (nao pode haver
        # perigo fora da mancha). Usada para recortar rasters e vetor.
        mancha_name = cfg.get('mancha')
        mancha_lyr = (QgsVectorLayer('%s|layername=%s' % (gpkg, mancha_name), 'mancha', 'ogr')
                      if mancha_name else None)
        if not (mancha_lyr and mancha_lyr.isValid() and mancha_lyr.featureCount() > 0):
            raise QgsProcessingException('Mancha (%s) nao encontrada - rode o Script 4 antes.' % mancha_name)
        mancha_geom = QgsGeometry.unaryUnion([f.geometry() for f in mancha_lyr.getFeatures()])

        # 2) h x v e classificacao nas 5 faixas ANA (numpy), RECORTADO pela mancha
        hv_tif = os.path.join(pb, id_bar + '_hv.tif')
        perigo_tif = os.path.join(pb, id_bar + '_perigo.tif')
        stats, hvmax = self._calc_perigo(prof_path, velo_tif, hv_tif, perigo_tif,
                                         gpkg, mancha_name, feedback)

        # 3) vetoriza o perigo (poligonos por classe 1..5)
        feedback.pushInfo('Vetorizando o perigo...')
        poly = processing.run('gdal:polygonize', {
            'INPUT': perigo_tif, 'BAND': 1, 'FIELD': 'classe', 'EIGHT_CONNECTEDNESS': True,
            'OUTPUT': 'TEMPORARY_OUTPUT'}, context=context, feedback=None)['OUTPUT']
        pl = QgsVectorLayer(poly, 'p', 'ogr') if isinstance(poly, str) else poly
        perigo_name = id_bar + '_Perigo'
        self._gravar_perigo(gpkg, perigo_name, crs_id, pl, fechamento, suavizar,
                            mancha_geom, feedback)

        cfg['velocidade_tif'] = velo_tif
        cfg['hv_tif'] = hv_tif
        cfg['perigo_tif'] = perigo_tif
        cfg['perigo'] = perigo_name
        cfg['perigo_faixas'] = '<0,5 | 0,5-1 | 1-5 | 5-10 | >10 (ANA)'
        cfg['hv_max'] = round(hvmax, 2)
        cfg['perigo_areas_ha'] = stats
        json.dump(cfg, open(cfg_path, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)

        feedback.pushInfo('Areas por faixa (ha): ' + ' | '.join(
            '%s=%.1f' % (FAIXAS_ANA[i][3], stats.get(str(i + 1), 0)) for i in range(5)))
        feedback.pushInfo('h*v maximo = %.2f m2/s' % hvmax)
        feedback.pushInfo('\n***** FIM - Perigo hidrodinamico (faixas ANA) para "%s" *****' % id_bar)
        self._add = [(hv_tif, id_bar + '_hv', 'hv'),
                     ('%s|layername=%s' % (gpkg, perigo_name), perigo_name, 'perigo')]
        return {self.OUT_PERIGO: '%s|layername=%s' % (gpkg, perigo_name)}

    @staticmethod
    def _calc_perigo(prof_path, velo_path, hv_path, perigo_path, gpkg, mancha_name, feedback):
        """h*v e classificacao nas 5 faixas ANA; alinha a velocidade ao grid da
        profundidade e RECORTA pela mancha (perigo nunca fora da mancha)."""
        from osgeo import gdal
        import numpy as np
        gdal.UseExceptions()
        pds = gdal.Open(prof_path)
        gt = pds.GetGeoTransform(); nx, ny = pds.RasterXSize, pds.RasterYSize
        proj = pds.GetProjection()
        pbnd = pds.GetRasterBand(1); pnd = pbnd.GetNoDataValue()
        prof = pbnd.ReadAsArray().astype('float64')

        velo_al = gdal.Warp('', velo_path, format='MEM', width=nx, height=ny,
                            outputBounds=[gt[0], gt[3] + gt[5] * ny, gt[0] + gt[1] * nx, gt[3]],
                            resampleAlg='bilinear')
        vb = velo_al.GetRasterBand(1); vnd = vb.GetNoDataValue()
        velo = vb.ReadAsArray().astype('float64')

        # mascara da MANCHA (rasterizada no grid da profundidade)
        mds = gdal.GetDriverByName('MEM').Create('', nx, ny, 1, gdal.GDT_Byte)
        mds.SetGeoTransform(gt); mds.SetProjection(proj)
        gdal.Rasterize(mds, gpkg, options=gdal.RasterizeOptions(
            layers=[mancha_name], burnValues=[1]))
        dentro_mancha = mds.GetRasterBand(1).ReadAsArray().astype(bool)
        mds = None

        flood = (prof > 0.0) & dentro_mancha   # so dentro da mancha
        if pnd is not None:
            flood &= (prof != pnd)
        velo_ok = np.where((velo == vnd) if vnd is not None else False, 0.0, velo)
        hvv = prof * velo_ok

        hv = np.full(prof.shape, -9999.0, dtype='float32')
        hv[flood] = hvv[flood].astype('float32')

        # classes 1..5 conforme FAIXAS_ANA (255 = NoData)
        cls = np.full(prof.shape, 255, dtype='int16')
        ant = -1e30
        for (lim, cod, cor, rot) in FAIXAS_ANA:
            cls[flood & (hvv > ant) & (hvv <= lim)] = cod
            ant = lim

        drv = gdal.GetDriverByName('GTiff')
        for path, arr, gdt, nd in [(hv_path, hv, gdal.GDT_Float32, -9999.0),
                                   (perigo_path, cls, gdal.GDT_Int16, 255)]:
            ds = drv.Create(path, nx, ny, 1, gdt, options=['COMPRESS=DEFLATE', 'TILED=YES'])
            ds.SetGeoTransform(gt); ds.SetProjection(proj)
            b = ds.GetRasterBand(1); b.SetNoDataValue(nd); b.WriteArray(arr); ds = None
        velo_al = None; pds = None

        px_ha = abs(gt[1] * gt[5]) / 10000.0
        stats = {str(c): round(float((cls == c).sum() * px_ha), 2) for c in (1, 2, 3, 4, 5)}
        return stats, (float(hvv[flood].max()) if flood.any() else 0.0)

    @staticmethod
    def _acabar(qg, fechamento, suavizar):
        """Fechamento morfologico curto + suavizacao (mesmo acabamento da mancha)."""
        if qg is None or qg.isEmpty():
            return qg
        if fechamento > 0:
            f = qg.buffer(fechamento, 8).buffer(-fechamento, 8)
            if f and not f.isEmpty():
                qg = f
        if suavizar > 0:
            s = qg.smooth(suavizar, 0.25)
            if s and not s.isEmpty():
                qg = s
        return qg

    def _gravar_perigo(self, gpkg, layer_name, crs_id, poly_layer, fechamento, suavizar,
                       mancha_geom, feedback):
        """Dissolve por faixa, aplica acabamento (merge+suavizacao), RECORTA pela
        mancha e grava, com PRIORIDADE de classe (perigo maior fica por cima;
        classe menor nao cobre area de classe maior)."""
        from osgeo import ogr, osr
        porclasse = {1: [], 2: [], 3: [], 4: [], 5: []}
        for f in poly_layer.getFeatures():
            c = f['classe']
            if c in porclasse:
                porclasse[int(c)].append(ogr.CreateGeometryFromWkt(f.geometry().asWkt()))

        # processa de ALTA para BAIXA, subtraindo as classes superiores ja feitas
        geoms = {}
        acumulado = None  # uniao das classes maiores ja processadas
        for c in (5, 4, 3, 2, 1):
            if not porclasse[c]:
                continue
            g = porclasse[c][0]
            for extra in porclasse[c][1:]:
                g = g.Union(extra)
            qg = QgsGeometry.fromWkt(g.ExportToWkt())
            qg = self._acabar(qg, fechamento, suavizar)
            # recorta pela mancha (o fechamento pode empurrar para fora)
            if mancha_geom is not None and not mancha_geom.isEmpty():
                qg = qg.intersection(mancha_geom)
            if acumulado is not None and not acumulado.isEmpty():
                qg = qg.difference(acumulado)   # nao invade as classes maiores
            if qg and not qg.isEmpty():
                geoms[c] = qg
                acumulado = qg if acumulado is None else acumulado.combine(qg)

        epsg = int(crs_id.split(':')[1])
        srs = osr.SpatialReference(); srs.ImportFromEPSG(epsg)
        ds = ogr.Open(gpkg, 1)
        lyr = ds.CreateLayer(layer_name, srs, ogr.wkbMultiPolygon,
                             options=['OVERWRITE=YES', 'GEOMETRY_NAME=geom'])
        lyr.CreateField(ogr.FieldDefn('classe', ogr.OFTInteger))
        lyr.CreateField(ogr.FieldDefn('faixa', ogr.OFTString))
        rotulos = {cod: rot for (lim, cod, cor, rot) in FAIXAS_ANA}
        for c in (1, 2, 3, 4, 5):
            if c not in geoms:
                continue
            feat = ogr.Feature(lyr.GetLayerDefn())
            feat.SetField('classe', c)
            feat.SetField('faixa', rotulos[c])
            feat.SetGeometry(ogr.CreateGeometryFromWkt(geoms[c].asWkt()))
            lyr.CreateFeature(feat); feat = None
        ds = None
        feedback.pushInfo('Camada de perigo gravada: %s (5 faixas ANA, com acabamento)' % layer_name)

    def postProcessAlgorithm(self, context, feedback):
        try:
            from qgis.core import (QgsCategorizedSymbolRenderer, QgsRendererCategory,
                                    QgsFillSymbol)
            proj = QgsProject.instance()
            for src, nome, tipo in getattr(self, '_add', []):
                if tipo == 'hv':
                    rl = QgsRasterLayer(src, nome)
                    if rl.isValid():
                        rl.setRenderer(QgsSingleBandPseudoColorRenderer(
                            rl.dataProvider(), 1, self._shader_ana()))
                        rl.triggerRepaint()
                        # salva o estilo .qml ao lado do raster
                        try:
                            rl.saveNamedStyle(os.path.splitext(src)[0] + '.qml')
                        except Exception:
                            pass
                        proj.addMapLayer(rl)
                else:  # vetor de perigo: categorizado nas faixas ANA
                    vl = QgsVectorLayer(src, nome, 'ogr')
                    if vl.isValid():
                        cats = []
                        for (lim, cod, cor, rot) in FAIXAS_ANA:
                            sym = QgsFillSymbol.createSimple({'color': cor, 'outline_color': cor})
                            cats.append(QgsRendererCategory(cod, sym, rot))
                        vl.setRenderer(QgsCategorizedSymbolRenderer('classe', cats))
                        proj.addMapLayer(vl)
        except Exception:
            pass
        return {}
