# Proyect_pizza

Reto práctico para Barrio Pizza, desarrollado por Juan Delgado.

Dashboard que revisa automáticamente las órdenes de compra semanales de las 4 sucursales y genera alertas accionables sobre qué pedir de más, de menos, o directamente qué se olvidaron de pedir.

🔗 **App en vivo:** https://proyectpizza-biouho9q2mkomuqrm93phu.streamlit.app/

🎥 **Video (3–5 min):** https://youtu.be/ZdM4mvQnpqE

---

## Cómo correrlo

### 1. Clonar el repo e instalar dependencias

```bash
git clone https://github.com/FakeJohnG/Proyect_pizza
cd proyect_pizza
pip install -r requirements.txt
```

### 2. Configurar la API key de Gemini (para el chatbot "Bob")

El dashboard incluye un chatbot que responde preguntas sobre los datos usando Gemini. Para funcionar necesita una API key de google:

- **Para correr local:** creá un archivo `API_KEY.env` en la raíz del proyecto con una línea:
  ```
  key=TU_API_KEY_DE_GEMINI
  ```
  (este archivo está en `.gitignore`, nunca se sube al repo)

- **Para producción (Streamlit Cloud):** configurá el secret `GOOGLE_API_KEY` desde el panel de la app en Streamlit Cloud.

Si no se configura ninguna key, el resto del dashboard funciona igual — solo que el chatbot quedara inoperativo

### 3. Correr la app

```bash
streamlit run main.py
```

Se abre en `http://localhost:8501`.

---

## Estructura del repo

```
proyect_pizza/
├── datos/                      # Los 4 CSV proporcionados del reto
├── assets/
│   └── barrio_logo.jpg
├── logic.py                    # Toda la lógica de negocio (BACKEND)
├── main.py                     # Interfaz Streamlit (FRONTEND)
├── requirements.txt
├── API_KEY.env                 # (no versionado) tu API key de Gemini
└── README.md
```

`logic.py` es independiente de Streamlit a propósito: recibe y devuelve DataFrames de pandas, para poder testearlo sin levantar la interfaz.

---

## Qué hace el dashboard

**Pestaña Alertas:**
- KPIs de resumen (alertas totales, por tipo)
- Filtro por sucursal
- Alertas agrupadas por severidad (alta / leve), con las de menor severidad atenuadas visualmente
- Ingredientes pedidos que no están en el catálogo, marcados aparte para revisión manual
- Detalle expandible con los números crudos (proyección, stock, pedido, diferencia)

**Pestaña Ordenes:**
- Tabla editable de la orden de la semana por sucursal, con indicador de qué ingredientes tienen un problema pendiente y de qué tipo
- Botón para confirmar los cambios y recalcular las alertas al instante
- Pedido corregido (según la proyección, no lo que pidieron con errores), agrupado por proveedor y listo para copiar/reenviar

**Chatbot "Bob" (sidebar, visible en todas las pestañas):**
- Responde preguntas en español sobre el estado actual de los datos (catálogo, alertas, proyecciones), usando Gemini con el contexto de datos armado en vivo

---

## Supuestos que hice

- **Proyección de consumo:** uso la **mediana** de las 6 semanas de histórico, no el promedio. Encontré un caso real en los datos (Marbella/pepperoni: 150kg en una semana vs. ~29kg el resto) donde un promedio simple habría inflado la proyección en ~67% y generado una alerta falsa. La mediana ignora ese tipo de outliers sin necesidad de detectarlos explícitamente.

- **Redondeo:** un excedente **menor** a un formato de compra completo no se considera sobre-pedido (es redondeo normal, tal como aclara el reto). El corte es `>=` un formato exacto, no `>`.

- **Riesgo de quiebre — severidad:** cualquier déficit genera alerta, pero si es menor a un formato completo lo marco como severidad "leve" en vez de "alta", para no competir visualmente con los casos urgentes.

