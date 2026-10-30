import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

# ---------------------------------------------------------------
# 1. CONFIGURACIÓN
# ---------------------------------------------------------------
st.set_page_config(page_title="Panel Comercial", layout="wide")

URL_DATOS = "https://raw.githubusercontent.com/SixChain/panel-ventas/main/data/ventas.csv"
# Para saber cuándo Power Automate actualizó el archivo por última vez
URL_ULTIMO_CAMBIO = "https://api.github.com/repos/SixChain/panel-ventas/commits?path=data/ventas.csv&per_page=1"

MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO",
         "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]

# Colores de marca Consorcio Líder (negro y dorado)
# y colores con significado (Unidad 5: "el color es un comunicador")
NEGRO = "#0B0B0B"         # fondo
TARJETA = "#141414"       # fondo de tarjetas y filtros
TEXTO = "#F2E9D0"         # texto principal (crema)
TEXTO_SUAVE = "#B5B5B5"   # textos secundarios
DORADO = "#C9A24B"        # dato principal / año actual
GRIS = "#6B6B6B"          # contexto / año anterior
VERDE = "#3FB950"         # mejora (siempre con ▲)
NARANJA = "#FF7A45"       # alerta / caída (siempre con ▼)

# Refuerzo del fondo negro, por si el config.toml no se carga
st.markdown(
    f"""
    <style>
    .stApp {{ background-color: {NEGRO}; color: {TEXTO}; }}
    section[data-testid="stSidebar"] {{ background-color: {TARJETA}; }}
    h1, h2, h3 {{ color: {TEXTO}; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------
# 2. CARGA DE DATOS (se lee directo de GitHub)
# ---------------------------------------------------------------
@st.cache_data(ttl=600)
def cargar_datos():
    df = pd.read_csv(URL_DATOS)
    df["mes_num"] = df["mes"].map({m: i + 1 for i, m in enumerate(MESES)})
    df["nombre_vendedor"] = df["nombre_vendedor"].str.strip().str.title()
    return df


@st.cache_data(ttl=600)
def fecha_ultima_actualizacion():
    """Pregunta a GitHub la fecha del último commit de ventas.csv (el que hace Power Automate)."""
    try:
        r = requests.get(URL_ULTIMO_CAMBIO, timeout=5)
        fecha = pd.to_datetime(r.json()[0]["commit"]["committer"]["date"])
        return fecha.tz_convert("America/Bogota").strftime("%d/%m/%Y %I:%M %p")
    except Exception:
        return "no disponible"


df_completo = cargar_datos()


# ---------------------------------------------------------------
# 3. FILTROS (barra lateral) Y PERÍODO DE COMPARACIÓN
# ---------------------------------------------------------------
st.sidebar.header("Filtros")

# Pesos o unidades: cambia TODOS los gráficos con un solo clic
ver_en = st.sidebar.radio("Ver gráficos en", ["Pesos", "Unidades"], horizontal=True)
MEDIDA = "valor_cop" if ver_en == "Pesos" else "unidades_convertidas_750"
UNIDAD = "millones COP" if ver_en == "Pesos" else "unidades (eq. 750 ml)"
TITULO_EJE = "Millones COP" if ver_en == "Pesos" else "Unidades (eq. 750 ml)"
DIVISOR = 1e6 if ver_en == "Pesos" else 1

anios = sorted(df_completo["anio"].unique(), reverse=True)[:-1]  # el primer año no tiene con qué compararse
anio_actual = st.sidebar.selectbox("Año a analizar", anios)

grupos = ["Todos"] + sorted(df_completo["descripcion_grupo_producto"].unique())
sel_grupo = st.sidebar.selectbox("Grupo de producto", grupos)

# Marcas: solo las del grupo elegido. Puedes elegir varias (por ejemplo, todas las ONIX)
base_marcas = df_completo if sel_grupo == "Todos" else df_completo[df_completo["descripcion_grupo_producto"] == sel_grupo]
sel_marcas = st.sidebar.multiselect("Marca", sorted(base_marcas["marca_producto"].unique()),
                                    placeholder="Todas las marcas")

vendedores = ["Todos"] + sorted(df_completo["nombre_vendedor"].unique())
sel_vendedor = st.sidebar.selectbox("Vendedor", vendedores)

df = df_completo.copy()
if sel_grupo != "Todos":
    df = df[df["descripcion_grupo_producto"] == sel_grupo]
if sel_marcas:
    df = df[df["marca_producto"].isin(sel_marcas)]
if sel_vendedor != "Todos":
    df = df[df["nombre_vendedor"] == sel_vendedor]

if df.empty:
    st.warning("Con estos filtros no hay datos. Cambia la selección.")
    st.stop()

# Año elegido vs. los MISMOS meses del año anterior
anio_anterior = anio_actual - 1
ultimo_mes = df_completo.loc[df_completo["anio"] == anio_actual, "mes_num"].max()

actual = df[(df["anio"] == anio_actual) & (df["mes_num"] <= ultimo_mes)]
anterior = df[(df["anio"] == anio_anterior) & (df["mes_num"] <= ultimo_mes)]

periodo = f"Enero – {MESES[ultimo_mes - 1].capitalize()}"

# Si se eligieron marcas, el detalle baja de "marca" a "producto"
DETALLE = "descripcion_producto" if sel_marcas else "marca_producto"
NOMBRE_DETALLE = "producto" if sel_marcas else "marca"
ART = "el" if sel_marcas else "la"   # "el producto" / "la marca"

# Si las ventas son pequeñas (por ejemplo, Cremas), los gráficos en pesos pasan a "miles"
if ver_en == "Pesos" and df.groupby(["anio", "mes_num"])["valor_cop"].sum().max() < 1e6:
    UNIDAD, TITULO_EJE, DIVISOR = "miles COP", "Miles COP", 1e3


def pesos(valor):
    """Plata en formato corto: $1.276 M, $1,1 M o $172 mil."""
    if abs(valor) >= 1e7:
        return f"${valor / 1e6:,.0f} M".replace(",", ".")
    if abs(valor) >= 1e6:
        return f"${valor / 1e6:.1f} M".replace(".", ",")
    return f"${valor / 1e3:,.0f} mil".replace(",", ".")


def fmt(valor):
    """Escribe un valor según la medida elegida: $1.276 M o 26.561 und."""
    if ver_en == "Pesos":
        return pesos(valor)
    return f"{valor:,.0f} und.".replace(",", ".")


# ---------------------------------------------------------------
# 4. CÁLCULO DE LOS 4 KPIs
# ---------------------------------------------------------------
def calcular_kpis(datos):
    ventas = datos["valor_cop"].sum()
    unidades = datos["unidades_convertidas_750"].sum()
    clientes = datos["nit"].nunique()
    promedio = ventas / clientes if clientes else 0
    return ventas, unidades, clientes, promedio


v_act, u_act, c_act, p_act = calcular_kpis(actual)
v_ant, u_ant, c_ant, p_ant = calcular_kpis(anterior)


def variacion(nuevo, viejo):
    return (nuevo - viejo) / viejo * 100 if viejo else 0


# Formatos en estilo colombiano: punto para miles
def miles(n):
    return f"{n:,.0f}".replace(",", ".")


def millones(n):
    return pesos(n)


# ---------------------------------------------------------------
# 5. TARJETA DE KPI (verde si mejora, naranja si empeora)
# ---------------------------------------------------------------
def tarjeta_kpi(titulo, valor, cambio, referencia):
    if cambio >= 0.5:
        color, flecha = VERDE, "▲"
    elif cambio <= -0.5:
        color, flecha = NARANJA, "▼"
    else:
        color, flecha = GRIS, "●"
    st.markdown(
        f"""
        <div translate="no" class="notranslate" style="background:{TARJETA}; border:1px solid #2a2a2a; border-top:3px solid {DORADO};
                    border-radius:10px; padding:16px 18px;">
            <div style="font-size:14px; color:{TEXTO_SUAVE};">{titulo}</div>
            <div style="font-size:32px; font-weight:700; color:{TEXTO}; margin:4px 0;">{valor}</div>
            <div style="font-size:14px; color:{color}; font-weight:600;">
                {flecha} {cambio:+.0f}% <span style="color:{TEXTO_SUAVE}; font-weight:400;">vs. {referencia}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------
# 6. ENCABEZADO Y KPIs (lo más importante, siempre arriba)
# ---------------------------------------------------------------
st.markdown(f"<h1 style='margin-bottom:0'>Panel Comercial · <span style='color:{DORADO}'>Consorcio Líder</span></h1>", unsafe_allow_html=True)
st.caption(f"Período analizado: {periodo} {anio_actual}, comparado con el mismo período de {anio_anterior}"
           f"  ·  Última actualización de los datos: {fecha_ultima_actualizacion()}")

col1, col2, col3, col4 = st.columns(4)
with col1:
    tarjeta_kpi("Ventas", millones(v_act), variacion(v_act, v_ant), millones(v_ant))
with col2:
    tarjeta_kpi("Unidades (eq. 750 ml)", miles(u_act), variacion(u_act, u_ant), miles(u_ant))
with col3:
    tarjeta_kpi("Clientes activos", miles(c_act), variacion(c_act, c_ant), miles(c_ant))
with col4:
    tarjeta_kpi("Venta promedio por cliente", pesos(p_act), variacion(p_act, p_ant), pesos(p_ant))


# ---------------------------------------------------------------
# 7. FUNCIONES DE APOYO PARA GRÁFICOS Y TARJETAS
# ---------------------------------------------------------------
def estilo_grafico(fig, alto=380):
    """Mismo estilo para todos los gráficos (Pilar 2: consistencia)."""
    fig.update_layout(
        height=alto,
        paper_bgcolor=TARJETA,
        plot_bgcolor=TARJETA,
        font=dict(color=TEXTO, size=13),
        margin=dict(l=10, r=20, t=10, b=10),
        legend=dict(orientation="h", y=1.08, x=0, bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor=NEGRO, font_color=TEXTO),
    )
    fig.update_xaxes(showgrid=False, color=TEXTO_SUAVE)
    fig.update_yaxes(gridcolor="#2a2a2a", color=TEXTO_SUAVE, zeroline=False)
    return fig


def barras_cambio(cambio, alto=380):
    """Barras horizontales: verde si subió, naranja si bajó (en la medida elegida)."""
    fig = go.Figure(go.Bar(
        x=cambio.values, y=cambio.index, orientation="h",
        marker_color=[VERDE if v > 0 else NARANJA for v in cambio.values],
        text=[("▲ " if v > 0 else "▼ ") + fmt(abs(v) * DIVISOR) for v in cambio.values],
        textposition="outside", cliponaxis=False,
        hovertemplate="%{y}: %{x:+,.0f}<extra></extra>",
    ))
    margen = cambio.abs().max() * 0.45
    fig.update_xaxes(title_text=TITULO_EJE, zeroline=True, zerolinecolor=TEXTO_SUAVE,
                     range=[min(cambio.min(), 0) - margen, max(cambio.max(), 0) + margen])
    fig.update_yaxes(ticksuffix="  ")
    return estilo_grafico(fig, alto)


def cambio_por(columna, medida=None):
    """Diferencia (año actual - año anterior) por categoría, en la unidad del gráfico."""
    medida = medida or MEDIDA
    a = actual.groupby(columna)[medida].sum()
    b = anterior.groupby(columna)[medida].sum()
    return a.sub(b, fill_value=0) / DIVISOR


def tarjeta_historia(numero, titulo, contenido, destacada=False):
    borde = NARANJA if destacada else DORADO
    st.markdown(
        f"""
        <div translate="no" class="notranslate" style="background:{TARJETA}; border:1px solid #2a2a2a;
             border-left:4px solid {borde}; border-radius:10px; padding:16px 18px; height:100%;">
            <div style="font-size:13px; color:{borde}; font-weight:700;">{numero}. {titulo}</div>
            <div style="font-size:15px; color:{TEXTO}; margin-top:8px; line-height:1.5;">{contenido}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def m(valor_millones):
    """Recibe millones y los escribe en formato corto (sin signo): 1276 -> $1.276 M"""
    return pesos(abs(valor_millones) * 1e6)


nombres_mes = [mes[:3].capitalize() for mes in MESES]

# ---------------------------------------------------------------
# 8. PESTAÑAS: cada una responde UNA pregunta
# ---------------------------------------------------------------
st.write("")
tab_resumen, tab_clientes, tab_vendedores, tab_productos = st.tabs(
    ["Resumen", "Clientes", "Vendedores", "Productos"])

# ===============================================================
# PESTAÑA RESUMEN: ¿Cómo vamos y qué hacemos?
# ===============================================================
with tab_resumen:
    izq, der = st.columns([3, 2])

    # --- Tendencia mensual: año actual (dorado) vs. año anterior (gris) ---
    with izq:
        st.subheader("¿Cómo van las ventas mes a mes?")
        st.caption(f"Ventas mensuales en {UNIDAD} · {anio_actual} vs. {anio_anterior}")

        # Todos los meses aparecen, aunque en alguno no se haya vendido (queda en cero)
        mensual_ant = (df[df["anio"] == anio_anterior].groupby("mes_num")[MEDIDA].sum() / DIVISOR
                       ).reindex(range(1, 13), fill_value=0)
        mensual_act = (actual.groupby("mes_num")[MEDIDA].sum() / DIVISOR
                       ).reindex(range(1, ultimo_mes + 1), fill_value=0)

        fig_linea = go.Figure()
        for serie, anio, color, ancho in [(mensual_ant, anio_anterior, GRIS, 2),
                                          (mensual_act, anio_actual, DORADO, 3)]:
            fig_linea.add_trace(go.Scatter(
                x=[nombres_mes[i - 1] for i in serie.index], y=serie.values,
                name=str(anio), mode="lines+markers",
                line=dict(color=color, width=ancho), marker=dict(size=7 + ancho - 2),
                hovertemplate="%{x}: %{y:,.0f}<extra>" + str(anio) + "</extra>",
            ))
        fig_linea.update_yaxes(title_text=TITULO_EJE)
        st.plotly_chart(estilo_grafico(fig_linea), width="stretch")

    # --- ¿Dónde ganamos y dónde perdemos? Variación por marca ---
    with der:
        st.subheader("¿Dónde ganamos y dónde perdemos?")
        st.caption(f"Cambio por {NOMBRE_DETALLE} en {UNIDAD} · {periodo} {anio_actual} vs. {anio_anterior}")
        cambio_marca = cambio_por(DETALLE).sort_values()
        # Sin cambios diminutos (menos del 2% del cambio más grande)
        cambio_marca = cambio_marca[cambio_marca.abs() >= cambio_marca.abs().max() * 0.02]
        st.plotly_chart(barras_cambio(cambio_marca), width="stretch")

    # --- Storytelling (siempre en pesos: es la plata lo que le importa al director) ---
    marca_pesos = (actual.groupby(DETALLE)["valor_cop"].sum()
                   .sub(anterior.groupby(DETALLE)["valor_cop"].sum(), fill_value=0) / 1e6).sort_values()
    pocos_datos = c_act < 10 or c_ant < 10 or len(marca_pesos) < 2
    if not pocos_datos:
        marca_pierde, valor_pierde = marca_pesos.index[0], marca_pesos.iloc[0]
        marca_gana, valor_gana = marca_pesos.index[-1], marca_pesos.iloc[-1]

        mes_act = actual.groupby("mes_num")["valor_cop"].sum()
        mes_ant = anterior.groupby("mes_num")["valor_cop"].sum()
        mes_peor = (mes_act - mes_ant.reindex(mes_act.index, fill_value=0)).idxmin()

        cli_act = actual.groupby("nombre")["valor_cop"].sum()
        cli_ant = anterior.groupby("nombre")["valor_cop"].sum()
        cambio_cli = (cli_act.reindex(cli_ant.index, fill_value=0) - cli_ant) / 1e6
        cambio_cli = cambio_cli.drop("CONSUMIDOR FINAL", errors="ignore").sort_values().head(5)
        perdida_top5 = -cambio_cli.sum()
        caida_total = (v_ant - v_act) / 1e6
        lista_clientes = "".join(
            f"<li>{nombre.title()}: <b style='color:{NARANJA}'>▼ {m(v)}</b></li>"
            for nombre, v in cambio_cli.items()
        )

    st.write("")
    st.subheader("¿Qué nos dicen los datos y qué hacemos?")
    if pocos_datos:
        st.info(f"Con estos filtros hay muy pocos datos ({c_act} cliente(s) en {anio_actual}) para sacar "
                "conclusiones. Amplía la selección para ver la recomendación.")
    else:
        h1, h2, h3, h4 = st.columns(4)
        with h1:
            verbo = "cayeron" if v_act < v_ant else "crecieron"
            tarjeta_historia(1, "SITUACIÓN · ¿Qué ocurrió?",
                f"Las ventas de {periodo.lower()} {anio_actual} {verbo} "
                f"<b style='color:{NARANJA if v_act < v_ant else VERDE}'>{abs(variacion(v_act, v_ant)):.0f}%</b> "
                f"frente a {anio_anterior}. El mes más afectado fue <b>{MESES[mes_peor - 1].capitalize()}</b>.")
        with h2:
            tarjeta_historia(2, "EXPLICACIÓN · ¿Por qué?",
                f"Clientes activos: {variacion(c_act, c_ant):+.0f}%. Venta por cliente: "
                f"<b>{variacion(p_act, p_ant):+.0f}%</b>. {ART.capitalize()} {NOMBRE_DETALLE} que más perdió fue <b>{marca_pierde.title()}</b> "
                f"({m(valor_pierde)}) y {ART} que más ganó, <b>{marca_gana.title()}</b> ({m(valor_gana)}).")
        with h3:
            tarjeta_historia(3, "EVIDENCIA · Clientes que más bajaron",
                f"<ul style='margin:0; padding-left:18px; font-size:14px;'>{lista_clientes}</ul>"
                f"<div style='font-size:13px; color:{TEXTO_SUAVE}; margin-top:6px;'>Entre los 5 dejaron de comprar "
                f"{m(perdida_top5)}. {'Caída' if caida_total > 0 else 'Crecimiento'} total con estos filtros: "
                f"{m(caida_total)}.</div>")
        with h4:
            tarjeta_historia(4, "ACCIÓN · ¿Qué hacer?",
                f"<b>1.</b> Visitar esta semana a los 5 clientes que más bajaron y entender por qué.<br>"
                f"<b>2.</b> Revisar precio y disponibilidad de <b>{marca_pierde.title()}</b>.<br>"
                f"<b>3.</b> Aprovechar el impulso de <b>{marca_gana.title()}</b> en esos mismos clientes.",
                destacada=True)

    # Las otras pestañas las construimos en los siguientes pasos
# ===============================================================
# PESTAÑA CLIENTES: ¿A qué clientes debemos ir a buscar?
# ===============================================================
with tab_clientes:
    hay_clientes = (~df["nombre"].str.contains("CONSUMIDOR", na=False)).any() and c_ant > 0
    if not hay_clientes:
        st.info("No hay suficientes clientes con estos filtros para este análisis.")
    else:
        # Sin cuentas genéricas como "CONSUMIDOR FINAL"
        reales = df[~df["nombre"].str.contains("CONSUMIDOR", na=False)].copy()
        reales["mes_abs"] = reales["anio"] * 12 + reales["mes_num"]       # mes como número continuo
        mes_corte = anio_actual * 12 + ultimo_mes                          # último mes analizado
        reales = reales[reales["mes_abs"] <= mes_corte]

        # --- Estado de cada cliente según su última compra ---
        cartera = reales.groupby("nit").agg(
            Cliente=("nombre", "first"),
            ultima=("mes_abs", "max"),
            venta_historica=("valor_cop", "sum"),
            unidades_historicas=("unidades_convertidas_750", "sum"),
        )
        cartera["Meses sin comprar"] = mes_corte - cartera["ultima"]
        cartera["Estado"] = pd.cut(cartera["Meses sin comprar"], bins=[-1, 1, 12, 1000],
                                   labels=["Activos", "En riesgo", "Perdidos"]).astype(str)
        conteo = cartera["Estado"].value_counts().reindex(["Activos", "En riesgo", "Perdidos"], fill_value=0)

        # 1) Estado de la cartera: UNA barra apilada (en vez de la dona)
        st.subheader("¿Cómo está nuestra cartera de clientes?")
        st.caption("Según la última compra: Activos (compraron este mes o el anterior), En riesgo (de 2 a 12 meses "
                   "sin comprar), Perdidos (más de 12 meses sin comprar).")
        fig_cartera = go.Figure()
        for estado, color in [("Activos", VERDE), ("En riesgo", NARANJA), ("Perdidos", GRIS)]:
            n = int(conteo[estado])
            fig_cartera.add_trace(go.Bar(
                x=[n], y=["Clientes"], orientation="h", name=estado, marker_color=color,
                marker_line=dict(color=TARJETA, width=2),
                text=f"{estado}: {n:,} ({n / conteo.sum() * 100:.0f}%)".replace(",", "."),
                textposition="inside", insidetextanchor="middle", textfont=dict(color=NEGRO, size=14),
                hovertemplate=f"{estado}: %{{x:,}} clientes<extra></extra>",
            ))
        fig_cartera.update_layout(barmode="stack", showlegend=False)
        fig_cartera.update_xaxes(visible=False)
        fig_cartera.update_yaxes(visible=False)
        st.plotly_chart(estilo_grafico(fig_cartera, alto=110), width="stretch")

        izq_c, der_c = st.columns([3, 2])

        # 2) Los 10 clientes más grandes: este año vs. el anterior
        with izq_c:
            st.subheader("¿Cómo les va a nuestros 10 clientes más grandes?")
            reales_act = actual[~actual["nombre"].str.contains("CONSUMIDOR", na=False)]
            reales_ant = anterior[~anterior["nombre"].str.contains("CONSUMIDOR", na=False)]
            comp = pd.DataFrame({
                str(anio_anterior): reales_ant.groupby("nombre")[MEDIDA].sum(),
                str(anio_actual): reales_act.groupby("nombre")[MEDIDA].sum(),
            }).fillna(0)
            # Los 10 más grandes en CUALQUIERA de los dos años (así aparecen también los clientes nuevos)
            comp = comp.loc[comp.max(axis=1).nlargest(10).index]
            grandes = comp.index

            # Escala propia: si son valores pequeños (p. ej. Brandy), se muestran en miles
            div_c, eje_c = DIVISOR, TITULO_EJE
            if ver_en == "Pesos" and comp.to_numpy().max() < 1e6:
                div_c, eje_c = 1e3, "Miles COP"
            comp = comp / div_c
            st.caption(f"Los 10 que más compraron en {anio_anterior} o {anio_actual}, en {eje_c.lower()} · {periodo} · "
                       f"{anio_actual} (dorado) vs. {anio_anterior} (gris)")
            nombre_corto = {n.title()[:32]: n for n in comp.index}  # para saber a quién le hicieron clic
            comp.index = [n.title()[:32] for n in comp.index]  # nombres cortos para que se lean

            # Barras agrupadas: gris = año anterior, dorado = año actual.
            # Ordenadas de mayor a menor según lo que compran en el año actual.
            ya, yb = str(anio_anterior), str(anio_actual)
            comp = comp.sort_values([yb, ya], ascending=False)
            fig_top = go.Figure()
            for anio, color in [(ya, GRIS), (yb, DORADO)]:
                fig_top.add_trace(go.Bar(
                    x=comp[anio], y=comp.index, orientation="h", name=anio, marker_color=color,
                    hovertemplate="%{y}: %{x:,.0f}<extra>" + anio + "</extra>",
                ))
            fig_top.update_layout(barmode="group", bargap=0.25, margin=dict(t=40))
            # autorange="reversed": el primero de la lista (el que más compra) queda ARRIBA
            fig_top.update_yaxes(autorange="reversed", ticksuffix="  ")
            fig_top.update_xaxes(title_text=eje_c)
            # on_select: al hacer clic en un punto, Streamlit nos dice qué cliente se eligió
            clic = st.plotly_chart(estilo_grafico(fig_top, alto=max(240, 50 * len(comp) + 90)),
                                   width="stretch", on_select="rerun",
                                   selection_mode="points", key="grafico_top_clientes")
            st.caption("Ordenados de mayor a menor compra en " + yb + ". 👆 Haz clic en una barra para ver la historia del cliente.")

        # 3) Historia de un cliente
        with der_c:
            st.subheader("Historia de un cliente")
            nombres = list(grandes)
            nombres += sorted(set(reales["nombre"]) - set(nombres))

            # Si hicieron clic en una barra NUEVA, ese cliente pasa a la lista de selección
            puntos = clic.selection.points if clic and clic.selection else []
            if puntos:
                clic_cliente = nombre_corto.get(puntos[0]["y"])
                if clic_cliente and clic_cliente != st.session_state.get("ultimo_clic"):
                    st.session_state["ultimo_clic"] = clic_cliente
                    st.session_state["cliente_elegido"] = clic_cliente
            if st.session_state.get("cliente_elegido") not in nombres:
                st.session_state["cliente_elegido"] = nombres[0]

            elegido = st.selectbox("Elige un cliente (o haz clic en una barra)", nombres,
                                   format_func=str.title, key="cliente_elegido")
            datos_cli = reales[reales["nombre"] == elegido]
            # Todos los meses, también en los que no compró (aparecen en cero)
            meses = range(int(datos_cli["mes_abs"].min()), mes_corte + 1)
            hist_cli = datos_cli.groupby("mes_abs")[MEDIDA].sum().reindex(meses, fill_value=0)
            div_h, eje_h = (1e3, "Miles COP") if ver_en == "Pesos" and hist_cli.max() < 1e6 else (DIVISOR, TITULO_EJE)
            hist_cli = hist_cli / div_h
            etiquetas = [f"{nombres_mes[(i - 1) % 12]} {(i - 1) // 12}" for i in hist_cli.index]

            fig_cli = go.Figure(go.Scatter(
                x=etiquetas, y=hist_cli.values, mode="lines+markers",
                line=dict(color=DORADO, width=2), marker=dict(size=7),
                hovertemplate="%{x}: %{y:,.0f}<extra></extra>",
            ))
            fig_cli.update_yaxes(title_text=eje_h)
            st.plotly_chart(estilo_grafico(fig_cli, alto=300), width="stretch")
            meses_sin = int(mes_corte - datos_cli["mes_abs"].max())
            st.caption(f"Última compra hace {meses_sin} mes(es) · Compras en {datos_cli['mes_abs'].nunique()} meses distintos")

        # 4) Detalle al final y plegado (para el que quiera bajar a la lista)
        with st.expander(f"Ver la lista de clientes en riesgo ({int(conteo['En riesgo']):,})".replace(",", ".")):
            rango = st.slider("Meses sin comprar (entre)", 1, 24, (2, 12))
            lista = cartera[cartera["Meses sin comprar"].between(*rango)].sort_values("venta_historica", ascending=False)
            tabla = pd.DataFrame({
                "Cliente": lista["Cliente"].str.title(),
                "Meses sin comprar": lista["Meses sin comprar"],
                "Venta histórica (millones COP)": (lista["venta_historica"] / 1e6).round(1),
                "Unidades históricas (eq. 750 ml)": lista["unidades_historicas"].round(0).astype(int),
            })
            st.dataframe(tabla, height=300, hide_index=True, width="stretch")
            st.download_button("Descargar la lista (se abre en Excel)",
                               tabla.to_csv(index=False, sep=";").encode("utf-8-sig"),
                               file_name="clientes_en_riesgo.csv", mime="text/csv")

# ===============================================================
# PESTAÑA VENDEDORES: ¿Qué vendedores necesitan apoyo?
# ===============================================================
with tab_vendedores:
    # La oficina (código 1) y los promocionales (código 17) no son personas: no entran al ranking
    NO_VENDEDORES = [1, 17]
    ven_act = actual[~actual["codigo_vendedor"].isin(NO_VENDEDORES)]
    ven_ant = anterior[~anterior["codigo_vendedor"].isin(NO_VENDEDORES)]

    if ven_act.empty and ven_ant.empty:
        st.info("Con estos filtros no hay ventas de vendedores (solo de la oficina o de promocionales).")
    else:
        pct_oficina = actual.loc[actual["codigo_vendedor"] == 1, "valor_cop"].sum() / v_act * 100 if v_act else 0
        st.caption(f"No se incluyen la Oficina ni Promocionales. La Oficina hizo el {pct_oficina:.0f}% "
                   f"de la venta de {periodo.lower()} {anio_actual}.")

        # --- Clientes en riesgo de cada vendedor (2 a 12 meses sin comprarle) ---
        hist_v = df[~df["codigo_vendedor"].isin(NO_VENDEDORES) & ~df["nombre"].str.contains("CONSUMIDOR", na=False)]
        hist_v = hist_v.assign(mes_abs=hist_v["anio"] * 12 + hist_v["mes_num"])
        hist_v = hist_v[hist_v["mes_abs"] <= anio_actual * 12 + ultimo_mes]
        ultima_v = hist_v.groupby(["nombre_vendedor", "nit"])["mes_abs"].max()
        sin_comprar = anio_actual * 12 + ultimo_mes - ultima_v
        riesgo_v = sin_comprar[sin_comprar.between(2, 12)].groupby(level=0).size()

        izq_v, der_v = st.columns(2)

        # 1) ¿Quién sube y quién baja?
        with izq_v:
            st.subheader("¿Quién sube y quién baja?")
            st.caption(f"Cambio por vendedor en {UNIDAD} · {periodo} {anio_actual} vs. {anio_anterior}")
            cambio_v = (ven_act.groupby("nombre_vendedor")[MEDIDA].sum()
                        .sub(ven_ant.groupby("nombre_vendedor")[MEDIDA].sum(), fill_value=0) / DIVISOR).sort_values()
            st.plotly_chart(barras_cambio(cambio_v, alto=max(220, 34 * len(cambio_v) + 100)),
                            width="stretch")

        # 2) ¿Quién tiene más clientes por recuperar?
        with der_v:
            st.subheader("¿Quién tiene más clientes por recuperar?")
            st.caption("Clientes que llevan de 2 a 12 meses sin comprarle a cada vendedor")
            riesgo_orden = riesgo_v.sort_values()
            fig_riesgo = go.Figure(go.Bar(
                x=riesgo_orden.values, y=riesgo_orden.index, orientation="h",
                marker_color=NARANJA, text=[f"{n:,}".replace(",", ".") for n in riesgo_orden.values],
                textposition="outside", cliponaxis=False,
                hovertemplate="%{y}: %{x} clientes en riesgo<extra></extra>",
            ))
            fig_riesgo.update_xaxes(title_text="Clientes en riesgo", range=[0, riesgo_orden.max() * 1.25 if len(riesgo_orden) else 1])
            fig_riesgo.update_yaxes(ticksuffix="  ")
            st.plotly_chart(estilo_grafico(fig_riesgo, alto=max(220, 34 * len(riesgo_orden) + 100)),
                            width="stretch")

        # 3) Tabla resumen al final y plegada
        with st.expander("Ver la tabla resumen por vendedor"):
            resumen = ven_act.groupby("nombre_vendedor").agg(
                venta=("valor_cop", "sum"), unidades=("unidades_convertidas_750", "sum"), clientes=("nit", "nunique"))
            venta_ant_v = ven_ant.groupby("nombre_vendedor")["valor_cop"].sum()
            tabla_v = pd.DataFrame({
                "Vendedor": resumen.index,
                f"Venta {anio_actual} (millones COP)": (resumen["venta"] / 1e6).round(1).values,
                "Cambio vs. año anterior": [f"{variacion(v, venta_ant_v.get(n, 0)):+.0f}%"
                                            for n, v in resumen["venta"].items()],
                "Unidades (eq. 750 ml)": resumen["unidades"].round(0).astype(int).values,
                "Clientes atendidos": resumen["clientes"].values,
                "Clientes en riesgo": riesgo_v.reindex(resumen.index, fill_value=0).values,
            }).sort_values(f"Venta {anio_actual} (millones COP)", ascending=False)
            st.dataframe(tabla_v, hide_index=True, width="stretch")
# ===============================================================
# PESTAÑA PRODUCTOS: ¿Qué productos y presentaciones impulsar?
# ===============================================================
with tab_productos:
    izq_p, der_p = st.columns([3, 2])

    # 1) Los 10 productos más vendidos: año actual (dorado) vs. anterior (gris)
    with izq_p:
        st.subheader("¿Cuáles son nuestros productos estrella?")
        prod = pd.DataFrame({
            str(anio_anterior): anterior.groupby("descripcion_producto")[MEDIDA].sum(),
            str(anio_actual): actual.groupby("descripcion_producto")[MEDIDA].sum(),
        }).fillna(0)
        prod = prod.loc[prod.max(axis=1).nlargest(10).index]
        div_p, eje_p = (1e3, "Miles COP") if ver_en == "Pesos" and prod.to_numpy().max() < 1e6 else (DIVISOR, TITULO_EJE)
        prod = prod / div_p
        st.caption(f"Los 10 más vendidos en {anio_anterior} o {anio_actual} · {eje_p} · "
                   f"{periodo} {anio_actual} (dorado) vs. {anio_anterior} (gris)")
        prod.index = [p.title()[:38] for p in prod.index]

        fig_prod = go.Figure()
        for anio, color in [(str(anio_anterior), GRIS), (str(anio_actual), DORADO)]:
            fig_prod.add_trace(go.Bar(
                x=prod[anio], y=prod.index, orientation="h", name=anio, marker_color=color,
                hovertemplate="%{y}: %{x:,.0f}<extra>" + anio + "</extra>",
            ))
        fig_prod.update_layout(barmode="group", bargap=0.25, margin=dict(t=40))
        fig_prod.update_yaxes(autorange="reversed", ticksuffix="  ")
        fig_prod.update_xaxes(title_text=eje_p)
        st.plotly_chart(estilo_grafico(fig_prod, alto=max(220, 34 * len(prod) + 120)), width="stretch")

    # 2) ¿Qué tamaños prefieren? Botellas reales vendidas por presentación (% del total)
    with der_p:
        st.subheader("¿Qué tamaños prefieren los clientes?")
        st.caption("Porcentaje de botellas vendidas según el tamaño · mismo período de cada año")

        def tamano(cc):
            return "1 litro o más" if cc >= 1000 else f"{cc} ml"

        orden_tam = ["175 ml", "375 ml", "750 ml", "1 litro o más"]
        tonos = {"175 ml": "#E3C779", "375 ml": "#C9A24B", "750 ml": "#8C6D2F", "1 litro o más": "#5C4720"}
        fig_tam = go.Figure()
        anios_tam = [str(anio_anterior), str(anio_actual)]
        partes = {}
        for anio, datos in zip(anios_tam, [anterior, actual]):
            botellas = datos.groupby(datos["cantidad_cc_producto"].map(tamano))["unidades_vendidas"].sum()
            partes[anio] = (botellas / botellas.sum() * 100).reindex(orden_tam, fill_value=0) if botellas.sum() else None
        for t in orden_tam:
            valores = [partes[a][t] if partes[a] is not None else 0 for a in anios_tam]
            fig_tam.add_trace(go.Bar(
                x=valores, y=anios_tam, orientation="h", name=t, marker_color=tonos[t],
                marker_line=dict(color=TARJETA, width=2),
                text=[f"{v:.0f}%" if v >= 4 else "" for v in valores], textposition="inside",
                insidetextanchor="middle",
                textfont=dict(color=NEGRO if t in ("175 ml", "375 ml") else TEXTO),
                hovertemplate=t + ": %{x:.1f}%<extra>%{y}</extra>",
            ))
        fig_tam.update_layout(barmode="stack", legend=dict(traceorder="normal"))
        fig_tam.update_xaxes(range=[0, 100], ticksuffix="%")
        fig_tam.update_yaxes(ticksuffix="  ")
        st.plotly_chart(estilo_grafico(fig_tam, alto=250), width="stretch")

        # Precio promedio por botella (equivalente 750 ml): ¿estamos vendiendo más barato?
        precio_act = v_act / u_act if u_act else 0
        precio_ant = v_ant / u_ant if u_ant else 0
        tarjeta_kpi("Precio promedio por botella (eq. 750 ml)", pesos(precio_act),
                    variacion(precio_act, precio_ant), pesos(precio_ant))

    # 3) Tabla de productos al final y plegada
    with st.expander("Ver la tabla de todos los productos"):
        ra = actual.groupby("descripcion_producto").agg(venta=("valor_cop", "sum"),
                                                       unidades=("unidades_convertidas_750", "sum"))
        rb = anterior.groupby("descripcion_producto")["valor_cop"].sum()
        tabla_p = pd.DataFrame({
            "Producto": ra.index.str.title(),
            f"Venta {anio_actual} (millones COP)": (ra["venta"] / 1e6).round(1).values,
            "Cambio vs. año anterior": [f"{variacion(v, rb.get(n, 0)):+.0f}%" if rb.get(n, 0) else "Nuevo"
                                        for n, v in ra["venta"].items()],
            "Unidades (eq. 750 ml)": ra["unidades"].round(0).astype(int).values,
            "Precio prom. por botella (eq. 750 ml)": [pesos(v / u) if u else "-" for v, u in zip(ra["venta"], ra["unidades"])],
        }).sort_values(f"Venta {anio_actual} (millones COP)", ascending=False)
        st.dataframe(tabla_p, hide_index=True, width="stretch")

# ---------------------------------------------------------------
# PIE DE PÁGINA: fuente de datos documentada
# ---------------------------------------------------------------
st.divider()
st.caption("Fuente de datos: ventas.csv generado por el flujo automático de Power Automate y publicado en "
           "GitHub (SixChain/panel-ventas). Valores en pesos colombianos (COP). Unidades convertidas a "
           "botellas equivalentes de 750 ml. Incluye devoluciones (valores negativos).")