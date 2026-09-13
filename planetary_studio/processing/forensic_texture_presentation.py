"""Read-only descriptions of existing analysis values; no detector calculations."""
from bisect import bisect_left
from html import escape


FRIENDLY_METRICS = {
    'high_frequency': 'Detalhes finos',
    'fine_coarse': 'Relação entre detalhes',
    'gradient': 'Bordas e contraste',
    'fft': 'Padrão de frequência',
    'compression': 'Padrão de processamento',
    'rgb': 'Diferença de cor',
    'boundary': 'Diferença para o entorno',
}


def category(value):
    # Shared endpoints belong to the next band; 1 remains in the last band.
    return ('Muito baixa', 'Baixa', 'Moderada', 'Alta', 'Muito alta')[
        sum(value >= edge for edge in (.2, .4, .6, .8))]


def friendly_value(value):
    return f'{value:.1%} — {category(value)}'


class RegionPresentation:
    def __init__(self, regions):
        self.count = len(regions)
        self.distributions = {
            key: sorted(r[key] for r in regions)
            for key in ['score', *(k+'_anomaly' for k in FRIENDLY_METRICS)]
        }

    def percentile(self, region, key):
        """Percentage of OTHER analyzed windows strictly below this member."""
        if self.count < 2:
            return None
        return 100 * bisect_left(self.distributions[key], region[key]) / (self.count-1)

    def comparison(self, region, key):
        percentile = self.percentile(region, key)
        if percentile is None:
            return 'sem outras regiões para comparar'
        # Avoid displaying 100% when some other windows tie or exceed this one.
        return f'maior que {int(percentile)}% das outras regiões da imagem'

    def interpretation(self, region, weights):
        active = [key for key in FRIENDLY_METRICS if weights.get(key, 0) > 0
                  and (key != 'rgb' or region.get('rgb_valid', True))]
        if not active:
            return 'Nenhuma métrica interpretável está incluída na anomalia geral. Ative uma métrica para avaliar a região.'
        strong = [k for k in active if region[k+'_anomaly'] >= .6
                  and (self.percentile(region, k+'_anomaly') or 0) >= 90]
        if len(strong) >= 3:
            return 'A região está entre as mais incomuns da imagem em várias métricas.'
        internal = [k for k in active if k != 'boundary']
        if ('boundary' in active and region['boundary_anomaly'] >= .6 and internal
                and max(region[k+'_anomaly'] for k in internal) < .4):
            return 'A principal diferença está no entorno da região, enquanto a textura interna apresenta diferenças pequenas nas métricas ativas.'
        ranked = sorted(active, key=lambda k: region[k+'_anomaly'], reverse=True)
        peak = region[ranked[0]+'_anomaly']
        if peak < .4:
            if any((self.percentile(region, k+'_anomaly') or 0) >= 90 for k in active):
                return 'A região apresenta diferenças pequenas, embora algumas estejam entre as maiores desta imagem.'
            return 'A região apresenta comportamento bastante comum nas métricas ativas.'
        leaders = [k for k in ranked[:2] if region[k+'_anomaly'] >= .4]
        names = ' e '.join(FRIENDLY_METRICS[k].lower() for k in leaders)
        intensity = 'moderadas' if peak < .6 else 'acentuadas'
        return f'A região apresenta diferenças {intensity}, principalmente em {names}.'

    def summary_html(self, region, weights):
        text = (f'<h3>Anomalia geral: {category(region["score"]).upper()}</h3>'
                f'<p>{region["score"]:.1%} — {self.comparison(region, "score")}</p>'
                f'<p><b>Principal achado:</b><br>{self.interpretation(region, weights)}</p>'
                '<p><b>O que mais chamou atenção:</b></p>')
        ranked = sorted(FRIENDLY_METRICS, key=lambda k: region[k+'_anomaly'], reverse=True)
        text += '<ul>'
        for key in ranked:
            field = key+'_anomaly'
            value = region[field]
            note = ' · fora da anomalia geral' if not weights.get(key, 0) else ''
            if key == 'rgb' and not region.get('rgb_valid', True):
                description = 'Sem variação de cor suficiente para interpretar'
            else:
                description = f'{friendly_value(value)}<br>{self.comparison(region, field)}'
            text += f'<li><b>{escape(FRIENDLY_METRICS[key])}:</b> {description}{note}</li>'
        return text + '</ul>'