- **Faltante total:** si una sucursal consume un ingrediente habitualmente (tiene histórico) pero no lo pidió esta semana, se marca como faltante total — independientemente de lo que diga la comparación numérica pedido vs. necesidad (porque no hay pedido que comparar).

- **Ingredientes no catalogados:** si una sucursal pide algo que no está en `ingredientes.csv` (encontré el caso real de `aji_chombo` en Costa del Este), no se puede convertir a unidad base ni calcular una alerta de cantidad — se marca aparte como "revisar manualmente", sin inventar un formato de compra que no existe.

- **Detección de órdenes atípicas (extra):** comparo el ratio pedido/proyección de cada sucursal contra la mediana de las otras 3, normalizando por tamaño de sucursal (no cantidades crudas, que no son comparables entre sucursales). Solo marco un caso como atípico si no está ya cubierto por otra alerta, para no duplicar la misma señal dos veces.

- **Pedido corregido por proveedor (extra):** se calcula sobre la necesidad real proyectada, no sobre lo que la sucursal pidió — y se redondea siempre hacia **arriba** al formato completo más cercano (nunca se sugiere comprar de menos).

- **Edición de órdenes (extra):** los cambios se guardan en memoria durante la sesión del navegador (`st.session_state`), no se persisten en el CSV en disco. Si se recarga la página del todo, se pierde. En un sistema real esto se reemplazaría por escritura directa a la base de datos (ver sección de Odoo abajo).

---

## Cómo usé la IA

Durante el desarollo utilize a claude para discutir y codificar partes del proyecto:

- **Definición de requisitos e architectura:** Antes de empezar a codificar discutimos y establecimos cuales serian los requisitos funcionales del proyecto y como realizariamos el proyecto comparando los pros y contras de varias opciones. 
- **Exploración de datos:** Usé Claude para explorar los 4 CSV a fondo (unicidad de sucursales/ingredientes, nulos, outliers). Así encontramos casos reales que definieron decisiones de diseño -- el outlier de pepperoni en Marbella (que llevó a elegir mediana sobre promedio), el ingrediente no catalogado en Costa del Este, y el faltante total de mozzarella en Brisas del Golf.
- **Lógica de negocio (`logic.py`):** escrita de forma iterativa, función por función, revisando el resultado contra los datos reales en cada paso antes de seguir.
- **Interfaz:** diseñé primero en Figma, y usé eso como referencia para ir armando `main.py` en Streamlit iterativamente, iterando sobre capturas de pantalla de mi propia app corriendo.
- **ChatBot "Bob":** partí de código que ya tenía de otro proyecto (patrón de sidebar con `st.chat_message`) y lo adapté para que consulte el contexto de datos de este proyecto específico.
- **Pruebas y correciones de errores:** Utilize a Claude para realizar varias pruebas del proyecto asegurando que no se nos escapara ningun error critico.

---

## Cómo conectaría esto a Odoo en producción

Hoy la app lee 4 archivos CSV estáticos. En un negocio real se conectaria con la base de datos para conseguir toda la informacion necesaria. Para llevarlo a producción con un sistema como Odoo, los cambios principales serían:

1. **Reemplazar `logic.load_data()`** por consultas a la base de datos de Odoo (vía su API XML-RPC/JSON-RPC, o el módulo `odoo-rpc` de Python) en vez de `pd.read_csv()`.

2. **`orden_compra_semana`** vendría directo del módulo de compras de Odoo (`purchase.order`) en vez de un CSV subido a mano.

3. **La edición desde la pestaña Ordenes**  pasaría a escribir directamente a Odoo vía su API al confirmar, en vez de quedar en memoria del navegador -- así el cambio queda persistido y visible para cualquiera que abra el sistema, no solo en esa sesión.

4. **El botón "Actualizar alertas"** podría eliminarse a favor de recálculo en tiempo real o programado  acercándose a la visión del reto de "cargar todas las órdenes de la semana y ver las alertas al instante".

5. **Autenticación real** reemplazando el "Bienvenido Jefe" genérico actual, usando el sistema de usuarios de Odoo.
