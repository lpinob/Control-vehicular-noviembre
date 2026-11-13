
import streamlit as st
import requests
import re
import uuid
from supabase import create_client

# ======================================
# CONFIGURACION
# ======================================

st.set_page_config(
    page_title="Control Vehicular",
    page_icon="🚗",
    layout="wide"
)

supabase = create_client(
    st.secrets["supabase"]["SUPABASE_URL"],
    st.secrets["supabase"]["SUPABASE_KEY"]
)

OCR_KEY = st.secrets["ocr"]["API_KEY"]
BUCKET = "evidencias-vehiculos"


# ======================================
# FUNCIONES
# ======================================

def normalizar(texto):
    return re.sub(r"[^A-Z0-9]", "", str(texto).upper())


def limpiar_patente(texto):
    patente = normalizar(texto)
    if len(patente) == 6:
        return patente[:4] + "-" + patente[4:]
    return patente


def consultar_tabla(tabla):
    return supabase.table(tabla).select("*").execute().data


def reconocer_patente(foto):
    try:
        respuesta = requests.post(
            "https://api.ocr.space/parse/image",
            files={
                "file": (
                    "patente.jpg",
                    foto.getvalue(),
                    "image/jpeg"
                )
            },
            data={
                "apikey": OCR_KEY,
                "language": "eng",
                "OCREngine": "2"
            },
            timeout=30
        )
        respuesta.raise_for_status()
        datos = respuesta.json()

        if datos.get("IsErroredOnProcessing"):
            st.error(str(datos.get("ErrorMessage")))
            return ""

        texto = " ".join(
            r.get("ParsedText", "")
            for r in datos.get("ParsedResults", [])
        )

        return limpiar_patente(texto)

    except Exception as e:
        st.error(f"Error OCR: {e}")
        return ""


def buscar_vehiculo(patente):
    vehiculos = consultar_tabla("vehiculos")
    for v in vehiculos:
        if normalizar(v["patente"]) == normalizar(patente):
            return v
    return None


def conductores_autorizados(patente):
    autorizaciones = consultar_tabla("autorizaciones")
    conductores = consultar_tabla("conductores")

    ruts = {
        a["rut_conductor"]
        for a in autorizaciones
        if normalizar(a["patente"]) == normalizar(patente)
        and a["vigente"] is True
    }

    return [
        c for c in conductores
        if c["rut"] in ruts
        and c["estado"] == "Activo"
    ]


# ======================================
# ESTADO
# ======================================

if "patente" not in st.session_state:
    st.session_state["patente"] = ""

if "consulta" not in st.session_state:
    st.session_state["consulta"] = None


def borrar_consulta():
    st.session_state["consulta"] = None


# ======================================
# MENU LATERAL
# ======================================

st.sidebar.title("🚗 Control Vehicular")

pagina = st.sidebar.radio(
    "Seleccione una pagina",
    ["Guardia", "Conductor", "Administrador"],
    key="menu_principal"
)

st.sidebar.caption("Sistema de Control de Flota")


# ======================================
# PAGINA 1 - GUARDIA
# ======================================

