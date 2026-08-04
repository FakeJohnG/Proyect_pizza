"""
logic.py — Lógica de negocio del dashboard de compras de Barrio Pizza.

Este módulo es independiente de la interfaz (Streamlit). Todas las funciones
reciben y devuelven DataFrames / estructuras simples de pandas, para poder
testearlas sin levantar la UI.
"""

from pathlib import Path
import pandas as pd
import math

DATA_DIR = Path(__file__).parent / "datos"


def load_data(data_dir: Path = DATA_DIR) -> dict[str, pd.DataFrame]:
    """
    Carga los 4 CSV del reto y devuelve un diccionario con los DataFrames.

    Devuelve:
        {
            "ingredientes": catálogo (ingrediente_id, nombre, proveedor,
                             unidad_base, formato_compra,
                             unidad_base_por_formato, es_perecedero),
            "consumo":      histórico semanal por sucursal e ingrediente,
            "inventario":   stock actual por sucursal e ingrediente,
            "orden":        orden de compra de la semana (en formatos)
                             por sucursal e ingrediente,
        }


    """
    data_dir = Path(data_dir)

    ingredientes = pd.read_csv(data_dir / "ingredientes.csv", encoding="utf-8-sig")
    consumo = pd.read_csv(data_dir / "consumo_historico.csv", encoding="utf-8-sig")
    inventario = pd.read_csv(data_dir / "inventario_actual.csv", encoding="utf-8-sig")
    orden = pd.read_csv(data_dir / "orden_compra_semana.csv", encoding="utf-8-sig")

    # Tipos: aseguramos que las columnas de cantidad sean numéricas
    consumo["consumo_unidad_base"] = pd.to_numeric(consumo["consumo_unidad_base"])
    inventario["stock_actual_unidad_base"] = pd.to_numeric(inventario["stock_actual_unidad_base"])
    orden["cantidad_formatos"] = pd.to_numeric(orden["cantidad_formatos"])
    ingredientes["unidad_base_por_formato"] = pd.to_numeric(ingredientes["unidad_base_por_formato"])

    return {
        "ingredientes": ingredientes,
        "consumo": consumo,
        "inventario": inventario,
        "orden": orden,
    }


def validate_data(data: dict[str, pd.DataFrame]) -> dict[str, list]:
    """
    Corre chequeos de calidad de datos y devuelve un resumen de problemas
    encontrados, para que la UI los muestre de forma transparente.

    Devuelve:
        {
            "ingredientes_no_catalogados": [(sucursal, ingrediente_id), ...]
                -> aparecen en la orden pero no existen en ingredientes.csv
            "faltantes_totales": [(sucursal, ingrediente_id), ...]
                -> la sucursal consume ese ingrediente habitualmente
                   (tiene histórico) pero no lo pidió esta semana
        }
    """
    ingredientes = data["ingredientes"]
    consumo = data["consumo"]
    orden = data["orden"]

    catalogo_ids = set(ingredientes["ingrediente_id"])

    # 1) Ingredientes pedidos que no están en el catálogo
    no_catalogados = []
    for _, row in orden.iterrows():
        if row["ingrediente_id"] not in catalogo_ids:
            no_catalogados.append((row["sucursal"], row["ingrediente_id"]))

    # 2) Ingredientes que la sucursal consume habitualmente pero no pidió
    faltantes_totales = []
    consumo_pares = set(zip(consumo["sucursal"], consumo["ingrediente_id"]))
    orden_pares = set(zip(orden["sucursal"], orden["ingrediente_id"]))
    for sucursal, ingrediente_id in sorted(consumo_pares - orden_pares):
        faltantes_totales.append((sucursal, ingrediente_id))

    return {
        "ingredientes_no_catalogados": no_catalogados,
        "faltantes_totales": faltantes_totales,
    }


