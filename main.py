"""
app.py — Dashboard de revisión de órdenes de compra, Barrio Pizza.

Corre con: streamlit run app.py
"""

from pathlib import Path
import os
import time

import pandas as pd
import streamlit as st
from google import genai
from google.genai import types
from dotenv import dotenv_values

import logic

st.set_page_config(
    page_title="Barrio Pizza — Alertas de compras",
    page_icon="🍕",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Estilos mínimos para acercarse al diseño de Figma
# (colores por tipo de alerta, tarjetas KPI, etc.)
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
        /* Ocultar el menú hamburguesa y el botón de Deploy, pero SIN
           eliminar la barra superior entera -- ahí vive el botón para
           volver a abrir el sidebar si lo cerrás, y si lo tapamos del
           todo, ese botón desaparece y no hay forma de reabrirlo. */
        #MainMenu {
            visibility: hidden;
        }
        .stAppDeployButton {
            display: none;
        }
        header[data-testid="stHeader"] {
            background: transparent;
            height: auto;
        }
        /* Recuperar el espacio que dejaba la barra al no tener contenido visible */
        .block-container {
            padding-top: 2rem;
        }

        .kpi-card {
            background: #F5F5F5;
            border-radius: 10px;
            padding: 1rem;
            text-align: left;
        }
        .kpi-label { font-size: 13px; color: #666; margin: 0 0 4px 0; }
        .kpi-value { font-size: 26px; font-weight: 600; margin: 0; }

        .alert-row {
            display: flex;
            gap: 12px;
            align-items: flex-start;
            padding: 12px 14px;
            border-bottom: 1px solid #E5E5E5;
            border-left: 3px solid transparent;
        }
        .alert-row-alta-quiebre  { border-left-color: #D64545; }
        .alert-row-sobre-pedido  { border-left-color: #E0A030; }
        .alert-row-leve          { opacity: 0.7; }
        .alert-row-desconocido   { border-left-color: #4A7FD6; }

        .alert-msg  { font-size: 14px; margin: 0; }
        .alert-tag  { font-size: 12px; color: #888; margin: 4px 0 0 0; }

        .section-label {
            font-size: 13px;
            color: #888;
            text-transform: none;
            margin: 1.2rem 0 0.5rem 0;
        }

        /* Logo tipo header */
        .app-logo {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 26px;
            font-weight: 800;
            letter-spacing: 0.5px;
            margin-bottom: 0.5rem;
        }

        /* Tabs con look de nav: mayúsculas, subrayado rojo en la activa */
        .stTabs [data-baseweb="tab-list"] {
            gap: 24px;
            border-bottom: 1px solid #E5E5E5;
        }
        .stTabs [data-baseweb="tab"] {
            height: auto;
            padding: 8px 2px;
            font-size: 14px;
            color: #888;
        }
        .stTabs [aria-selected="true"] {
            color: #111 !important;
            border-bottom: 2px solid #111 !important;
        }
        .stTabs [data-baseweb="tab-highlight"] {
            background-color: #111 !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Carga de datos: se guarda en session_state (no con @st.cache_data) porque
# la orden se puede editar desde la pestaña "Ordenes" y necesitamos que esos
# cambios persistan entre reruns de la app durante la sesión del usuario.
# ---------------------------------------------------------------------------
if "data" not in st.session_state:
    st.session_state.data = logic.load_data()
    # Guardamos una copia de la orden original para poder detectar qué
    # celdas fueron editadas manualmente (comparación en la pestaña Ordenes)
    st.session_state.orden_original = st.session_state.data["orden"].copy()


def get_alerts():
    return logic.generate_alerts(st.session_state.data)


# Íconos y clase CSS por tipo de alerta
TIPO_INFO = {
    "riesgo_quiebre": {"icono": "⚠️", "clase": "alta-quiebre", "etiqueta": "Riesgo de quiebre"},
    "sobre_pedido": {"icono": "⬆️", "clase": "sobre-pedido", "etiqueta": "Sobre-pedido"},
    "faltante_total": {"icono": "⚠️", "clase": "alta-quiebre", "etiqueta": "Faltante total"},
    "ingrediente_desconocido": {"icono": "❔", "clase": "desconocido", "etiqueta": "Revisar manualmente"},
    "orden_rara": {"icono": "🔍", "clase": "desconocido", "etiqueta": "Orden atípica"},
}


def render_alert_row(row, atenuado=False):
    info = TIPO_INFO[row["tipo_alerta"]]
    clase = f"alert-row alert-row-{info['clase']}" + (" alert-row-leve" if atenuado else "")
    st.markdown(
        f"""
        <div class="{clase}">
            <span>{info['icono']}</span>
            <div>
                <p class="alert-msg">{row['mensaje']}</p>
                <p class="alert-tag">{info['etiqueta']}</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_alertas_tab():
    alertas = get_alerts()
    con_alerta = alertas[alertas["tipo_alerta"].notna()]
    total = len(con_alerta)

    if total == 0:
        st.markdown("### Bienvenido Jefe, todo en orden.")
    else:
        st.markdown("### Bienvenido Jefe, hay alertas que requieren su atención.")

    # -------------------- KPIs --------------------
    n_quiebre = (con_alerta["tipo_alerta"] == "riesgo_quiebre").sum()
    n_sobre = (con_alerta["tipo_alerta"] == "sobre_pedido").sum()
    n_faltante = (con_alerta["tipo_alerta"] == "faltante_total").sum()
    n_desconocido = (con_alerta["tipo_alerta"] == "ingrediente_desconocido").sum()
    n_atipica = (con_alerta["tipo_alerta"] == "orden_rara").sum()

    kpis = [
        ("Alertas totales", total),
        ("Riesgo de quiebre", n_quiebre),
        ("Sobre-pedido", n_sobre),
        ("Faltante total", n_faltante),
        ("Sin catalogar", n_desconocido),
        ("Orden atípica", n_atipica),
    ]
    cols = st.columns(len(kpis))
    for col, (label, value) in zip(cols, kpis):
        with col:
            st.markdown(
                f"""
                <div class="kpi-card">
                    <p class="kpi-label">{label}</p>
                    <p class="kpi-value">{value}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # -------------------- Filtro por sucursal --------------------
    sucursales = ["Todas"] + sorted(alertas["sucursal"].dropna().unique().tolist())
    sucursal_elegida = st.radio(
        "Sucursal", sucursales, horizontal=True, label_visibility="collapsed"
    )

    if sucursal_elegida != "Todas":
        con_alerta = con_alerta[con_alerta["sucursal"] == sucursal_elegida]

    # -------------------- Alertas por severidad --------------------
    conocidas = con_alerta[con_alerta["tipo_alerta"] != "ingrediente_desconocido"]
    desconocidas = con_alerta[con_alerta["tipo_alerta"] == "ingrediente_desconocido"]

    altas = conocidas[conocidas["severidad"] == "alta"]
    leves = conocidas[conocidas["severidad"] == "leve"]

    if not altas.empty:
        st.markdown('<p class="section-label">Severidad alta</p>', unsafe_allow_html=True)
        for _, row in altas.iterrows():
            render_alert_row(row)

    if not leves.empty:
        st.markdown('<p class="section-label">Severidad leve</p>', unsafe_allow_html=True)
        for _, row in leves.iterrows():
            render_alert_row(row, atenuado=True)

    if not desconocidas.empty:
        st.markdown('<p class="section-label">Ingredientes sin catalogar</p>', unsafe_allow_html=True)
        for _, row in desconocidas.iterrows():
            render_alert_row(row)

    if altas.empty and leves.empty and desconocidas.empty:
        st.success("No hay alertas para esta sucursal. Todo dentro de lo esperado. 🎉")

    # -------------------- Detalle expandible --------------------
    with st.expander("Ver detalle completo (proyección, stock, pedido)"):
        columnas_detalle = [
            "sucursal", "nombre", "consumo_proyectado_unidad_base",
            "stock_actual_unidad_base", "necesidad_real_unidad_base",
            "pedido_unidad_base", "diferencia_unidad_base", "tipo_alerta", "severidad",
        ]
        st.dataframe(alertas[columnas_detalle], use_container_width=True, hide_index=True)


def get_gemini_api_key():
    """
    Busca la API key de Gemini en este orden:
    1. st.secrets["GOOGLE_API_KEY"] -- para cuando la app esté publicada
       en Streamlit Cloud (se configura ahí, no en un archivo).
    2. Variable de entorno GOOGLE_API_KEY -- por si se corre así local.
    3. Archivo local API_KEY.env, variable "key" -- para desarrollo local
       (ese archivo nunca se sube al repo, está en .gitignore).
    """
    try:
        return st.secrets["GOOGLE_API_KEY"]
    except Exception:
        pass

    if os.environ.get("GOOGLE_API_KEY"):
        return os.environ["GOOGLE_API_KEY"]

    env_path = Path(__file__).parent / "API_KEY.env"
    if env_path.exists():
        valores = dotenv_values(env_path)
        return valores.get("key")

    return None


def obtener_respuesta(prompt: str) -> str:
    """
    Le pregunta a Bob (Gemini) sobre el estado actual de los datos.
    El contexto se arma en vivo con logic.build_chat_context(), así que
    refleja también las ediciones hechas desde la pestaña Ordenes.
    """
    api_key = get_gemini_api_key()
    if not api_key:
        return (
            "⚠️ Falta configurar la API key de Gemini. Definí la variable de "
            "entorno GOOGLE_API_KEY (o el secret en Streamlit Cloud) para que "
            "Bob pueda responder."
        )

    contexto = logic.build_chat_context(st.session_state.data)
    system_instruction = (
        "Sos Bob, el asistente de datos del dashboard de compras de Barrio "
        "Pizza. Respondé en español, de forma breve y concreta, a preguntas "
        "de la gerente de compras sobre las órdenes de esta semana. "
        "Basate ÚNICAMENTE en los datos de contexto que te paso a "
        "continuación -- no inventes cifras. Si la pregunta no se puede "
        "responder con estos datos, decilo con honestidad.\n\n"
        f"{contexto}"
    )

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=system_instruction),
        )
        return response.text
    except Exception as e:
        return f"⚠️ Hubo un error consultando a Bob: {e}"


def render_ordenes_tab():
    data = st.session_state.data

    sucursales = sorted(data["orden"]["sucursal"].dropna().unique().tolist())
    sucursal_elegida = st.radio(
        "Sucursal", sucursales, horizontal=True, label_visibility="collapsed", key="sucursal_ordenes"
    )

    # La tabla se arma con TODO lo que la sucursal consume habitualmente
    # (según el histórico) UNIDO a lo que pidió esta semana -- no solo lo
    # pedido. Así, un ingrediente con "faltante_total" (pidieron 0) aparece
    # igual en la tabla, con cantidad 0, para poder completarlo.
    consumo_ids = set(
        data["consumo"].loc[data["consumo"]["sucursal"] == sucursal_elegida, "ingrediente_id"]
    )
    orden_ids = set(
        data["orden"].loc[data["orden"]["sucursal"] == sucursal_elegida, "ingrediente_id"]
    )
    ids_relevantes = consumo_ids | orden_ids

    catalogo = data["ingredientes"]
    base = catalogo[catalogo["ingrediente_id"].isin(ids_relevantes)][
        ["ingrediente_id", "nombre", "formato_compra"]
    ].copy()

    # Ingredientes pedidos que no están en el catálogo (ej. aji_chombo) no
    # tienen fila en "ingredientes" -> los agregamos manualmente
    ids_sin_catalogar = ids_relevantes - set(catalogo["ingrediente_id"])
    if ids_sin_catalogar:
        extra = pd.DataFrame({
            "ingrediente_id": list(ids_sin_catalogar),
            "nombre": list(ids_sin_catalogar),
            "formato_compra": "(sin catalogar)",
        })
        base = pd.concat([base, extra], ignore_index=True)

    orden_cantidades = data["orden"].loc[
        data["orden"]["sucursal"] == sucursal_elegida, ["ingrediente_id", "cantidad_formatos"]
    ]
    tabla = base.merge(orden_cantidades, on="ingrediente_id", how="left")
    tabla["cantidad_formatos"] = tabla["cantidad_formatos"].fillna(0)

    tabla["nombre"] = tabla["nombre"].fillna(tabla["ingrediente_id"])
    tabla["formato_compra"] = tabla["formato_compra"].fillna("(sin catalogar)")

    # Marcamos con el tipo de alerta los ingredientes que ahora mismo tienen
    # un problema pendiente, para que se note de un vistazo qué ajustar y por qué
    alertas_actuales = get_alerts()
    alertas_sucursal = alertas_actuales[
        (alertas_actuales["sucursal"] == sucursal_elegida) & alertas_actuales["tipo_alerta"].notna()
    ]
    etiquetas_por_ingrediente = {
        row["ingrediente_id"]: TIPO_INFO[row["tipo_alerta"]]["icono"] + " " + TIPO_INFO[row["tipo_alerta"]]["etiqueta"]
        for _, row in alertas_sucursal.iterrows()
    }
    tabla["alerta"] = tabla["ingrediente_id"].map(etiquetas_por_ingrediente).fillna("")

    tabla_editable = tabla[["alerta", "ingrediente_id", "nombre", "formato_compra", "cantidad_formatos"]].rename(
        columns={"alerta": "Estado", "nombre": "Ingrediente", "formato_compra": "Formato", "cantidad_formatos": "Cantidad"}
    )

    resultado = st.data_editor(
        tabla_editable,
        column_config={
            "ingrediente_id": None,  # oculto, solo lo usamos para hacer el merge al guardar
            "Estado": st.column_config.TextColumn(disabled=True, width="medium"),
            "Ingrediente": st.column_config.TextColumn(disabled=True),
            "Formato": st.column_config.TextColumn(disabled=True),
            "Cantidad": st.column_config.NumberColumn(min_value=0, step=1),
        },
        hide_index=True,
        use_container_width=True,
        key=f"editor_{sucursal_elegida}",
    )

    # -------------------- Detección de cambios pendientes --------------------
    # Comparamos contra el ÚLTIMO ESTADO GUARDADO (data["orden"] actual de la
    # sesión), no contra el CSV original -- así, una vez que se confirma un
    # cambio con "Actualizar alertas", el aviso de "pendiente" desaparece.
    ultimo_guardado = data["orden"]
    ultimo_guardado_sucursal = ultimo_guardado[
        ultimo_guardado["sucursal"] == sucursal_elegida
    ].set_index("ingrediente_id")

    cambios = []
    for _, fila in resultado.iterrows():
        ing_id = fila["ingrediente_id"]
        cantidad_nueva = fila["Cantidad"]
        cantidad_guardada = (
            ultimo_guardado_sucursal.loc[ing_id, "cantidad_formatos"]
            if ing_id in ultimo_guardado_sucursal.index
            else 0
        )
        if cantidad_nueva != cantidad_guardada:
            cambios.append(f"**{fila['Ingrediente']}**: {cantidad_guardada} → {cantidad_nueva}")

    if cambios:
        st.caption("✏️ Cambios sin aplicar: " + " · ".join(cambios))

    if st.button("🔄 Actualizar alertas", type="primary"):
        # Escribimos los valores editados de vuelta en los datos de la sesión.
        # Puede haber ingredientes que antes NO tenían fila en la orden
        # (ej. un faltante total al que ahora le cargan cantidad) -> hay que
        # insertarlos, no solo actualizar filas existentes.
        orden_actualizada = data["orden"].copy()
        nuevas_filas = []
        for _, fila in resultado.iterrows():
            mask = (orden_actualizada["sucursal"] == sucursal_elegida) & (
                orden_actualizada["ingrediente_id"] == fila["ingrediente_id"]
            )
            if mask.any():
                orden_actualizada.loc[mask, "cantidad_formatos"] = fila["Cantidad"]
            elif fila["Cantidad"] > 0:
                nuevas_filas.append({
                    "sucursal": sucursal_elegida,
                    "ingrediente_id": fila["ingrediente_id"],
                    "cantidad_formatos": fila["Cantidad"],
                })
        if nuevas_filas:
            orden_actualizada = pd.concat(
                [orden_actualizada, pd.DataFrame(nuevas_filas)], ignore_index=True
            )
        st.session_state.data["orden"] = orden_actualizada
        st.success(f"Orden de {sucursal_elegida} actualizada. Revisá la pestaña Alertas.")
        st.rerun()

    # -------------------- Pedido corregido por proveedor --------------------
    st.divider()
    st.markdown("#### 📦 Pedido corregido ")
    st.caption(
        "Esto es lo que la sucursal DEBERÍA pedir según la proyección "
        "agrupado por proveedor."
        
    )

    pedido_corregido = logic.corrected_order_by_provider(data, sucursal_elegida)

    if pedido_corregido.empty:
        st.info("No hace falta pedir nada de más -- el stock actual cubre la proyección.")
    else:
        for proveedor, grupo in pedido_corregido.groupby("proveedor", sort=False):
            with st.expander(f"**{proveedor}** ({len(grupo)} ingredientes)"):
                texto_lineas = [f"Pedido para {proveedor} -- {sucursal_elegida}:"]
                for _, fila in grupo.iterrows():
                    linea = f"- {fila['nombre']}: {fila['cantidad_formatos_corregida']} x {fila['formato_compra']}"
                    st.markdown(linea)
                    texto_lineas.append(linea)
                st.code("\n".join(texto_lineas), language=None)


# ---------------------------------------------------------------------------
# Navegación principal
# ---------------------------------------------------------------------------
LOGO_PATH = Path(__file__).parent / "assets" / "barrio_logo.jpg"

if LOGO_PATH.exists():
    col_logo, _ = st.columns([1, 5])
    with col_logo:
        st.image(str(LOGO_PATH), width=160)
else:
    # Fallback mientras no se suba el logo real
    st.markdown('<div class="app-logo">🍕 BARRIO PIZZA</div>', unsafe_allow_html=True)
tab_alertas, tab_ordenes = st.tabs(["Alertas", "Ordenes"])

with tab_alertas:
    render_alertas_tab()

with tab_ordenes:
    render_ordenes_tab()


# ---------------------------------------------------------------------------
# Chat con los datos: "Bob" -- sidebar visible en todas las pestañas
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("💬 Bob")
    st.markdown("Dile hola a Bob!")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    chat_container = st.container(height=350)
    with chat_container:
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    if prompt := st.chat_input("Escribe tu duda..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_container:
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.spinner("Pensando..."):
                    response = obtener_respuesta(prompt)

                def stream_data():
                    for word in response.split(" "):
                        yield word + " "
                        time.sleep(0.02)

                st.write_stream(stream_data)
        st.session_state.messages.append({"role": "assistant", "content": response})