if pagina == "Guardia":

    st.title("Control de Acceso Vehicular")

    st.subheader("Lectura OCR de Patente")

    foto = st.camera_input(
        "Fotografiar patente",
        key="camara_guardia"
    )

    if foto is not None:
        if st.button("Reconocer patente"):
            with st.spinner("Procesando imagen..."):
                patente_ocr = reconocer_patente(foto)

            if patente_ocr:
                st.session_state["patente"] = patente_ocr
                borrar_consulta()
                st.success(
                    f"Patente detectada: {patente_ocr}"
                )
            else:
                st.warning("Ingrese la patente manualmente")

    st.text_input(
        "Patente del vehiculo",
        key="patente",
        on_change=borrar_consulta
    )

    if st.button("Consultar autorizacion"):

        patente = limpiar_patente(
            st.session_state["patente"]
        )

        borrar_consulta()

        if not patente:
            st.warning("Ingrese una patente")

        else:
            try:
                vehiculo = buscar_vehiculo(patente)

                if vehiculo is None:
                    st.session_state["consulta"] = {
                        "vehiculo": None,
                        "conductores": []
                    }
                else:
                    conductores = conductores_autorizados(
                        vehiculo["patente"]
                    )

                    st.session_state["consulta"] = {
                        "vehiculo": vehiculo,
                        "conductores": conductores
                    }

            except Exception as e:
                st.error(f"Error de consulta: {e}")

    resultado = st.session_state["consulta"]

    if resultado is not None:

        vehiculo = resultado["vehiculo"]
        conductores = resultado["conductores"]

        if vehiculo is None:
            st.error("ACCESO DENEGADO: Vehiculo no registrado")

        else:
            st.subheader("Datos del Vehiculo")

            st.write("Patente:", vehiculo["patente"])
            st.write("Modelo:", vehiculo["marca_modelo"])
            st.write("Tipo:", vehiculo["tipo_vehiculo"])
            st.write(
                "Estado operativo:",
                vehiculo["estado_operativo"]
            )

            if not conductores:
                st.error(
                    "ACCESO DENEGADO: Sin conductor "
                    "activo con autorizacion vigente"
                )

            else:
                opciones = {
                    c["rut"]: c
                    for c in conductores
                }

                rut = st.selectbox(
                    "Conductor presente",
                    list(opciones.keys()),
                    format_func=lambda r: (
                        opciones[r]["nombre_completo"]
                        + " - " + r
                    ),
                    key="conductor_guardia"
                )

                conductor = opciones[rut]

                st.write(
                    "Nombre:",
                    conductor["nombre_completo"]
                )
                st.write(
                    "Grado/Cargo:",
                    conductor["grado_o_cargo"]
                )
                st.write(
                    "Unidad:",
                    conductor["unidad_destino"]
                )

                st.success(
                    "AUTORIZACION VIGENTE PARA "
                    "EL CONDUCTOR SELECCIONADO"
                )

                st.info(
                    "Verifique presencialmente la identidad "
                    "del conductor antes de permitir el acceso."
                )


# ======================================
# PAGINA 2 - CONDUCTOR
# ======================================

elif pagina == "Conductor":

    st.title("Inspeccion Vehicular")

    try:
        vehiculos = consultar_tabla("vehiculos")
        conductores = consultar_tabla("conductores")
        autorizaciones = consultar_tabla("autorizaciones")

        if not vehiculos:
            st.warning("No hay vehiculos disponibles")
            st.stop()

        patentes = sorted(
            [v["patente"] for v in vehiculos]
        )

        patente = st.selectbox(
            "Seleccione la patente",
            patentes
        )

        ruts_autorizados = {
            a["rut_conductor"]
            for a in autorizaciones
            if normalizar(a["patente"]) == normalizar(patente)
            and a["vigente"] is True
        }

        disponibles = [
            c for c in conductores
            if c["rut"] in ruts_autorizados
            and c["estado"] == "Activo"
        ]

        if not disponibles:
            st.error(
                "No hay conductores activos autorizados "
                "para este vehiculo"
            )
            st.stop()

        opciones = {
            c["rut"]: c for c in disponibles
        }

        with st.form("formulario_conductor"):

            rut = st.selectbox(
                "Conductor",
                list(opciones.keys()),
                format_func=lambda r: (
                    opciones[r]["nombre_completo"]
                    + " - " + r
                )
            )

            kilometraje = st.number_input(
                "Kilometraje de salida",
                min_value=0,
                step=1
            )

            combustible = st.slider(
                "Nivel de combustible (%)",
                0, 100, 50
            )

            neumaticos = st.radio(
                "Estado de neumaticos",
                ["Correctos", "Baja presion"]
            )

            luces = st.radio(
                "Estado de luces",
                ["Operativas", "Con fallas"]
            )

            observaciones = st.text_area(
                "Novedades mecanicas"
            )

            foto = st.file_uploader(
                "Fotografia de evidencia",
                type=["jpg", "jpeg", "png"]
            )

            guardar = st.form_submit_button(
                "Guardar reporte"
            )

        if guardar:

            if foto is None:
                st.warning(
                    "Adjunte una fotografia de evidencia"
                )

            elif foto.size > 5 * 1024 * 1024:
                st.error("La fotografia supera los 5 MB")

            else:
                try:
                    extension = (
                        foto.name.rsplit(".", 1)[-1].lower()
                    )

                    tipo = (
                        "image/png"
                        if extension == "png"
                        else "image/jpeg"
                    )

                    ruta = (
                        normalizar(patente)
                        + "/"
                        + str(uuid.uuid4())
                        + "."
                        + extension
                    )

                    # Subir fotografia a Storage privado
                    supabase.storage.from_(BUCKET).upload(
                        path=ruta,
                        file=foto.getvalue(),
                        file_options={
                            "content-type": tipo,
                            "upsert": "false"
                        }
                    )

                    # Registrar inspeccion
                    reporte = {
                        "patente": patente,
                        "rut_conductor": rut,
                        "kilometraje_salida": int(kilometraje),
                        "nivel_combustible": int(combustible),
                        "presion_neumaticos": (
                            neumaticos == "Correctos"
                        ),
                        "luces_operativas": (
                            luces == "Operativas"
                        ),
                        "observaciones": observaciones,
                        "foto_evidencia_url": ruta
                    }

                    try:
                        supabase.table(
                            "reportes_estado"
                        ).insert(reporte).execute()

                    except Exception:
                        # Eliminar la foto si falla el registro
                        try:
                            supabase.storage.from_(
                                BUCKET
                            ).remove([ruta])
                        except Exception:
                            pass
                        raise

                    st.success(
                        "Reporte guardado correctamente"
                    )

                except Exception as e:
                    st.error(
                        f"No se pudo guardar el reporte: {e}"
                    )

    except Exception as e:
        st.error(f"Error: {e}")


