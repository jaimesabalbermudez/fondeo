"""Dashboard: `uv run fondeos-dashboard`.

Tres páginas: la guía de cómo operar, la simulación de tu bankroll y los planes. Todo usa la forma de
operar recomendada (`recommended.py`); los cálculos caros viven en la caché de disco
(`uv run fondeos-precalcular` los deja hechos).
"""

from dataclasses import replace

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from fondeos_sim import recommended as rec
from fondeos_sim.portfolio import MONTH

BLUE = "#4ea1ff"     # series de datos
ORANGE = "#ff8a3d"   # acentos y lo destacado
GRAY = "#7d8699"
MUTED = "#3a4560"
CFG = rec.DEFAULT
NQ, MNQ = 20.0, 2.0   # $ por punto

st.set_page_config(page_title="Fondeos", page_icon="📈", layout="wide")
st.markdown("""
<style>
  .block-container {padding-top: 2.2rem; max-width: 1180px;}
  h1 {font-weight: 700; letter-spacing: -0.02em; margin-bottom: 0.2rem;}
  .lead {font-size: 1.08rem; opacity: 0.75; margin-bottom: 1.4rem;}
  .step {display: flex; gap: 0.9rem; align-items: flex-start; margin: 0.15rem 0 0.9rem;}
  .step-n {flex: 0 0 2rem; height: 2rem; border-radius: 50%; background: linear-gradient(135deg, #ff8a3d, #ff6a3d); color: #0e1320;
           display: flex; align-items: center; justify-content: center; font-weight: 700;}
  .step-t {font-weight: 650; margin-bottom: 0.15rem;}
  .step-d {opacity: 0.8; font-size: 0.95rem; line-height: 1.45;}
  .tag {display: inline-block; padding: 0.1rem 0.55rem; border-radius: 999px; font-size: 0.78rem;
        background: rgba(78,161,255,0.14); color: #8cc2ff; border: 1px solid rgba(78,161,255,0.3); font-weight: 600; margin: 0 0.3rem 0.6rem 0;}
  .muted {opacity: 0.7; font-size: 0.9rem;}
  div[data-testid="stMetricValue"] {font-weight: 650; color: #ffb37d;}
  div[data-testid="stMetric"] {background: linear-gradient(160deg, rgba(78,161,255,0.08), rgba(255,138,61,0.05));}
  h1 {background: linear-gradient(90deg, #ff8a3d, #4ea1ff); -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;}
  h2, h3 {color: #8cc2ff;}
  section[data-testid="stSidebar"] {background: #0a0f1a;}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------- datos (memoria + disco)
@st.cache_resource(show_spinner="Calculando estrategias (solo la primera vez)...")
def opt(plan_id):
    return rec.optimized(plan_id)


@st.cache_resource(show_spinner="Calculando el ranking de planes (solo la primera vez)...")
def ranked():
    return rec.all_plans_ranked()


@st.cache_resource(show_spinner="Simulando tu cartera...")
def sim(bankroll, months, n_paths=2000, tpd=CFG.trades_per_day):
    return rec.simulate(bankroll, months, n_paths, cfg=replace(CFG, trades_per_day=tpd))


@st.cache_resource(show_spinner="Buscando el bankroll necesario...")
def needed(target):
    return rec.bankroll_needed(target)


@st.cache_data(show_spinner="Comparando bankrolls...")
def bankroll_table():
    rows = []
    for b in rec.BANKROLL_LEVELS:
        r = rec.simulate(b, 6, 1500)
        p = r.final - b
        rows.append({"Bankroll": b, "Beneficio mediano": np.median(p), "Beneficio medio": p.mean(),
                     "P(ruina)": r.ruined.mean()})
    return pd.DataFrame(rows)


def md(text, help=None, **kw):
    """st.markdown con los $ escapados: Streamlit interpreta $...$ como fórmula LaTeX."""
    esc = lambda t: t.replace("$", r"\$")
    st.markdown(esc(text), help=esc(help) if help else None, **kw)


def caption(text):
    st.caption(text.replace("$", r"\$"))


def money(x):
    return f"-${-x:,.0f}" if x < 0 else f"${x:,.0f}"


def pts(dollars, per_point):
    return f"{dollars / per_point:,.0f} pts"


def stop_txt(risk, per_point=None, margin=2000):
    if risk is None or risk == float("inf"):
        ex = f" (≈{pts(margin, per_point)} al inicio)" if per_point else ""
        return f"todo el margen hasta el suelo{ex}"
    return money(risk) + (f" (≈{pts(risk, per_point)})" if per_point else "")


def name(p):
    return f"{p.firm} · {p.name}"


def eval_days(p, es):
    """Secuencia de la evaluación si todos los trades salen bien (misma lógica que engine.eval_step)."""
    r, start = p.eval, p.start_balance
    bal, floor, best, days = start, start - r.mll, 0.0, []
    lock = start + r.lock_offset if r.lock_offset is not None else float("inf")
    while len(days) < 30:
        profit = bal - start
        need = r.profit_target - profit
        if r.consistency:
            need = max(need, best / r.consistency - profit)
        if need <= 1e-9 and len(days) >= r.min_days:
            break
        target = max(min(es.day_target, need), 0.0)
        margin = bal - floor if es.risk is None else min(es.risk, bal - floor)
        if r.dll:
            margin = min(margin, r.dll)            # el DLL corta el día antes que el suelo
        days.append((target, margin))
        bal += target
        best = max(best, target)
        if r.drawdown != "static":
            floor = max(floor, min(bal - r.mll, lock))
    return days, lock


def eval_help(p, es, days, lock):
    r = p.eval
    txt = ("Cada día un solo trade con su objetivo y su stop. Si sale mal, normalmente la cuenta se quema y se "
           "empieza otra. Nunca se busca más de lo que falta, así que el último día suele ser más pequeño.")
    if r.consistency:
        txt += (f"\n\nConsistencia {r.consistency:.0%}: el mejor día no puede pasar del {r.consistency:.0%} del "
                f"profit total. Por eso el máximo diario es {money(r.consistency * r.profit_target)} y el último "
                "día completa lo que falta.")
    if lock != float("inf") and r.drawdown != "static":
        txt += (f"\n\nEl suelo sube con el balance hasta fijarse en {money(lock)}; desde ahí el margen crece y "
                "el último trade es más fácil.")
    if any(t == 0 for t, _ in days):
        txt += f"\n\nDías con +$0: solo para cumplir el mínimo de {r.min_days} días (sin arriesgar)."
    txt += "\n\nRiesgo máximo cada día (suelo, stop o DLL): " + " · ".join(money(m) for _, m in days)
    return txt


def step(n, title, text):
    md(f'<div class="step"><div class="step-n">{n}</div><div><div class="step-t">{title}</div>'
                f'<div class="step-d">{text}</div></div></div>', unsafe_allow_html=True)


# ---------------------------------------------------------------- páginas
def page_guide():
    st.title("Cómo operar las cuentas de fondeo")
    md('<div class="lead">Estrategia breakeven: no hace falta ganar al mercado. El valor sale de las '
                'reglas de cada firma — elegir bien firma, fase y tamaño de cada trade.</div>', unsafe_allow_html=True)

    b5, _ = needed(0.05)
    b1, _ = needed(0.01)
    best = max((opt(s.plan_id) for s in CFG.slots), key=lambda r: r.ev_attempt)
    r3 = sim(5000, 12)
    k = st.columns(4)
    k[0].metric("Bankroll recomendado", money(round(b5, -2)), "ruina ≤ 5% en 6 meses", delta_color="off",
                border=True, help=f"Con {money(round(b1, -2))} la ruina baja al 1%.")
    k[1].metric(f"EV por evaluación ({best.plan.firm})", money(best.ev_attempt), f"ROI {best.roi:+.0%}", border=True)
    k[2].metric("Beneficio mediano 12 meses", money(np.median(r3.final - 5000)), "empezando con $5.000",
                delta_color="off", border=True)
    k[3].metric("Riesgo de ruina", "2–3 meses", "después casi desaparece", delta_color="off", border=True,
                help="El 95% de las ruinas ocurre al principio; cuando la caja llega a ~2,5× el bankroll "
                     "inicial la ruina es casi imposible.")

    st.subheader("Las reglas")
    left, right = st.columns(2, gap="large")
    first = list(dict.fromkeys(opt(s.plan_id).plan.firm for s in CFG.slots if s.from_cash == 0))
    later = list(dict.fromkeys(opt(s.plan_id).plan.firm for s in CFG.slots if s.from_cash > 0))
    expand = min((s.from_cash for s in CFG.slots if s.from_cash), default=0)
    with left:
        step(1, "Solo firmas EOD que permiten la estrategia",
             "Drawdown de fin de día y sin prohibiciones contra el 'todo o nada': " + ", ".join(first + later) + ".")
        step(2, f"Empieza con {' y '.join(first)}",
             f"Son las de mejor rendimiento por dólar. Añade {' y '.join(later)} cuando tu caja libre "
             f"llegue a {money(expand)}.")
        step(3, "Con poca caja, juega prudente",
             f"Mientras tu caja libre esté por debajo de {money(CFG.prudent_below)}, en las cuentas funded "
             f"busca un día gordo de +{money(CFG.prudent_gordo)} (en vez del óptimo, mucho mayor). Cobras el "
             "doble de veces y la ruina baja a la mitad.")
    with right:
        step(4, "Cada cuenta su propio trade, una detrás de otra",
             "Nunca copies el mismo trade en todas a la vez: si pierden juntas, el bankroll se vacía de golpe. "
             "Separando los trades el valor esperado es el mismo y el riesgo mucho menor.")
        step(5, f"Unos {CFG.trades_per_day} trades al día, rotando cuentas",
             "No hace falta operar todas las cuentas cada día: opera primero las que más tiempo llevan paradas. "
             "Ninguna puede pasar una semana sin un trade (Tradeify, MFFU) ni un mes (Lucid, FundedNext). "
             "Reinvierte y aguanta: el riesgo se concentra en los 2–3 primeros meses.")
        step(6, "Respeta los límites de cada firma",
             "Lucid: 5 funded y ≤10 cuentas abiertas · Tradeify: 5 funded, 15 compras/30 días · "
             "MFFU Rapid EOD: 3 funded · FundedNext: 5 funded, 10 activaciones/mes.")

    guide_schedule()

    st.subheader("Qué hacer en cada cuenta")
    md('<span class="muted">Objetivos netos de comisiones. Puntos de ejemplo en NQ: evaluación con 1 NQ '
                '($20/pt), día gordo con 2 NQ ($40/pt, lo que permite el scaling plan de Lucid al empezar), '
                'días verdes con 5 MNQ ($10/pt).</span>', unsafe_allow_html=True)
    tabs = st.tabs([opt(s.plan_id).plan.firm for s in CFG.slots])
    for tab, s in zip(tabs, CFG.slots):
        r = opt(s.plan_id)
        p, es, fs = r.plan, r.eval_strat, r.funded_strat
        with tab:
            md(f'<span class="tag">{p.name}</span><span class="tag">{money(p.costs.attempt_price())} '
                        f'por intento</span><span class="tag">{s.parallel} evaluaciones a la vez</span>'
                        + (f'<span class="tag">desde {money(s.from_cash)} de caja</span>' if s.from_cash else ""),
                        unsafe_allow_html=True)
            c1, c2, c3 = st.columns(3, gap="medium")
            with c1.container(border=True):
                md("**1 · Evaluación**")
                if es is None:
                    md("- Sin evaluación: directo a funded.")
                else:
                    days, lock = eval_days(p, es)
                    md("- Día a día si todo sale bien: **" + " · ".join(f"+{money(t)}" for t, _ in days) + "**",
                       help=eval_help(p, es, days, lock))
                    md(f"- Máximo diario **+{money(es.day_target)}** (≈{pts(es.day_target, NQ)})\n"
                                f"- Stop: **{stop_txt(es.risk, NQ, p.eval.mll)}**\n"
                                f"- Objetivo total {money(p.eval.profit_target)}"
                                + (f", consistencia {p.eval.consistency:.0%}" if p.eval.consistency else "")
                                + f"\n- Aprueba el **{r.p_pass:.0%}** de las veces")
            with c2.container(border=True):
                md("**2 · Funded con caja grande**")
                lines = []
                if fs.gordo_target:
                    lines.append(f"Día gordo: **+{money(fs.gordo_target)}** de golpe arriesgando todo el margen "
                                 f"(≈{pts(fs.gordo_target, 2 * NQ)} con 2 NQ)")
                lines.append(f"Después días verdes de **+{money(fs.grind_target)}**, stop "
                             f"**{stop_txt(fs.grind_risk)}** (≈{pts(fs.grind_target, 5 * MNQ)} con 5 MNQ)")
                if fs.cycle_gordo:
                    lines.append(f"Tras cada payout, otro día gordo de **+{money(fs.cycle_gordo)}**")
                lines.append(f"Cobra en el **{r.fd['p_payout']:.0%}** de las cuentas · vale "
                             f"**{money(r.value)}** de media")
                md("\n".join(f"- {x}" for x in lines))
            with c3.container(border=True):
                md(f"**2 · Funded con caja < {money(CFG.prudent_below)}**")
                if s.from_cash >= CFG.prudent_below:
                    md(f"- No aplica: esta firma solo se opera con caja ≥ {money(s.from_cash)}.")
                else:
                    ps = rec.prudent_strategy(fs, CFG)
                    md(f"- Día gordo: **+{money(ps.gordo_target)}** arriesgando todo el margen "
                                f"(≈{pts(ps.gordo_target, 2 * NQ)} con 2 NQ)\n"
                                f"- Después días verdes de **+{money(ps.grind_target)}**, stop "
                                f"**{money(ps.grind_risk)}** (≈15 / 60 pts con 5 MNQ)\n"
                                "- Cobra más a menudo (≈45–50% de las cuentas) aunque cada cuenta valga menos")

    st.subheader("Según tu bankroll")
    b = st.select_slider("Bankroll inicial", rec.BANKROLL_LEVELS, value=5000, format_func=money,
                         label_visibility="collapsed")
    r = sim(b, 6, 1500)
    p = r.final - b
    active = list(dict.fromkeys(opt(s.plan_id).plan.firm for s in CFG.slots if s.from_cash <= b))
    k = st.columns(4)
    k[0].metric("Firmas desde el día 1", f"{len(active)} de {len(set(opt(s.plan_id).plan.firm for s in CFG.slots))}",
                ", ".join(f.split()[0] for f in active), delta_color="off", border=True)
    k[1].metric("Modo funded al empezar", "prudente" if b < CFG.prudent_below else "óptimo", border=True)
    k[2].metric("Beneficio mediano 6 meses", money(np.median(p)), f"media {money(p.mean())}", delta_color="off",
                border=True)
    k[3].metric("Probabilidad de ruina", f"{r.ruined.mean():.0%}", border=True)
    caption("Detalle completo, abanico de resultados y cualquier otro bankroll en la página **Simulación**.")


# volatilidad del NQ por franja (pts/√min, velas de 5 min, 60 días hasta oct 2026): analysis/06_horario.py
VOL = [("Pre 4:00–9:30", 7.0), ("Apertura 9:30–10:00", 18.8), ("10:00–11:00", 13.4), ("11:00–14:00", 9.9),
       ("14:00–15:30", 7.7), ("Cierre 15:30–16:00", 8.6), ("Noche", 5.6)]


def guide_schedule():
    st.subheader("Horario")
    md('<span class="muted">Sin ventaja, la hora no cambia la probabilidad de ganar un trade: solo lo rápido que se '
       'resuelve. Como los trades van de uno en uno, la apertura es donde caben más.</span>', unsafe_allow_html=True)
    left, right = st.columns([3, 2], gap="large")
    with left:
        md("""
| Hora Nueva York | Hora España | Qué operar | Por qué |
|---|---|---|---|
| 9:31–10:00 | 15:31–16:00 | **Días gordos**, uno detrás de otro | Son los más lentos; en la apertura un gordo tarda ~30 min (por la tarde, ~3 h) |
| 10:00–11:30 | 16:00–17:30 | **Evaluaciones**, de la de trade más grande a la más pequeña | Aún hay volatilidad: 10–25 min por trade |
| 11:30–15:00 | 17:30–21:00 | **Días verdes** de las funded | Trades pequeños: la lentitud da igual, y en la apertura se resolverían en segundos (regla de microscalping) |
| antes de 15:50 | antes de 21:50 | **Todo cerrado** | FundedNext cierra a las 16:10 NY; nada abierto al final de la sesión |
""", help="Ejemplos: evaluación Lucid ±$1.200 con 1 NQ = 60/60 pts; gordo +$8.000/−$2.000 con 2 NQ = 200/50 pts; "
          "día verde +$150/−$600 con 5 MNQ = 15/60 pts. Tiempo medio hasta TP o SL = TP·SL/σ².")
        md("- **Nunca dos trades abiertos a la vez**: si coinciden en la misma dirección los resultados van juntos, "
           "y en direcciones opuestas es hedging (prohibido).\n"
           "- **Dirección al azar** (o según el gap): con ventaja cero da igual, y así evitas sesgos.\n"
           "- **Noticias**: no abras un trade en el minuto de un dato importante (8:30, 10:00 o 14:00 NY los días de "
           "CPI, NFP, ISM o FOMC): el deslizamiento se dispara.\n"
           "- **Hora en España**: Nueva York + 6 h; en las semanas de cambio de hora (finales de marzo y de octubre) "
           "son 5 h.")
    with right:
        vol = pd.DataFrame(VOL, columns=["Franja (NY)", "Volatilidad"])
        vol["Apertura"] = vol["Franja (NY)"].str.startswith("Apertura")
        st.altair_chart(alt.Chart(vol).mark_bar(cornerRadiusEnd=4).encode(
            y=alt.Y("Franja (NY):N", sort=None, title=None),
            x=alt.X("Volatilidad:Q", title="Volatilidad del NQ (puntos por √minuto)"),
            color=alt.condition(alt.datum.Apertura, alt.value(ORANGE), alt.value(BLUE)),
            tooltip=["Franja (NY)", alt.Tooltip("Volatilidad:Q", format=".1f")]).properties(height=250),
            width="stretch")
        caption("NQ en velas de 5 minutos, últimos 60 días. A más volatilidad, antes se resuelve cada trade.")


def page_sim():
    st.title("Simulación de tu cartera")
    md('<div class="lead">Miles de caminos posibles operando según la guía: compras, aprobados, payouts, '
                'límites de cada firma y reinversión, día a día.</div>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 1, 2])
    bankroll = c1.number_input("Bankroll inicial ($)", 100, 1_000_000, 5000, 100)
    months = c2.segmented_control("Horizonte", [3, 6, 12], default=12, format_func=lambda m: f"{m} meses") or 12
    tpd_opts = {str(t) if t else "sin límite": t for t in rec.TRADES_PER_DAY}
    tpd = c3.segmented_control("Trades al día", list(tpd_opts), default=str(CFG.trades_per_day),
                               help="Cuántos trades caben en una sesión operando de uno en uno (ver el horario de "
                                    "la Guía). Con más cuentas que trades, cada día operan las que más tiempo "
                                    "llevan paradas.") or str(CFG.trades_per_day)
    res = sim(int(bankroll), int(months), tpd=tpd_opts[tpd])
    profit = res.final - bankroll

    k = st.columns(4)
    k[0].metric("Beneficio mediano", money(np.median(profit)), help="La mitad de los caminos acaba por encima.",
                border=True)
    k[1].metric("Beneficio medio", money(profit.mean()), f"{profit.mean() / bankroll:+.0%} del bankroll",
                border=True)
    k[2].metric("Probabilidad de ruina", f"{res.ruined.mean():.0%}",
                help="Sin cuentas abiertas y sin caja para comprar otra evaluación.", border=True)
    k[3].metric("Peor 10% de los caminos", money(np.percentile(profit, 10)), border=True)

    q = np.percentile(res.cash, [5, 25, 50, 75, 95], axis=0)
    fan = pd.DataFrame({"mes": res.days / MONTH, "p5": q[0], "p25": q[1], "p50": q[2], "p75": q[3], "p95": q[4]})
    base = alt.Chart(fan).encode(x=alt.X("mes:Q", title="Mes", scale=alt.Scale(nice=False)))
    hover = alt.selection_point(fields=["mes"], nearest=True, on="pointerover", empty=False)
    chart = alt.layer(
        base.mark_area(color=BLUE, opacity=0.14).encode(y=alt.Y("p5:Q", title="Caja ($)"), y2="p95:Q"),
        base.mark_area(color=BLUE, opacity=0.28).encode(y="p25:Q", y2="p75:Q"),
        base.mark_line(color=ORANGE, strokeWidth=2.5).encode(y="p50:Q"),
        alt.Chart(pd.DataFrame({"y": [bankroll]})).mark_rule(color=GRAY, strokeDash=[4, 4]).encode(y="y:Q"),
        base.mark_rule(color=GRAY).encode(
            opacity=alt.condition(hover, alt.value(0.5), alt.value(0)),
            tooltip=[alt.Tooltip("mes:Q", format=".1f"), alt.Tooltip("p5:Q", title="peor 5%", format="$,.0f"),
                     alt.Tooltip("p50:Q", title="mediana", format="$,.0f"),
                     alt.Tooltip("p95:Q", title="mejor 5%", format="$,.0f")]).add_params(hover),
    ).properties(height=330)
    hist = alt.Chart(pd.DataFrame({"b": profit, "Camino": np.where(res.ruined, "arruinado", "superviviente")})
                     ).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        color=alt.Color("Camino:N", scale=alt.Scale(domain=["superviviente", "arruinado"], range=[BLUE, ORANGE]),
                        legend=alt.Legend(orient="top", title=None)),
        x=alt.X("b:Q", bin=alt.Bin(maxbins=36), title="Beneficio final ($)"),
        y=alt.Y("count():Q", title="Caminos"),
        tooltip=[alt.Tooltip("b:Q", bin=alt.Bin(maxbins=36), format="$,.0f", title="beneficio"),
                 alt.Tooltip("count():Q", title="caminos")]).properties(height=330)
    left, right = st.columns([3, 2], gap="large")
    with left:
        md("**Caja en el tiempo** · mediana, 50% y 90% central de los caminos")
        st.altair_chart(chart, width="stretch")
    with right:
        md("**Resultado final**")
        st.altair_chart(hist, width="stretch")
        caption(f"El pico en ≈ {money(-bankroll)} son los caminos arruinados: gastan todo antes del primer payout.")

    st.subheader("¿Cuándo desaparece el riesgo?")
    ru, peak = res.ruined, res.cash.max(axis=1)
    c1, c2 = st.columns([1, 2], gap="large")
    with c1:
        if ru.any():
            st.metric("El 95% de las ruinas ocurre antes del",
                      f"mes {np.percentile(res.ruin_day[ru], 95) / MONTH:.1f}", border=True)
        else:
            st.metric("Ruinas en la simulación", "ninguna", border=True)
    levels = sorted({round(bankroll * m, -2) for m in (1.5, 2.5, 5, 10)})
    tab = pd.DataFrame([{"Si tu caja llega a": lv, "Caminos que llegan": (peak >= lv).mean(),
                         "Ruina desde ese momento": 100 * (ru & (peak >= lv)).sum() / max((peak >= lv).sum(), 1)}
                        for lv in levels])
    c2.dataframe(tab, hide_index=True, width="stretch", column_config={
        "Si tu caja llega a": st.column_config.NumberColumn(format="$%d"),
        "Caminos que llegan": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
        "Ruina desde ese momento": st.column_config.NumberColumn(format="%.2f%%")})

    st.subheader("Por plan")
    rows = []
    for key, s in res.per_plan.items():
        pid, _, mode = key.partition(":")
        rows.append({"Plan": name(opt(pid).plan), "Modo": "prudente" if mode else "óptimo",
                     "Evaluaciones": s["evaluaciones"], "Cuentas funded": s["funded"],
                     "Gastado": s["gastado"], "Cobrado": s["cobrado"], "Neto": s["cobrado"] - s["gastado"]})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={
        **{c: st.column_config.NumberColumn(format="$%.0f") for c in ("Gastado", "Cobrado", "Neto")},
        **{c: st.column_config.NumberColumn(format="%.1f") for c in ("Evaluaciones", "Cuentas funded")}})
    caption("Medias por camino. 'Prudente' = cuentas operadas con caja libre por debajo de "
               f"{money(CFG.prudent_below)}.")

    st.subheader("Comparar bankrolls (6 meses)")
    comp = bankroll_table()
    xb = alt.X("Bankroll:Q", scale=alt.Scale(type="log"), title="Bankroll inicial",
               axis=alt.Axis(values=list(rec.BANKROLL_LEVELS), format="$,.0f"))
    line = dict(color=BLUE, strokeWidth=2, point=alt.OverlayMarkDef(size=60, color=BLUE))
    c1, c2 = st.columns(2, gap="large")
    c1.altair_chart(alt.Chart(comp).mark_line(**line).encode(
        x=xb, y=alt.Y("Beneficio mediano:Q", title="Beneficio mediano ($)"),
        tooltip=[alt.Tooltip("Bankroll:Q", format="$,.0f"), alt.Tooltip("Beneficio mediano:Q", format="$,.0f"),
                 alt.Tooltip("Beneficio medio:Q", format="$,.0f")]).properties(height=240, title="Beneficio mediano"),
        width="stretch")
    c2.altair_chart(alt.Chart(comp).mark_line(**{**line, "color": ORANGE,
                                                 "point": alt.OverlayMarkDef(size=60, color=ORANGE)}).encode(
        x=xb, y=alt.Y("P(ruina):Q", title="Probabilidad de ruina", axis=alt.Axis(format="%"),
                      scale=alt.Scale(domain=[0, 1])),
        tooltip=[alt.Tooltip("Bankroll:Q", format="$,.0f"), alt.Tooltip("P(ruina):Q", format=".1%")]
    ).properties(height=240, title="Probabilidad de ruina"), width="stretch")


def page_plans():
    st.title("Planes")
    md('<div class="lead">Todas las firmas investigadas con su mejor estrategia. Las recomendadas son las '
                'que combinan rentabilidad, drawdown EOD y reglas que permiten operar así.</div>',
                unsafe_allow_html=True)
    chosen = {s.plan_id for s in CFG.slots}

    def verdict(r):
        p = r.plan
        if p.id in chosen:
            return "✅ recomendada"
        if not p.all_eod:
            return "drawdown intradía"
        if p.p_payout_denial >= 0.3:
            return "prohíbe la estrategia"
        if p.id == "lucid_flex_50k":
            return "peor que la versión con DLL"
        return "menor rentabilidad"

    df = pd.DataFrame([{"Plan": name(r.plan), "Estado": verdict(r), "Precio/intento": r.plan.costs.attempt_price(),
                        "P(pasar)": r.p_pass, "Valor funded": r.value, "EV/intento": r.ev_attempt, "ROI": r.roi}
                       for r in ranked()])
    bar = alt.Chart(df).mark_bar(cornerRadiusEnd=4).encode(
        y=alt.Y("Plan:N", sort=None, title=None),
        x=alt.X("EV/intento:Q", title="Valor esperado por evaluación comprada ($)"),
        color=alt.condition(alt.datum.Estado == "✅ recomendada", alt.value(ORANGE), alt.value(MUTED)),
        tooltip=["Plan", "Estado", alt.Tooltip("EV/intento:Q", format="$,.0f"), alt.Tooltip("ROI:Q", format="+.0%")],
    ).properties(height=30 * len(df) + 10)
    st.altair_chart(bar, width="stretch")
    st.dataframe(df, hide_index=True, width="stretch", column_config={
        **{c: st.column_config.NumberColumn(format="$%.0f") for c in ("Precio/intento", "Valor funded", "EV/intento")},
        "P(pasar)": st.column_config.NumberColumn(format="percent"),
        "ROI": st.column_config.NumberColumn(format="percent")})

    st.subheader("Reglas de las recomendadas")
    for s in CFG.slots:
        p = opt(s.plan_id).plan
        c, e, f, po = p.costs, p.eval, p.funded, p.funded.payout
        with st.expander(name(p)):
            md(f'<span class="tag">{money(c.attempt_price())} por intento</span>'
               f'<span class="tag">activación {money(c.activation_fee)}</span>'
               f'<span class="tag">drawdown {f.drawdown.upper()}</span>', unsafe_allow_html=True)
            left, right = st.columns(2, gap="large")
            with left:
                md("**Evaluación**")
                if e is None:
                    md("- Sin evaluación: directo a funded")
                else:
                    md("\n".join([
                        f"- Objetivo: {money(e.profit_target)}",
                        f"- Pérdida máxima (MLL): {money(e.mll)} {e.drawdown.upper()}",
                        f"- Pérdida diaria (DLL): {money(e.dll)}" if e.dll else "- Pérdida diaria (DLL): no",
                        f"- Consistencia: {e.consistency:.0%}" if e.consistency else "- Consistencia: no",
                        f"- Mínimo de días: {e.min_days}"]))
            with right:
                md("**Funded**")
                caps = " / ".join(money(x) if x != float("inf") else "sin tope" for x in po.max_amount)
                rows = [f"- Pérdida máxima (MLL): {money(f.mll)} {f.drawdown.upper()}",
                        f"- Pérdida diaria (DLL): {money(f.dll)}" if f.dll else "- Pérdida diaria (DLL): no",
                        "- Para cobrar: " + ", ".join(
                            ([f"{po.min_green_days} días de ≥ {money(po.green_min)}"] if po.min_green_days else [])
                            + ([f"colchón de {money(po.buffer)}"] if po.buffer else [])
                            + ([f"+{money(po.min_cycle_profit)} desde el último payout"]
                               if po.min_cycle_profit > 1 else []) or ["sin mínimos"]),
                        f"- Payout: entre {money(po.min_amount)} y {caps}"
                        + (f" (máx. {po.pct_of_profit:.0%} del profit)" if po.pct_of_profit else ""),
                        f"- Split: {po.split:.0%}",
                        f"- Payouts hasta live: {po.max_payouts}" if po.max_payouts else "- Payouts: sin límite"]
                md("\n".join(rows))
            if c.discount:
                caption(f"Precio: {c.discount}")
            if p.notes:
                md("**Notas**")
                md("\n".join(f"- {n}" for n in p.notes))

nav = st.navigation([
    st.Page(page_guide, title="Guía", icon="🧭", default=True),
    st.Page(page_sim, title="Simulación", icon="📈", url_path="simulacion"),
    st.Page(page_plans, title="Planes", icon="📋", url_path="planes"),
])
with st.sidebar:
    caption(f"Supuestos: mercado sin ventaja (edge 0), un trade por cuenta y día (máximo {CFG.trades_per_day} al día), precios con códigos "
               "reutilizables verificados, comisiones incluidas. Los cálculos se guardan en caché.")
nav.run()
