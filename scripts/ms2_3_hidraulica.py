# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# MS 2.0 ANA  ->  Porte para QGIS
# Script 3 de 5: Hidraulica (ANA 2024)  -  SUBSTITUI a planilha de calculo
#
# Porta as macros VBA do MetodoSimplificadoANA_v2.1.xlsm:
#   cotaminima(+fenda) -> declividade -> decaimento Qx (interpolacoef ANA 2024)
#   -> Manning por secao (Param_geom) -> correcao_wse
#
# Le os CSVs gerados pelo Script 2 (perfis + secoes) e o <ID>_MS2.json.
# Grava cotamax (WSE corrigido) e Velocidade em _SecTrans e um CSV de resultados.
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
    QgsProcessingParameterEnum,
    QgsProcessingOutputString,
    QgsProcessingException,
    QgsVectorLayer,
    QgsField,
    edit,
)

# ---------------------------------------------------------------------------
# Configuracao de caminhos (ms2_config.json) - remove os caminhos fixos.
# O arquivo fica na pasta de scripts do perfil do QGIS (ao lado deste .py).
# Conteudo minimo:  { "raiz": "D:/GIS/Barragens" }
# Chave opcional para sobrescrever: coeficientes
# ---------------------------------------------------------------------------
def _ms2_config():
    # Tolerante: se o arquivo nao existe, retorna {} (nao quebra o carregamento).
    # O coeficientes_ana2024.json e' achado ao lado dos scripts, entao o Script 3
    # funciona mesmo sem ms2_config.json.
    import os, json
    try:
        from qgis.core import QgsApplication
        base = os.path.join(QgsApplication.qgisSettingsDirPath(), 'processing', 'scripts')
    except Exception:
        base = os.path.dirname(os.path.abspath(__file__))
    caminho = os.path.join(base, 'ms2_config.json')
    if not os.path.exists(caminho):
        return {}
    with open(caminho, encoding='utf-8') as f:
        return json.load(f)


def _cfg(chave):
    import os
    try:
        from qgis.core import QgsApplication
        base = os.path.join(QgsApplication.qgisSettingsDirPath(), 'processing', 'scripts')
    except Exception:
        base = os.path.dirname(os.path.abspath(__file__))
    c = _ms2_config()
    padrao = {
        # coeficientes acompanha os scripts (mesma pasta); pode ser sobrescrito no config
        'coeficientes': os.path.join(base, 'coeficientes_ana2024.json'),
    }
    return c.get(chave) or padrao.get(chave)


COEF_JSON = _cfg('coeficientes')
MANNING_N_PADRAO = 0.035
SLOPE_MIN = 0.00001      # piso de declividade PADRAO (ANA: sem piso efetivo; a fenda ja garante slope>0)


