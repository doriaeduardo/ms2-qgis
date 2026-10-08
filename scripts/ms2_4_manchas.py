# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# MS 2.0 ANA  ->  Porte para QGIS
# Script 4 de 5: Manchas (poligono de inundacao)
#
# Porta o Manchas.py da toolbox MS2.tbx (ANA):
#   TIN do cotamax (superficie d'agua) -> raster WSE
#   WSE - MDE = profundidade ; inundado onde profundidade > 0
#   dominio = uniao dos convex hulls de pares de secoes consecutivas
#   mancha = poligono do inundado, recortado pelo dominio e suavizado
#
# Le o <ID>_MS2.json (MDE, cotamax em _SecTrans). Gera:
#   <ID>_WSE.tif, <ID>_profundidade.tif e a camada <ID>_Mancha no GeoPackage.
# ---------------------------------------------------------------------------

import os
import json
import math

from qgis.PyQt.QtCore import QCoreApplication, QVariant
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
    QgsProject,
)
import processing


class Manchas(QgsProcessingAlgorithm):
    """4 - Manchas (MS 2.0 ANA / QGIS)."""

    PASTA = 'PASTA'
    ID_BAR = 'ID_BAR'
    SUAVIZAR = 'SUAVIZAR'
    FECHAMENTO = 'FECHAMENTO'
    OUT_MANCHA = 'OUT_MANCHA'

    def tr(self, s):
        return QCoreApplication.translate('Processing', s)

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    def createInstance(self):
        return Manchas()

    def name(self):
        return 'ms2_4_manchas'

    def displayName(self):
        return self.tr('4 - Manchas')

    def group(self):
        return self.tr('MS 2.0 ANA')

    def groupId(self):
        return 'ms2ana'

    def shortHelpString(self):
        return self.tr(
            'Gera o poligono de inundacao a partir do cotamax das secoes '
            '(calculado no Script 3): interpola a superficie d\'agua (TIN), '
            'subtrai o MDE, mapeia onde ha lamina d\'agua, recorta pelo dominio '
            '(corredor das secoes) e suaviza.')

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            self.PASTA, self.tr('Pasta de Trabalho'),
            behavior=QgsProcessingParameterFile.Folder))
        self.addParameter(QgsProcessingParameterString(
            self.ID_BAR, self.tr('ID da Barragem')))
        self.addParameter(QgsProcessingParameterNumber(
            self.SUAVIZAR, self.tr('Suavizacao do contorno (0 = nenhuma)'),
            type=QgsProcessingParameterNumber.Integer, defaultValue=2,
            minValue=0, maxValue=10))
        self.addParameter(QgsProcessingParameterNumber(
            self.FECHAMENTO,
            self.tr('Fechamento/merge (m) - une vaos finos (artefatos); vaos > 2x sao preservados'),
            type=QgsProcessingParameterNumber.Double, defaultValue=25.0, minValue=0.0, maxValue=200.0))
        self.addOutput(QgsProcessingOutputString(self.OUT_MANCHA, self.tr('Camada da mancha')))

    # -----------------------------------------------------------------------
    def processAlgorithm(self, parameters, context, feedback):
        self._add = []
        pasta = self.parameterAsFile(parameters, self.PASTA, context)
        id_bar = self.parameterAsString(parameters, self.ID_BAR, context).strip()
        suavizar = self.parameterAsInt(parameters, self.SUAVIZAR, context)
        fechamento = self.parameterAsDouble(parameters, self.FECHAMENTO, context)

        pb = os.path.join(pasta, id_bar)
        cfg_path = os.path.join(pb, id_bar + '_MS2.json')
        if not os.path.exists(cfg_path):
            raise QgsProcessingException('Config nao encontrado: %s' % cfg_path)
        cfg = json.load(open(cfg_path, encoding='utf-8'))
        gpkg = cfg['gpkg']
        mde_path = cfg['mde']
        crs_id = cfg['crs']

        mde = QgsRasterLayer(mde_path, 'mde')
        if not mde.isValid():
            raise QgsProcessingException('MDE invalido: %s' % mde_path)
        sec = QgsVectorLayer('%s|layername=%s' % (gpkg, cfg['sectrans']), 'sec', 'ogr')
        if sec.fields().indexOf('cotamax') < 0:
            raise QgsProcessingException('_SecTrans sem o campo cotamax - rode o Script 3 antes.')
        feats = [f for f in sec.getFeatures() if f['cotamax'] is not None]
        if len(feats) < 2:
            raise QgsProcessingException('Menos de 2 secoes com cotamax - rode o Script 3.')
        feats.sort(key=lambda f: (f['ID'] if f['ID'] is not None else 1e9))

        # extensao/resolucao do MDE (para alinhar o WSE)
        ext = mde.extent()
        pix = abs(mde.rasterUnitsPerPixelX()) or 30.0
        # limita a extensao do TIN ao corredor das secoes (+buffer) p/ ganhar tempo
        sec_ext = sec.extent()
        sec_ext.grow(pix * 5)
        sec_ext = sec_ext.intersect(ext)
        ext_str = '%f,%f,%f,%f [%s]' % (sec_ext.xMinimum(), sec_ext.xMaximum(),
                                        sec_ext.yMinimum(), sec_ext.yMaximum(), crs_id)

        # 1) TIN da superficie d'agua (cotamax) -> raster WSE
        fidx = sec.fields().indexOf('cotamax')
        # formato: source ::~:: valueSource(0=atributo) ::~:: indiceAtributo ::~:: tipo(2=breaklines)
        interp = '%s::~::0::~::%d::~::2' % (sec.source(), fidx)
        wse_tif = os.path.join(pb, id_bar + '_WSE.tif')
        feedback.pushInfo('Interpolando a superficie d\'agua (TIN)...')
        processing.run('qgis:tininterpolation', {
            'INTERPOLATION_DATA': interp, 'METHOD': 0,
            'EXTENT': ext_str, 'PIXEL_SIZE': pix, 'OUTPUT': wse_tif},
            context=context, feedback=None)

        # 2) profundidade = WSE - MDE (onde WSE existe e WSE > MDE), via gdal/numpy
        prof_tif = os.path.join(pb, id_bar + '_profundidade.tif')
        self._calc_profundidade(mde_path, wse_tif, prof_tif, feedback)

        # 3) dominio = uniao dos convex hulls de pares de secoes consecutivas
        feedback.pushInfo('Construindo o dominio (corredor das secoes)...')
        hulls = []
        for i in range(len(feats) - 1):
            comb = feats[i].geometry().combine(feats[i + 1].geometry())
            h = comb.convexHull()
            if h and not h.isEmpty():
                hulls.append(h)
        dominio = QgsGeometry.unaryUnion(hulls)

        # 4) poligoniza a profundidade (>0) e recorta pelo dominio
        feedback.pushInfo('Vetorizando a mancha...')
        poly_tmp = processing.run('gdal:polygonize', {
            'INPUT': prof_tif, 'BAND': 1, 'FIELD': 'prof', 'EIGHT_CONNECTEDNESS': True,
            'OUTPUT': 'TEMPORARY_OUTPUT'}, context=context, feedback=None)['OUTPUT']
        poly = QgsVectorLayer(poly_tmp, 'poly', 'ogr') if isinstance(poly_tmp, str) else poly_tmp

        # dissolve tudo e intersecta com o dominio
        partes = [f.geometry() for f in poly.getFeatures() if not f.geometry().isEmpty()]
        if not partes:
            raise QgsProcessingException('Nenhum pixel inundado gerado - verifique cotamax/MDE.')
        mancha_geom = QgsGeometry.unaryUnion(partes)
        if dominio and not dominio.isEmpty():
            mancha_geom = mancha_geom.intersection(dominio)

        # 5) ACABAMENTO (merge): fechamento morfologico curto - une vaos FINOS
        #    (frestas de juncao do dominio e serrilhado do raster 30 m) e
        #    PRESERVA os vaos grandes/reais (> 2x a distancia). Nao inventa
        #    inundacao em trechos secos longos.
        if fechamento > 0 and not mancha_geom.isEmpty():
            fechada = mancha_geom.buffer(fechamento, 8).buffer(-fechamento, 8)
            if fechada and not fechada.isEmpty():
                mancha_geom = fechada
                feedback.pushInfo('Fechamento de %.0f m aplicado (une vaos < %.0f m).'
                                  % (fechamento, 2 * fechamento))
        if suavizar > 0 and not mancha_geom.isEmpty():
            mancha_geom = mancha_geom.smooth(suavizar, 0.25)
            feedback.pushInfo('Mancha suavizada (%d iteracoes).' % suavizar)
        mancha_name = id_bar + '_Mancha'
        rid = (cfg.get('rodada') or {}).get('id')
        self._gravar_poligono(gpkg, mancha_name, crs_id, mancha_geom, rid, feedback)
        # carimba os rasters desta rodada (metadado GDAL, nao altera pixel)
        self._tag_rodada(wse_tif, rid)
        self._tag_rodada(prof_tif, rid)

        area_ha = mancha_geom.area() / 10000.0
        feedback.pushInfo('Area inundada: %.1f ha (%.3f km2)' % (area_ha, area_ha / 100.0))

        cfg['wse_tif'] = wse_tif
        cfg['profundidade_tif'] = prof_tif
        cfg['mancha'] = mancha_name
        cfg['area_inundada_ha'] = round(area_ha, 2)
        json.dump(cfg, open(cfg_path, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)

        feedback.pushInfo('\n***** FIM - Mancha gerada para "%s" *****' % id_bar)
        self._add = [(prof_tif, id_bar + '_profundidade', 'raster'),
                     ('%s|layername=%s' % (gpkg, mancha_name), mancha_name, 'vetor')]
        return {self.OUT_MANCHA: '%s|layername=%s' % (gpkg, mancha_name)}

    @staticmethod
    def _tag_rodada(path, rodada_id):
        """Grava o rodada_id como metadado GDAL do raster (nao altera pixel/CRS)."""
        if not rodada_id or not path or not os.path.exists(path):
            return
        try:
            from osgeo import gdal
            ds = gdal.Open(path, gdal.GA_Update)
            if ds is not None:
                ds.SetMetadataItem('rodada_id', rodada_id)
                ds = None
        except Exception:
            pass

    @staticmethod
    def _calc_profundidade(mde_path, wse_path, out_path, feedback):
        """profundidade = WSE - MDE onde WSE valido e > MDE; alinha o WSE ao grid do MDE."""
        from osgeo import gdal
        import numpy as np
        gdal.UseExceptions()
        mde_ds = gdal.Open(mde_path)
        gt = mde_ds.GetGeoTransform()
        nx, ny = mde_ds.RasterXSize, mde_ds.RasterYSize
        proj = mde_ds.GetProjection()
        mde_b = mde_ds.GetRasterBand(1)
        mde_nd = mde_b.GetNoDataValue()
        mde = mde_b.ReadAsArray().astype('float64')

        # reamostra o WSE para o grid exato do MDE
        wse_al = gdal.Warp('', wse_path, format='MEM', xRes=gt[1], yRes=abs(gt[5]),
                           outputBounds=[gt[0], gt[3] + gt[5] * ny, gt[0] + gt[1] * nx, gt[3]],
                           width=nx, height=ny, resampleAlg='bilinear')
        wb = wse_al.GetRasterBand(1)
        wnd = wb.GetNoDataValue()
        wse = wb.ReadAsArray().astype('float64')

        prof = wse - mde
        mask = np.ones(prof.shape, dtype=bool)
        if wnd is not None:
            mask &= (wse != wnd)
        if mde_nd is not None:
            mask &= (mde != mde_nd)
        mask &= (prof > 0.0)
        out = np.full(prof.shape, -9999.0, dtype='float32')
        out[mask] = prof[mask].astype('float32')

        drv = gdal.GetDriverByName('GTiff')
        ds = drv.Create(out_path, nx, ny, 1, gdal.GDT_Float32,
                        options=['COMPRESS=DEFLATE', 'TILED=YES'])
        ds.SetGeoTransform(gt)
        ds.SetProjection(proj)
        ob = ds.GetRasterBand(1)
        ob.SetNoDataValue(-9999.0)
        ob.WriteArray(out)
        ds = None
        wse_al = None
        mde_ds = None
        npix = int(mask.sum())
        feedback.pushInfo('Profundidade: %d pixels inundados (max %.2f m).'
                          % (npix, float(prof[mask].max()) if npix else 0.0))

    @staticmethod
    def _gravar_poligono(gpkg, layer_name, crs_id, geom, rodada_id, feedback):
        """Grava a geometria da mancha como camada de poligono no GeoPackage (via ogr)."""
        from osgeo import ogr, osr
        epsg = int(crs_id.split(':')[1])
        srs = osr.SpatialReference(); srs.ImportFromEPSG(epsg)
        ds = ogr.Open(gpkg, 1)
        if ds is None:
            raise QgsProcessingException('Nao foi possivel abrir o GeoPackage.')
        lyr = ds.CreateLayer(layer_name, srs, ogr.wkbMultiPolygon,
                             options=['OVERWRITE=YES', 'GEOMETRY_NAME=geom'])
        lyr.CreateField(ogr.FieldDefn('id', ogr.OFTInteger))
        lyr.CreateField(ogr.FieldDefn('rodada_id', ogr.OFTString))
        feat = ogr.Feature(lyr.GetLayerDefn())
        feat.SetField('id', 1)
        if rodada_id:
            feat.SetField('rodada_id', rodada_id)
        feat.SetGeometry(ogr.CreateGeometryFromWkt(geom.asWkt()))
        lyr.CreateFeature(feat)
        feat = None
        ds = None
        feedback.pushInfo('Mancha gravada: %s' % layer_name)

    def postProcessAlgorithm(self, context, feedback):
        try:
            from qgis.utils import iface
            proj = QgsProject.instance()
            for src, nome, tipo in getattr(self, '_add', []):
                lyr = (QgsRasterLayer(src, nome) if tipo == 'raster'
                       else QgsVectorLayer(src, nome, 'ogr'))
                if lyr.isValid():
                    proj.addMapLayer(lyr)
        except Exception:
            pass
        return {}