# ======================================
# PAGINA 3 - ADMINISTRADOR
# ======================================


# ======================================
# PAGINA 3 - ADMINISTRADOR
# ======================================

elif pagina == "Administrador":

    st.title("Cuadro de Mando de la Flota")

    try:
        vehiculos = consultar_tabla("vehiculos")
        reportes = consultar_tabla("reportes_estado")

        total = len(vehiculos)

        operativos = sum(
            v["estado_operativo"] == "Operativo"
            for v in vehiculos
        )

        mantenimiento = sum(
            v["estado_operativo"] == "Requiere Mantención"
            for v in vehiculos
        )

        criticos = sum(
            v["estado_operativo"] == "Crítico"
            for v in vehiculos
        )

        apresto = (
            round(operativos / total * 100, 1)
            if total > 0 else 0
        )

        # INDICADORES
        st.subheader("Indicadores de la Flota")

        c1, c2, c3, c4 = st.columns(4)

        c1.metric("Total Vehículos", total)
        c2.metric("Operativos", operativos)
        c3.metric("Mantención", mantenimiento)
        c4.metric("Críticos", criticos)

        st.metric(
            "Apresto Operacional",
            f"{apresto}%"
        )

        # ESTADO DE VEHICULOS
        st.subheader("Estado Operacional")

        for v in vehiculos:

            st.write(
                f'{v["patente"]} | '
                f'{v["marca_modelo"]} | '
                f'{v["estado_operativo"]}'
            )

        # ALERTAS
        st.subheader("Alertas Mecánicas")

        alertas = 0

        for v in vehiculos:

            if v["estado_operativo"] != "Operativo":

                st.warning(
                    f'{v["patente"]} - '
                    f'{v["estado_operativo"]}'
                )

                alertas += 1

        if alertas == 0:
            st.success("No existen alertas operacionales")

        # HISTORIAL
        st.subheader("Historial de Inspecciones")

        reportes = sorted(
            reportes,
            key=lambda r: r.get("fecha_reporte") or "",
            reverse=True
        )

        st.write(
            "Total de reportes registrados:",
            len(reportes)
        )

        for r in reportes:

            with st.expander(
                f'{r["patente"]} - '
                f'{r["fecha_reporte"]}'
            ):

                st.write(
                    "Conductor:",
                    r["rut_conductor"]
                )

                st.write(
                    "Kilometraje:",
                    r["kilometraje_salida"]
                )

                st.write(
                    "Combustible:",
                    str(r["nivel_combustible"]) + "%"
                )

                st.write(
                    "Neumáticos:",
                    "Correctos"
                    if r["presion_neumaticos"]
                    else "Baja presión"
                )

                st.write(
                    "Luces:",
                    "Operativas"
                    if r["luces_operativas"]
                    else "Con fallas"
                )

                st.write(
                    "Observaciones:",
                    r["observaciones"]
                )

                if (
                    r["presion_neumaticos"] is False
                    or r["luces_operativas"] is False
                ):
                    st.error(
                        "ALERTA: Falla mecánica detectada"
                    )

    except Exception as e:
        st.error(f"Error del administrador: {e}")