class Hidraulica(QgsProcessingAlgorithm):
    """3 - Hidraulica (ANA 2024)."""

    PASTA = 'PASTA'
    ID_BAR = 'ID_BAR'
    MANNING = 'MANNING'
    INCERTEZA = 'INCERTEZA'
    FENDA = 'FENDA'
    METODO_QX = 'METODO_QX'
    SLOPE_MIN_P = 'SLOPE_MIN'
    OUT_RESULT = 'OUT_RESULT'

    def tr(self, s):
        return QCoreApplication.translate('Processing', s)

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    def createInstance(self):
        return Hidraulica()

    def name(self):
        return 'ms2_3_hidraulica'

    def displayName(self):
        return self.tr('3 - Hidraulica (ANA 2024)')

    def group(self):
        return self.tr('MS 2.0 ANA')

    def groupId(self):
        return 'ms2ana'

    def shortHelpString(self):
        return self.tr(
            'Calcula a hidraulica das secoes (substitui a planilha): cota minima '
            '+ fenda, declividade, decaimento da vazao (ANA 2024), Manning por '
            'secao e correcao de remanso. Grava cotamax (WSE) e Velocidade.\n\n'
            'Le os CSVs do Script 2 e o <ID>_MS2.json.')

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            self.PASTA, self.tr('Pasta de Trabalho'),
            behavior=QgsProcessingParameterFile.Folder))
        self.addParameter(QgsProcessingParameterString(
            self.ID_BAR, self.tr('ID da Barragem')))
        self.addParameter(QgsProcessingParameterNumber(
            self.MANNING, self.tr('Coeficiente de Manning (n)'),
            type=QgsProcessingParameterNumber.Double, defaultValue=MANNING_N_PADRAO,
            minValue=0.01, maxValue=0.2))
        self.addParameter(QgsProcessingParameterNumber(
            self.INCERTEZA, self.tr('Margem de incerteza no WSE (m)'),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.0,
            minValue=0.0, maxValue=5.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.FENDA, self.tr('Profundidade da fenda (m) - praxe ANA = 0,05'),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.05,
            minValue=0.0, maxValue=1.0))
        self.addParameter(QgsProcessingParameterEnum(
            self.METODO_QX, self.tr('Metodo de decaimento da vazao (Qx)'),
            options=['ANA 2024/2023 (exp/potencia)', 'ANA 2014 (MS1)'],
            defaultValue=1))
        self.addParameter(QgsProcessingParameterNumber(
            self.SLOPE_MIN_P, self.tr('Piso de declividade (m/m) - ANA usa ~0 (sem piso); 0,0003 = conservador'),
            type=QgsProcessingParameterNumber.Double, defaultValue=SLOPE_MIN,
            minValue=0.0, maxValue=0.01))
        self.addOutput(QgsProcessingOutputString(self.OUT_RESULT, self.tr('CSV de resultados')))

    # ===================== decaimento ANA 2024 =============================
    @staticmethod
    def _classe(slope):
        """Retorna (bloco, percentil) conforme a macro interpolacoef."""
        if slope <= 0.0005:
            return 'lt001', 'P25'
        if slope <= 0.001:
            return 'lt001', 'Media'
        if slope <= 0.005:
            return 'gt001', 'P25'
        return 'gt001', 'Media'

    @staticmethod
    def _interp_alt_vol(rows, vol, alt, getter):
        """Interpola bilinear por altura (dentro de cada volume) e depois por volume."""
        vols = sorted(set(r['vol'] for r in rows))

        def at_vol(v):
            sub = sorted([r for r in rows if r['vol'] == v], key=lambda r: r['alt'])
            for i in range(len(sub) - 1):
                if sub[i]['alt'] <= alt <= sub[i + 1]['alt']:
                    c0, c1 = getter(sub[i]), getter(sub[i + 1])
                    return c0 + (c1 - c0) * (alt - sub[i]['alt']) / (sub[i + 1]['alt'] - sub[i]['alt'])
            return getter(sub[-1]) if alt >= sub[-1]['alt'] else getter(sub[0])

        for i in range(len(vols) - 1):
            if vols[i] <= vol <= vols[i + 1]:
                c0, c1 = at_vol(vols[i]), at_vol(vols[i + 1])
                return c0 + (c1 - c0) * (vol - vols[i]) / (vols[i + 1] - vols[i])
        return at_vol(vols[-1]) if vol >= vols[-1] else at_vol(vols[0])

    def _coef_decaimento(self, coefs, volume_hm3, altura_m, slope, feedback):
        """Retorna dict {tipo, a, [b, xmin]} interpolado das tabelas ANA 2024."""
        bloco, perc = self._classe(slope)
        alt = min(max(altura_m or 5.1, 5.1), 19.9)
        if volume_hm3 > 0.50001:   # grandes -> exponencial
            vol = min(volume_hm3, 20.0)
            a = self._interp_alt_vol(coefs['grandes'], vol, alt,
                                     lambda r: r[bloco][perc])
            feedback.pushInfo('Decaimento: GRANDE | classe %s/%s | a=%.5f' % (bloco, perc, a))
            return {'tipo': 'exp', 'a': a}
        else:                       # pequenos -> potencia
            vol = max(volume_hm3, 0.2)
            rows = coefs['pequenos'][bloco]
            a = self._interp_alt_vol(rows, vol, alt, lambda r: r['a'][perc])
            b = self._interp_alt_vol(rows, vol, alt, lambda r: r['b'][perc])
            xmin = self._interp_alt_vol(rows, vol, alt, lambda r: r['xmin'][perc])
            feedback.pushInfo('Decaimento: PEQUENO | classe %s/%s | a=%.4f b=%.4f xmin=%.3f'
                              % (bloco, perc, a, b, xmin))
            return {'tipo': 'pot', 'a': a, 'b': b, 'xmin': xmin}

    @staticmethod
    def _qx(qmax, dist_m, dec):
        """Vazao decaida na distancia dist_m (a jusante da barragem)."""
        if dist_m <= 0.0:
            return qmax
        if dec.get('tipo') == 'ana2014':
            V = dec['V_m3']
            if dec.get('V_hm3') and dec['V_hm3'] > 6.2:
                q = qmax * (10.0 ** (-0.01243 * (dist_m / 1000.0)))
            else:
                a = 0.002 * math.log(V) + 0.9626
                b = -0.20047 * ((V + 25000.0) ** (-0.5979))
                q = qmax * a * math.exp(b * dist_m)
            return max(0.0, min(q, qmax))
        x_km = dist_m / 1000.0
        if dec['tipo'] == 'exp':
            q = qmax * math.exp(dec['a'] * x_km)
        else:
            if x_km < dec['xmin']:
                return qmax
            q = qmax * dec['a'] * (x_km ** dec['b'])
        return max(0.0, min(q, qmax))

    # ===================== Manning (Param_geom) ============================
    @staticmethod
    def _manning(perfil, n, slope, q_alvo):
        """Resolve o nivel d'agua (WSE absoluto) e a area p/ a vazao q_alvo.
        perfil: lista [(x, z)]. Retorna (wse, area, ok)."""
        if len(perfil) < 2 or slope <= 0:
            return None, None, False
        zs = [z for _, z in perfil]
        namin, namax = min(zs), max(zs)
        if namax <= namin:
            return None, None, False
        dy = max((namax - namin) / 200.0, 0.005)

        rating = []  # (na, area, Q)
        na = namin
        while na <= namax + 1e-9:
            at = pt = 0.0
            for i in range(len(perfil) - 1):
                x1, y1 = perfil[i]
                x2, y2 = perfil[i + 1]
                if y1 == y2:
                    y2 = y2 + 0.0002
                ym = (y1 + y2) / 2.0
                if (na <= y1 and na >= y2) or (na >= y1 and na <= y2):
                    if na <= y1 and na >= y2:
                        dx = ((x2 - x1) * (na - y2)) / (y1 - y2)
                        ap = (dx * (na - y2)) / 2.0
                        pp = math.hypot(na - y2, dx)
                    else:
                        dx = ((x2 - x1) * (na - y1)) / (y2 - y1)
                        ap = (dx * (na - y1)) / 2.0
                        pp = math.hypot(na - y1, dx)
                else:
                    if ym > na:
                        ap = pp = 0.0
                    else:
                        dx = x2 - x1
                        ap = (na - ym) * dx
                        pp = math.hypot(y2 - y1, dx)
                at += ap
                pt += pp
            pm = pt if pt > 0 else 1.0
            rh = at / pm
            q = (1.0 / n) * at * (rh ** (2.0 / 3.0)) * (slope ** 0.5)
            rating.append((na, at, q))
            na += dy

        # interpola o nivel para q_alvo
        for i in range(1, len(rating)):
            q0 = rating[i - 1][2]
            q1 = rating[i][2]
            if (q0 <= q_alvo <= q1) or (q1 <= q_alvo <= q0):
                if q1 == q0:
                    return rating[i][0], rating[i][1], True
                t = (q_alvo - q0) / (q1 - q0)
                wse = rating[i - 1][0] + t * (rating[i][0] - rating[i - 1][0])
                area = rating[i - 1][1] + t * (rating[i][1] - rating[i - 1][1])
                return wse, area, True
        # q_alvo acima da capacidade da secao
        return rating[-1][0], rating[-1][1], False

    # ===================== execucao ========================================
    def processAlgorithm(self, parameters, context, feedback):
        self._reload = None
        pasta = self.parameterAsFile(parameters, self.PASTA, context)
        id_bar = self.parameterAsString(parameters, self.ID_BAR, context).strip()
        n_manning = self.parameterAsDouble(parameters, self.MANNING, context)
        incerteza = self.parameterAsDouble(parameters, self.INCERTEZA, context)
        fenda_val = self.parameterAsDouble(parameters, self.FENDA, context)
        slope_min = self.parameterAsDouble(parameters, self.SLOPE_MIN_P, context)

        pb = os.path.join(pasta, id_bar)
        cfg_path = os.path.join(pb, id_bar + '_MS2.json')
        if not os.path.exists(cfg_path):
            raise QgsProcessingException('Config %s nao encontrado (rode Scripts 1 e 2).' % cfg_path)
        cfg = json.load(open(cfg_path, encoding='utf-8'))

        volume = cfg.get('volume_hm3')
        altura = cfg.get('altura_m')
        qmax = cfg.get('qmax_m3s')
        if not (volume and qmax):
            raise QgsProcessingException('Config sem volume/qmax - rode o Script 1.')

        p_secoes = cfg.get('secoes_csv') or os.path.join(pb, id_bar + '_secoes.csv')
        p_brutas = cfg.get('secoesbrutas_csv') or os.path.join(pb, id_bar + '_SecoesBrutas.csv')
        if not (os.path.exists(p_secoes) and os.path.exists(p_brutas)):
            raise QgsProcessingException('CSVs do Script 2 nao encontrados - rode o Script 2.')

        if not os.path.exists(COEF_JSON):
            raise QgsProcessingException('Tabela de coeficientes nao encontrada: %s' % COEF_JSON)
        coefs = json.load(open(COEF_JSON, encoding='utf-8'))

        # le secoes (ordenadas por ID) e perfis
        secoes = []
        with open(p_secoes, encoding='utf-8') as f:
            for row in csv.DictReader(f):
                secoes.append({'id': int(row['ID']), 'Di': float(row['Di_m']),
                               'dt': float(row['dist_trecho_m']),
                               'cota_min': float(row['cota_min_m'])})
        secoes.sort(key=lambda s: s['id'])

        perfis = {}
        with open(p_brutas, encoding='utf-8') as f:
            for row in csv.DictReader(f):
                lid = int(row['LINE_ID'])
                perfis.setdefault(lid, []).append((float(row['FIRST_DIST']), float(row['FIRST_Z'])))

        # 1) cota minima + FENDA (rio nao pode "subir" a jusante)
        cota_ant = None
        for s in secoes:
            cmin = s['cota_min']
            if cota_ant is not None and cmin >= cota_ant:
                novo = cota_ant - fenda_val
                # insere uma fenda estreita no talvegue do perfil
                perfil = perfis.get(s['id'], [])
                if perfil:
                    izmin = min(range(len(perfil)), key=lambda k: perfil[k][1])
                    d0 = perfil[izmin][0]
                    perfil = (perfil[:izmin + 1]
                              + [(d0 + 0.1, novo), (d0 + 0.2, perfil[izmin][1])]
                              + perfil[izmin + 1:])
                    perfis[s['id']] = perfil
                cmin = novo
            s['cota_min_corr'] = cmin
            cota_ant = cmin

        # 2) declividade por trecho (1o trecho usa a cota do coroamento)
        ncor = cfg.get('cota_coroamento')
        if ncor is None:
            ncor = secoes[0]['cota_min_corr'] + (altura or 0.0)  # estimativa: talvegue S0 + altura
        cota_mont = ncor
        for s in secoes:
            dt = s['dt'] if s['dt'] > 0 else 1.0
            s['slope'] = max((cota_mont - s['cota_min_corr']) / dt, 0.0)
            cota_mont = s['cota_min_corr']
        # declividade media do 1o trecho (metade de montante) -> alimenta o decaimento
        meio = max(1, len(secoes) // 2)
        slopes_1 = [s['slope'] for s in secoes[:meio]]
        declim_t1 = sum(slopes_1) / len(slopes_1) if slopes_1 else slope_min
        feedback.pushInfo('Declividade media (1o trecho) = %.5f m/m' % declim_t1)

        # 3) coeficiente de decaimento
        metodo_qx = self.parameterAsEnum(parameters, self.METODO_QX, context)
        dec_2024 = self._coef_decaimento(coefs, volume, altura, declim_t1, feedback)
        if metodo_qx == 1:
            V_m3 = (volume or 0.0) * 1.0e6
            dec = {'tipo': 'ana2014', 'V_m3': V_m3, 'V_hm3': volume, 'metodo': 'ANA 2014 (MS1)'}
            if volume and volume > 6.2:
                feedback.pushInfo('Decaimento: ANA 2014 (MS1) | V>6.2 hm3 | Qx=Qp*10^(-0.01243*x_km)')
            else:
                _a = 0.002 * math.log(V_m3) + 0.9626
                _b = -0.20047 * ((V_m3 + 25000.0) ** (-0.5979))
                feedback.pushInfo('Decaimento: ANA 2014 (MS1) | a=%.4f b=%.3e' % (_a, _b))
        else:
            dec = dec_2024

        # 4) por secao: Qx -> Manning -> WSE, area, velocidade
        avisos = 0
        for s in secoes:
            s['Qx'] = self._qx(qmax, s['Di'], dec)
            slope_m = max(s['slope'], slope_min)
            perfil = perfis.get(s['id'], [])
            wse, area, ok = self._manning(perfil, n_manning, slope_m, s['Qx'])
            if not ok or wse is None:
                avisos += 1
                feedback.pushWarning(
                    'Secao S%d: nao comporta a vazao %.1f m3/s (perfil baixo?). '
                    'Usando o nivel maximo do perfil.' % (s['id'], s['Qx']))
            s['wse'] = wse if wse is not None else s['cota_min_corr']
            s['area'] = area if area else 0.0
            s['prof'] = max(s['wse'] - s['cota_min_corr'], 0.0)
            s['vel'] = (s['Qx'] / area) if area and area > 0 else 0.0

        # 5) correcao de remanso (jusante -> montante) + incerteza
        for i in range(len(secoes) - 2, -1, -1):
            if secoes[i]['wse'] < secoes[i + 1]['wse']:
                secoes[i]['wse'] = secoes[i + 1]['wse']
        for s in secoes:
            s['cotamax'] = s['wse'] + incerteza
            s['prof'] = max(s['cotamax'] - s['cota_min_corr'], 0.0)

        # 6) grava resultados em CSV
        p_result = os.path.join(pb, id_bar + '_resultados_hidraulica.csv')
        with open(p_result, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['ID', 'Di_m', 'cota_min', 'slope', 'Qx_m3s', 'profundidade_m',
                        'WSE_m', 'area_m2', 'velocidade_ms', 'cotamax_m'])
            for s in secoes:
                w.writerow([s['id'], round(s['Di'], 2), round(s['cota_min_corr'], 3),
                            round(s['slope'], 6), round(s['Qx'], 2), round(s['prof'], 3),
                            round(s['wse'], 3), round(s['area'], 2), round(s['vel'], 3),
                            round(s['cotamax'], 3)])
        feedback.pushInfo('Resultados: %s' % p_result)

        # 7) grava cotamax e Velocidade em _SecTrans (por ID)
        gpkg = cfg['gpkg']
        sec = QgsVectorLayer('%s|layername=%s' % (gpkg, cfg['sectrans']), cfg['sectrans'], 'ogr')
        nomes = [fld.name() for fld in sec.fields()]
        novos = [QgsField(c, QVariant.Double) for c in ('cotamax', 'Velocidade', 'profundidade')
                 if c not in nomes]
        if novos:
            sec.dataProvider().addAttributes(novos)
            sec.updateFields()
        i_cm = sec.fields().indexOf('cotamax')
        i_v = sec.fields().indexOf('Velocidade')
        i_p = sec.fields().indexOf('profundidade')
        por_id = {s['id']: s for s in secoes}
        with edit(sec):
            for f in sec.getFeatures():
                sid = f['ID']
                if sid is not None and int(sid) in por_id:
                    s = por_id[int(sid)]
                    sec.changeAttributeValue(f.id(), i_cm, float(round(s['cotamax'], 3)))
                    sec.changeAttributeValue(f.id(), i_v, float(round(s['vel'], 3)))
                    sec.changeAttributeValue(f.id(), i_p, float(round(s['prof'], 3)))

        # atualiza config
        cfg['manning_n'] = n_manning
        cfg['incerteza_m'] = incerteza
        cfg['fenda_m'] = fenda_val
        cfg['declividade_media_1trecho'] = round(declim_t1, 6)
        cfg['decaimento'] = dec
        cfg['metodo_qx'] = 'ANA 2014 (MS1)' if metodo_qx == 1 else 'ANA 2024/2023'
        cfg['resultados_csv'] = p_result
        cfg['cota_coroamento_usada'] = round(ncor, 3)
        json.dump(cfg, open(cfg_path, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)

        feedback.pushInfo('\n***** FIM - Hidraulica concluida para "%s" (%d secoes, %d aviso(s)) *****'
                          % (id_bar, len(secoes), avisos))
        feedback.pushInfo('Proximo: Script 4 (Manchas) usa cotamax para gerar o poligono de inundacao.')
        self._reload = (gpkg, cfg['sectrans'])
        return {self.OUT_RESULT: p_result}

    def postProcessAlgorithm(self, context, feedback):
        try:
            if getattr(self, '_reload', None):
                from qgis.core import QgsProject
                for l in QgsProject.instance().mapLayersByName(self._reload[1]):
                    l.reload(); l.triggerRepaint()
        except Exception:
            pass
        return {}
