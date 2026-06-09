from src.models.analysis_result import LedAnalysisResult
from src.models.led_features import LedFeatures
from src.models.metric_evaluation import MetricEvaluation
from src.models.metric_vote import MetricVote


class ReferenceLedClassifier:
    def __init__(
        self,
        features_referencia_acesa: LedFeatures,
        features_referencia_apagada: LedFeatures,
    ) -> None:
        self.features_referencia_acesa = features_referencia_acesa
        self.features_referencia_apagada = features_referencia_apagada

    def calcular_distancia_features(self, features_atual: LedFeatures, features_referencia: LedFeatures) -> float:
        pesos = {
            "v_mean": 0.08,
            "v_max": 0.45,
            "v_std": 1.15,
            "v_p95": 0.55,
            "v_p99": 0.75,
            "s_mean": 0.22,
            "s_std": 0.35,
            "center_to_ring_v": 1.35,
            "center_to_ring_s": 0.35,
            "percent_hot_235": 120.0,
            "percent_hot_245": 180.0,
            "percent_hot_250": 240.0,
            "glow_score": 1.85,
        }

        distancia = 0.0

        for nome_feature, peso in pesos.items():
            valor_atual = float(getattr(features_atual, nome_feature, 0.0))
            valor_referencia = float(getattr(features_referencia, nome_feature, 0.0))
            distancia += abs(valor_atual - valor_referencia) * peso

        return float(distancia)

    def avaliar_metricas_referencia(self, features_atual: LedFeatures) -> MetricEvaluation:
        metricas = [
            {"nome": "v_max", "peso": 1.1, "min_delta": 6.0, "fator_on": 0.75},
            {"nome": "v_std", "peso": 1.4, "min_delta": 3.0, "fator_on": 0.65},
            {"nome": "v_p95", "peso": 1.2, "min_delta": 6.0, "fator_on": 0.70},
            {"nome": "v_p99", "peso": 1.2, "min_delta": 6.0, "fator_on": 0.70},
            {"nome": "s_mean", "peso": 0.7, "min_delta": 4.0, "fator_on": 0.60},
            {"nome": "center_to_ring_v", "peso": 1.5, "min_delta": 4.0, "fator_on": 0.65},
            {"nome": "percent_hot_235", "peso": 1.2, "min_delta": 0.015, "fator_on": 0.70},
            {"nome": "percent_hot_245", "peso": 1.5, "min_delta": 0.008, "fator_on": 0.72},
            {"nome": "percent_hot_250", "peso": 1.8, "min_delta": 0.003, "fator_on": 0.75},
            {"nome": "glow_score", "peso": 2.0, "min_delta": 5.0, "fator_on": 0.68},
        ]

        detalhes = []
        peso_total = 0.0
        peso_aceso = 0.0
        votos_aceso = 0
        votos_apagado = 0

        for metrica in metricas:
            nome = metrica["nome"]
            valor_on = float(getattr(self.features_referencia_acesa, nome, 0.0))
            valor_off = float(getattr(self.features_referencia_apagada, nome, 0.0))
            valor_atual = float(getattr(features_atual, nome, 0.0))
            delta_referencia = valor_on - valor_off

            if abs(delta_referencia) < float(metrica["min_delta"]):
                detalhes.append(
                    MetricVote(
                        metrica=nome,
                        usada=False,
                        motivo="diferença pequena entre referências",
                        atual=round(valor_atual, 6),
                        ref_aceso=round(valor_on, 6),
                        ref_apagado=round(valor_off, 6),
                    )
                )
                continue

            limite = valor_off + (delta_referencia * float(metrica["fator_on"]))

            if delta_referencia > 0:
                indica_aceso = valor_atual >= limite
            else:
                indica_aceso = valor_atual <= limite

            peso = float(metrica["peso"])
            peso_total += peso

            if indica_aceso:
                peso_aceso += peso
                votos_aceso += 1
            else:
                votos_apagado += 1

            detalhes.append(
                MetricVote(
                    metrica=nome,
                    usada=True,
                    atual=round(valor_atual, 6),
                    ref_aceso=round(valor_on, 6),
                    ref_apagado=round(valor_off, 6),
                    limite=round(limite, 6),
                    indica="ACESO" if indica_aceso else "APAGADO",
                    peso=peso,
                )
            )

        score_metricas = peso_aceso / peso_total if peso_total > 0 else 0.0

        return MetricEvaluation(
            score_metricas=round(float(score_metricas), 6),
            peso_total=round(float(peso_total), 6),
            peso_aceso=round(float(peso_aceso), 6),
            votos_aceso=votos_aceso,
            votos_apagado=votos_apagado,
            detalhes=detalhes,
        )

    def calcular_limite_dinamico(self, nome_feature: str, fator_on: float, fallback: float) -> float:
        valor_on = float(getattr(self.features_referencia_acesa, nome_feature, 0.0))
        valor_off = float(getattr(self.features_referencia_apagada, nome_feature, 0.0))
        delta = valor_on - valor_off

        if delta <= 0.0001:
            return fallback

        return valor_off + (delta * fator_on)

    def classificar_led_por_referencia(
        self,
        features_atual: LedFeatures,
        centro_x: int,
        centro_y: int,
        raio: int,
    ) -> LedAnalysisResult:
        distancia_on = self.calcular_distancia_features(features_atual, self.features_referencia_acesa)
        distancia_off = self.calcular_distancia_features(features_atual, self.features_referencia_apagada)
        avaliacao_metricas = self.avaliar_metricas_referencia(features_atual)

        v_mean_on = float(self.features_referencia_acesa.v_mean)
        v_mean_off = float(self.features_referencia_apagada.v_mean)
        v_mean_atual = float(features_atual.v_mean)

        limite_v_mean = v_mean_off + ((v_mean_on - v_mean_off) * 0.60)

        if v_mean_on > v_mean_off:
            brilho_indica_aceso = v_mean_atual >= limite_v_mean
        else:
            brilho_indica_aceso = v_mean_atual <= limite_v_mean

        # Antes estava muito rígido em 0.82.
        # Em imagens reais da PCI, LEDs acesos podem ficar mais próximos da referência apagada
        # por causa de reflexo, exposição, ângulo e diferença entre a foto de referência e a foto de teste.
        similaridade_indica_aceso = distancia_on < (distancia_off * 0.95)

        v_std_atual = float(features_atual.v_std)
        v_p99_atual = float(features_atual.v_p99)
        percent_hot_245_atual = float(features_atual.percent_hot_245)
        percent_hot_250_atual = float(features_atual.percent_hot_250)
        center_to_ring_v_atual = float(features_atual.center_to_ring_v)
        glow_score_atual = float(features_atual.glow_score)

        limite_v_std = self.calcular_limite_dinamico("v_std", 0.65, fallback=30.0)
        limite_center_to_ring_v = self.calcular_limite_dinamico("center_to_ring_v", 0.65, fallback=8.0)
        limite_glow_score = self.calcular_limite_dinamico("glow_score", 0.68, fallback=32.0)
        limite_v_p99 = self.calcular_limite_dinamico("v_p99", 0.70, fallback=248.0)

        percent_hot_245_on = float(self.features_referencia_acesa.percent_hot_245)
        percent_hot_245_off = float(self.features_referencia_apagada.percent_hot_245)
        percent_hot_250_on = float(self.features_referencia_acesa.percent_hot_250)
        percent_hot_250_off = float(self.features_referencia_apagada.percent_hot_250)

        limite_percent_hot_245 = max(
            0.020,
            percent_hot_245_off + ((percent_hot_245_on - percent_hot_245_off) * 0.35),
        )
        limite_percent_hot_250 = max(
            0.006,
            percent_hot_250_off + ((percent_hot_250_on - percent_hot_250_off) * 0.30),
        )

        # Não usar v_max sozinho.
        # O LED apagado pode ter v_max alto por reflexo ou saturação pontual.
        # O pico só deve indicar aceso quando existe área quente suficiente.
        pico_indica_aceso = (
            v_p99_atual >= max(245.0, limite_v_p99)
            or percent_hot_245_atual >= limite_percent_hot_245
            or percent_hot_250_atual >= limite_percent_hot_250
        )

        contraste_indica_aceso = (
            v_std_atual >= limite_v_std
            or center_to_ring_v_atual >= limite_center_to_ring_v
            or glow_score_atual >= limite_glow_score
        )

        score_metricas = float(avaliacao_metricas.score_metricas)
        metricas_indicam_aceso = score_metricas >= 0.58

        votos_aceso = int(avaliacao_metricas.votos_aceso)
        votos_apagado = int(avaliacao_metricas.votos_apagado)

        votos_favorecem_aceso = votos_aceso >= (votos_apagado + 2)
        evidencia_luminosa_forte = pico_indica_aceso and metricas_indicam_aceso and votos_favorecem_aceso

        apagado_forte = (
            score_metricas <= 0.45
            and percent_hot_245_atual < limite_percent_hot_245
            and percent_hot_250_atual < limite_percent_hot_250
            and v_p99_atual < max(245.0, limite_v_p99)
        )

        tem_luz = (
            evidencia_luminosa_forte
            or (pico_indica_aceso and similaridade_indica_aceso and score_metricas >= 0.50)
            or (pico_indica_aceso and contraste_indica_aceso and score_metricas >= 0.50)
            or (brilho_indica_aceso and pico_indica_aceso and votos_favorecem_aceso)
        )

        if apagado_forte:
            tem_luz = False

        denominador_confianca = distancia_on + distancia_off + 0.0001
        confianca_similaridade = abs(distancia_off - distancia_on) / denominador_confianca
        distancia_decisao = abs(score_metricas - 0.50) * 2.0

        if tem_luz:
            confianca_evidencia_luminosa = min(
                1.0,
                max(
                    score_metricas,
                    percent_hot_245_atual * 3.0,
                    percent_hot_250_atual * 5.0,
                ),
            )
            confianca = max(confianca_similaridade, distancia_decisao, confianca_evidencia_luminosa)
        else:
            confianca_evidencia_apagado = min(
                1.0,
                max(
                    1.0 - score_metricas,
                    1.0 - min(1.0, percent_hot_245_atual / max(limite_percent_hot_245, 0.0001)),
                    1.0 - min(1.0, percent_hot_250_atual / max(limite_percent_hot_250, 0.0001)),
                ),
            )
            confianca = max(confianca_similaridade, distancia_decisao, confianca_evidencia_apagado)

        confianca = min(1.0, confianca)

        motivos = [
            "pico/área quente compatível" if pico_indica_aceso else "sem área quente suficiente",
            "contraste/glow compatível" if contraste_indica_aceso else "contraste/glow baixo",
            "métricas favorecem aceso" if metricas_indicam_aceso else "métricas não favorecem aceso",
            "votos favorecem aceso" if votos_favorecem_aceso else "votos não favorecem aceso",
            "similaridade forte com aceso" if similaridade_indica_aceso else "similaridade insuficiente",
            "apagado forte" if apagado_forte else "apagado não confirmado",
        ]

        return LedAnalysisResult(
            id="LED_SELECIONADO",
            status="ACESO" if tem_luz else "APAGADO",
            valor_binario=1 if tem_luz else 0,
            centro_x=centro_x,
            centro_y=centro_y,
            raio=raio,
            features=features_atual,
            limite_v_mean=round(float(limite_v_mean), 4),
            limite_v_std=round(float(limite_v_std), 4),
            limite_center_to_ring_v=round(float(limite_center_to_ring_v), 4),
            limite_glow_score=round(float(limite_glow_score), 4),
            limite_v_p99=round(float(limite_v_p99), 4),
            distancia_on=round(float(distancia_on), 4),
            distancia_off=round(float(distancia_off), 4),
            brilho_indica_aceso=bool(brilho_indica_aceso),
            similaridade_indica_aceso=bool(similaridade_indica_aceso),
            pico_indica_aceso=bool(pico_indica_aceso),
            contraste_indica_aceso=bool(contraste_indica_aceso),
            metricas_indicam_aceso=bool(metricas_indicam_aceso),
            avaliacao_metricas=avaliacao_metricas,
            motivos=motivos,
            confianca=round(float(confianca), 4),
        )