def project_consumption(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Proyecta el consumo de la próxima semana por sucursal e ingrediente,
    usando la MEDIANA de las últimas 6 semanas de histórico.

    Devuelve un DataFrame con columnas:
        sucursal, ingrediente_id, consumo_proyectado_unidad_base
    """
    consumo = data["consumo"]

    proyeccion = (
        consumo.groupby(["sucursal", "ingrediente_id"])["consumo_unidad_base"]
        .median()
        .reset_index()
        .rename(columns={"consumo_unidad_base": "consumo_proyectado_unidad_base"})
    )
    return proyeccion


def compute_needs(data: dict[str, pd.DataFrame], proyeccion: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula la necesidad real de cada sucursal-ingrediente:

        necesidad_real = consumo_proyectado − stock_actual

    Devuelve un DataFrame con columnas:
        sucursal, ingrediente_id, consumo_proyectado_unidad_base,
        stock_actual_unidad_base, necesidad_real_unidad_base
    """
    inventario = data["inventario"]

    needs = proyeccion.merge(
        inventario,
        on=["sucursal", "ingrediente_id"],
        how="left",  # si falta inventario para algún par, queda NaN (lo señalamos, no lo inventamos)
    )
    needs["stock_actual_unidad_base"] = needs["stock_actual_unidad_base"].fillna(0)
    needs["necesidad_real_unidad_base"] = (
        needs["consumo_proyectado_unidad_base"] - needs["stock_actual_unidad_base"]
    )
    return needs


def convert_order_to_base_units(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Convierte la orden de compra (en formatos, ej. "3 sacos") a unidad base
    (ej. kg), usando unidad_base_por_formato del catálogo.

    Devuelve un DataFrame con columnas:
        sucursal, ingrediente_id, cantidad_formatos,
        unidad_base_por_formato, pedido_unidad_base
    """
    orden = data["orden"]
    ingredientes = data["ingredientes"][
        ["ingrediente_id", "unidad_base_por_formato", "unidad_base", "formato_compra"]
    ]

    orden_convertida = orden.merge(ingredientes, on="ingrediente_id", how="inner")
    orden_convertida["pedido_unidad_base"] = (
        orden_convertida["cantidad_formatos"] * orden_convertida["unidad_base_por_formato"]
    )
    return orden_convertida


def generate_alerts(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Junta proyección + inventario + orden convertida y genera las alertas
    finales, comparando lo pedido contra la necesidad real.

    Regla de redondeo: los insumos se compran en formatos completos, así
    que un excedente MENOR a un formato completo (unidad_base_por_formato)
    es redondeo normal, no una alerta de sobre-pedido.

    Tipos de alerta (columna "tipo_alerta"):
        - "riesgo_quiebre": piden menos de lo que necesitan
        - "sobre_pedido":   piden de más, más allá del margen de redondeo
        - "faltante_total": no pidieron nada de un ingrediente que
                             consumen habitualmente
        - "ingrediente_desconocido": pedido de un ingrediente que no
                             está en el catálogo (no se puede calcular
                             cantidad, se marca para revisión manual)
        - None:             el pedido está dentro de lo esperado, no hay
                             alerta

    Devuelve un DataFrame con todas las filas sucursal-ingrediente
    (incluyendo las que no requieren alerta) más una fila por cada
    ingrediente desconocido, con columnas:
        sucursal, ingrediente_id, nombre, unidad_base,
        consumo_proyectado_unidad_base, stock_actual_unidad_base,
        necesidad_real_unidad_base, pedido_unidad_base,
        diferencia_unidad_base, tipo_alerta, mensaje
    """
    ingredientes = data["ingredientes"]

    proyeccion = project_consumption(data)
    needs = compute_needs(data, proyeccion)
    orden_convertida = convert_order_to_base_units(data)
    problemas = validate_data(data)

    # Cruzamos necesidad con lo efectivamente pedido (convertido a unidad base)
    alertas = needs.merge(
        orden_convertida[["sucursal", "ingrediente_id", "pedido_unidad_base"]],
        on=["sucursal", "ingrediente_id"],
        how="left",  # si no pidieron nada, pedido_unidad_base queda NaN -> lo tratamos como 0
    )
    alertas["pedido_unidad_base"] = alertas["pedido_unidad_base"].fillna(0)

    # Traemos nombre legible y unidad de medida para armar el mensaje
    alertas = alertas.merge(
        ingredientes[["ingrediente_id", "nombre", "unidad_base", "unidad_base_por_formato"]],
        on="ingrediente_id",
        how="left",
    )

    alertas["diferencia_unidad_base"] = (
        alertas["pedido_unidad_base"] - alertas["necesidad_real_unidad_base"]
    )

    faltantes_totales = set(problemas["faltantes_totales"])

    def clasificar(row):
        clave = (row["sucursal"], row["ingrediente_id"])
        diff = row["diferencia_unidad_base"]
        margen_redondeo = row["unidad_base_por_formato"]

        if clave in faltantes_totales:
            return "faltante_total"
        if diff < 0:
            return "riesgo_quiebre"
        if diff >= margen_redondeo:
            return "sobre_pedido"
        return None  # dentro de lo esperado (incluye redondeo normal)

    def clasificar_severidad(row):
        """
        Nivel de severidad dentro de cada tipo de alerta:
        - faltante_total e ingrediente_desconocido: siempre "alta"
        - sobre_pedido: siempre "alta" (ya filtramos el redondeo normal antes)
        - riesgo_quiebre: "leve" si el déficit es menor a un formato completo
          (ej. faltan 0.3kg de algo que se compra en cajas de 5kg — se nota
          pero no amerita la misma urgencia que faltar un saco entero),
          "alta" si el déficit es de un formato completo o más.
        """
        tipo = row["tipo_alerta"]
        if tipo is None:
            return None
        if tipo != "riesgo_quiebre":
            return "alta"
        deficit = abs(row["diferencia_unidad_base"])
        margen_redondeo = row["unidad_base_por_formato"]
        return "leve" if deficit < margen_redondeo else "alta"

    alertas["tipo_alerta"] = alertas.apply(clasificar, axis=1)
    alertas["severidad"] = alertas.apply(clasificar_severidad, axis=1)
    alertas["mensaje"] = alertas.apply(_build_message, axis=1)

    # Agregamos los ingredientes no catalogados como filas de alerta aparte
    filas_desconocidas = []
    orden = data["orden"]
    for sucursal, ingrediente_id in problemas["ingredientes_no_catalogados"]:
        cantidad = orden.loc[
            (orden["sucursal"] == sucursal) & (orden["ingrediente_id"] == ingrediente_id),
            "cantidad_formatos",
        ].iloc[0]
        filas_desconocidas.append({
            "sucursal": sucursal,
            "ingrediente_id": ingrediente_id,
            "nombre": ingrediente_id,
            "unidad_base": None,
            "consumo_proyectado_unidad_base": None,
            "stock_actual_unidad_base": None,
            "necesidad_real_unidad_base": None,
            "pedido_unidad_base": None,
            "diferencia_unidad_base": None,
            "tipo_alerta": "ingrediente_desconocido",
            "severidad": "alta",
            "mensaje": (
                f"ALERTA: {sucursal} pidió {cantidad} unidades de "
                f"'{ingrediente_id}', que no está en el catálogo de "
                f"ingredientes → revisar manualmente."
            ),
        })

    if filas_desconocidas:
        alertas = pd.concat([alertas, pd.DataFrame(filas_desconocidas)], ignore_index=True)

    # -------------------- Órdenes raras (comparación entre sucursales) --------------------
    # Solo agregamos las que NO están ya cubiertas por otra alerta en el
    # mismo par sucursal-ingrediente, para no mostrar la misma señal dos
    # veces con distinta redacción.
    pares_ya_alertados = set(
        zip(alertas.loc[alertas["tipo_alerta"].notna(), "sucursal"],
            alertas.loc[alertas["tipo_alerta"].notna(), "ingrediente_id"])
    )
    ordenes_raras = detect_unusual_orders(data)
    if not ordenes_raras.empty:
        ordenes_raras = ordenes_raras[
            ~ordenes_raras.apply(lambda r: (r["sucursal"], r["ingrediente_id"]) in pares_ya_alertados, axis=1)
        ]
    if not ordenes_raras.empty:
        columnas_comunes = ["sucursal", "ingrediente_id", "nombre", "tipo_alerta", "severidad", "mensaje"]
        alertas = pd.concat([alertas, ordenes_raras[columnas_comunes]], ignore_index=True)

    return alertas



def _build_message(row) -> str | None:
    """Arma el texto de alerta accionable para una fila de generate_alerts."""
    tipo = row["tipo_alerta"]
    if tipo is None:
        return None

    sucursal = row["sucursal"]
    nombre = row["nombre"]
    unidad = row["unidad_base"]

    if tipo == "faltante_total":
        return (
            f"ALERTA: {sucursal} no pidió nada de {nombre}, "
            f"pero lo consume habitualmente → riesgo de quiebre."
        )
    if tipo == "riesgo_quiebre":
        faltante = abs(row["diferencia_unidad_base"])
        return (
            f"ALERTA: {sucursal} está pidiendo {faltante:.1f} {unidad} de "
            f"{nombre} menos que lo proyectado → riesgo de quiebre."
        )
    if tipo == "sobre_pedido":
        exceso = row["diferencia_unidad_base"]
        return (
            f"ALERTA: {sucursal} está pidiendo {exceso:.1f} {unidad} de "
            f"{nombre} de más que lo proyectado → posible sobre-stock."
        )
    return None


def build_chat_context(data: dict[str, pd.DataFrame]) -> str:
    """
    Arma un resumen de texto compacto con el estado actual de los datos
    (catálogo + alertas + tabla de proyección/stock/pedido), para pasárselo
    como contexto a un modelo de lenguaje que responda preguntas de la
    gerente de compras ("chat con los datos").

    Se recalcula sobre `data` (no sobre un snapshot fijo) para que refleje
    también las ediciones que se hayan hecho desde la pestaña Ordenes.
    """
    alertas = generate_alerts(data)
    ingredientes = data["ingredientes"]

    lineas = ["=== CATÁLOGO DE INGREDIENTES ==="]
    lineas.append("ingrediente | proveedor | unidad_base | formato_compra | cuanto_trae_cada_formato | perecedero")
    for _, row in ingredientes.iterrows():
        lineas.append(
            f"{row['nombre']} | {row['proveedor']} | {row['unidad_base']} | "
            f"{row['formato_compra']} | {row['unidad_base_por_formato']} {row['unidad_base']} por formato | "
            f"{row['es_perecedero']}"
        )

    lineas.append("")
    lineas.append("=== ALERTAS ACTUALES ===")
    con_alerta = alertas[alertas["tipo_alerta"].notna()]
    if con_alerta.empty:
        lineas.append("No hay alertas pendientes.")
    else:
        for _, row in con_alerta.iterrows():
            lineas.append(f"- [{row['tipo_alerta']} / severidad {row['severidad']}] {row['mensaje']}")

    lineas.append("")
    lineas.append("=== DETALLE POR SUCURSAL E INGREDIENTE (unidad base) ===")
    lineas.append("sucursal | ingrediente | consumo_proyectado | stock_actual | pedido | necesidad_real")
    detalle = alertas[alertas["tipo_alerta"] != "ingrediente_desconocido"]
    for _, row in detalle.iterrows():
        lineas.append(
            f"{row['sucursal']} | {row['nombre']} | "
            f"{row['consumo_proyectado_unidad_base']:.1f} | "
            f"{row['stock_actual_unidad_base']:.1f} | "
            f"{row['pedido_unidad_base']:.1f} | "
            f"{row['necesidad_real_unidad_base']:.1f}"
        )

    return "\n".join(lineas)


def detect_unusual_orders(data: dict[str, pd.DataFrame], factor: float = 1.5) -> pd.DataFrame:
    """
    Detecta "órdenes raras": una sucursal pidiendo proporcionalmente mucho
    más o menos de un ingrediente que el resto de las sucursales, aunque
    individualmente su pedido no dispare riesgo_quiebre/sobre_pedido
    (porque esas reglas comparan contra el propio histórico, no contra
    las demás sucursales).

    Un caso se marca como atípico si su ratio es >= factor veces la
    mediana de sus pares, o <= 1/factor veces esa mediana. Requiere al
    menos 3 sucursales con datos para ese ingrediente (si no, no hay
    suficiente base de comparación).

    Devuelve un DataFrame con: sucursal, ingrediente_id, nombre,
    ratio_propio, mediana_pares, desvio, tipo_alerta ("orden_rara"),
    severidad, mensaje.
    """
    proyeccion = project_consumption(data)
    needs = compute_needs(data, proyeccion)
    orden_convertida = convert_order_to_base_units(data)

    combinado = needs.merge(
        orden_convertida[["sucursal", "ingrediente_id", "pedido_unidad_base"]],
        on=["sucursal", "ingrediente_id"],
        how="left",
    )
    combinado["pedido_unidad_base"] = combinado["pedido_unidad_base"].fillna(0)
    combinado = combinado[combinado["consumo_proyectado_unidad_base"] > 0].copy()
    combinado["ratio"] = combinado["pedido_unidad_base"] / combinado["consumo_proyectado_unidad_base"]

    filas = []
    for _, grupo in combinado.groupby("ingrediente_id"):
        if len(grupo) < 3:
            continue  # no hay suficientes sucursales para comparar de forma confiable
        for _, fila in grupo.iterrows():
            pares = grupo[grupo["sucursal"] != fila["sucursal"]]
            mediana_pares = pares["ratio"].median()
            if mediana_pares == 0:
                continue
            desvio = fila["ratio"] / mediana_pares
            if desvio >= factor or desvio <= 1 / factor:
                filas.append({
                    "sucursal": fila["sucursal"],
                    "ingrediente_id": fila["ingrediente_id"],
                    "ratio_propio": fila["ratio"],
                    "mediana_pares": mediana_pares,
                    "desvio": desvio,
                })

    resultado = pd.DataFrame(
        filas, columns=["sucursal", "ingrediente_id", "ratio_propio", "mediana_pares", "desvio"]
    )
    if resultado.empty:
        resultado["tipo_alerta"] = []
        resultado["severidad"] = []
        resultado["mensaje"] = []
        return resultado

    ingredientes = data["ingredientes"][["ingrediente_id", "nombre"]]
    resultado = resultado.merge(ingredientes, on="ingrediente_id", how="left")
    resultado["nombre"] = resultado["nombre"].fillna(resultado["ingrediente_id"])

    resultado["tipo_alerta"] = "orden_rara"
    resultado["severidad"] = resultado["desvio"].apply(
        lambda d: "alta" if (d >= factor * 1.7 or d <= 1 / (factor * 1.7)) else "leve"
    )

    def _mensaje(row):
        direccion = "más" if row["desvio"] > 1 else "menos"
        return (
            f"ALERTA: {row['sucursal']} pidió proporcionalmente mucho {direccion} "
            f"{row['nombre']} que el resto de las sucursales "
            f"({row['ratio_propio']:.1f}x su propia proyección, vs. "
            f"{row['mediana_pares']:.1f}x en las demás) → orden atípica, revisar."
        )

    resultado["mensaje"] = resultado.apply(_mensaje, axis=1)
    return resultado

def corrected_order_by_provider(data: dict[str, pd.DataFrame], sucursal: str) -> pd.DataFrame:
    """
    Arma el pedido CORREGIDO (según la proyección, no lo que la sucursal
    pidió con errores) para una sucursal, agrupado por proveedor -- para
    poder reenviarle a cada proveedor directamente su parte del pedido.
 
    La cantidad se redondea hacia ARRIBA al formato de compra completo
    más cercano (nunca se compra de menos; el sobrante chico es
    redondeo normal, no un problema).
 
    Devuelve un DataFrame con: proveedor, nombre, formato_compra,
    cantidad_formatos_corregida, necesidad_real_unidad_base, unidad_base
    -- ordenado por proveedor y luego por nombre.
    """
    proyeccion = project_consumption(data)
    needs = compute_needs(data, proyeccion)
    needs_sucursal = needs[needs["sucursal"] == sucursal].copy()
 
    ingredientes = data["ingredientes"][
        ["ingrediente_id", "nombre", "proveedor", "formato_compra", "unidad_base_por_formato", "unidad_base"]
    ]
    # merge "inner": los ingredientes no catalogados no tienen fila en el
    # catálogo, así que quedan excluidos automáticamente
    tabla = needs_sucursal.merge(ingredientes, on="ingrediente_id", how="inner")
 
    tabla = tabla[tabla["necesidad_real_unidad_base"] > 0].copy()
    tabla["cantidad_formatos_corregida"] = (
        tabla["necesidad_real_unidad_base"] / tabla["unidad_base_por_formato"]
    ).apply(math.ceil)
 
    tabla = tabla.sort_values(["proveedor", "nombre"])
    return tabla[
        ["proveedor", "nombre", "formato_compra", "cantidad_formatos_corregida",
         "necesidad_real_unidad_base", "unidad_base"]
    ].reset_index(drop=True)

if __name__ == "__main__":
    # Prueba rápida manual: python logic.py
    data = load_data()
    for nombre, df in data.items():
        print(f"--- {nombre} ({len(df)} filas) ---")
        print(df.head(3))
        print()

    problemas = validate_data(data)
    print("=== Problemas de calidad de datos ===")
    print("Ingredientes no catalogados:", problemas["ingredientes_no_catalogados"])
    print("Faltantes totales (no pidieron nada):", problemas["faltantes_totales"])
    print()

    proyeccion = project_consumption(data)
    print("=== Proyección (mediana) — chequeo caso Marbella/pepperoni ===")
    print(proyeccion[
        (proyeccion["sucursal"] == "Marbella") & (proyeccion["ingrediente_id"] == "pepperoni")
    ])
    print("(esperado: ~29, NO ~49 que daría un promedio simple)")
    print()

    needs = compute_needs(data, proyeccion)
    print("=== Necesidad real (primeras filas) ===")
    print(needs.head(8))
    print()

    alertas = generate_alerts(data)
    con_alerta = alertas[alertas["tipo_alerta"].notna()]
    print(f"=== Alertas generadas: {len(con_alerta)} de {len(alertas)} filas totales ===")
    print(con_alerta["tipo_alerta"].value_counts())
    print()
    print("=== Mensajes de alerta (con severidad) ===")
    for _, row in con_alerta.iterrows():
        print(f"- [{row['severidad']}] {row['mensaje']}")
