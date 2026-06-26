# Bot Agencias — Panel multi-sucursal con asistente comercial por WhatsApp

Sistema web para agencias automotrices que combina un **dashboard de gestión multi-sucursal** con un **bot comercial inteligente** conectado a **WhatsApp Cloud API** y **Google Gemini**. Cada sucursal puede tener su propio equipo de vendedores, inventario, leads y citas, con respuestas personalizadas según la línea de WhatsApp que contacte el cliente.

**Repositorio:** [github.com/Javierlw60/Bot-Agencia](https://github.com/Javierlw60/Bot-Agencia) · **Release estable:** [v1.0.0](https://github.com/Javierlw60/Bot-Agencia/releases/tag/v1.0.0)

---

## Características principales

### Dashboard de gestión

- **Panel multi-sucursal** con navegación persistente y selector de sucursal activa.
- **Inventario** de vehículos por sucursal, con fotos y datos de preventa.
- **Leads** comerciales vinculados a conversaciones y autos de interés.
- **Citas y agenda:** vista en vivo (hoy / mañana), calendario mensual y buscador avanzado con filtro dinámico por vendedor.
- **Estados de cita:** Pendiente, En curso, Venta concretada, Venta perdida — con panel de desempeño, ranking y tasa de conversión (semanal, mensual, anual).
- **Equipo de ventas:** jerarquía Agencia → Sucursal → Vendedor, con identidad del bot configurable (nombre, color, logo, línea).
- **Enlaces directos a WhatsApp** (`wa.me`) desde citas y ranking cuando hay teléfono válido.
- **Autenticación del panel** con verificación por correo y **2FA opcional por WhatsApp**.
- **Suscripciones** con integración Mercado Pago y bloqueo automático por vencimiento.

### Bot comercial (WhatsApp + Gemini)

- **WhatsApp Cloud API (Meta):** recepción y envío de mensajes reales vía Graph API, con webhook estándar en `GET/POST /webhook`.
- **Enrutamiento por vendedor:** los mensajes entrantes se asocian al vendedor/sucursal según el **Phone Number ID** de Meta configurado en cada línea.
- **Google Gemini:** motor conversacional que consulta el inventario en tiempo real, califica leads, gestiona permutas y agenda visitas respetando horarios comerciales y contexto temporal (incluye reglas para madrugada en Argentina).
- **Multimedia:** soporte de mensajes de **texto** y **audio** (transcripción STT + respuesta TTS con voces neurales en español).
- **Recordatorios automáticos** de citas mediante scheduler en segundo plano.
- **Modo consola** (`WHATSAPP_MODO=consola`) para desarrollo sin enviar mensajes reales.

---

## Requisitos

| Requisito | Detalle |
|-----------|---------|
| **Python** | 3.10 o superior |
| **SO** | Windows (scripts `.bat` incluidos) o cualquier entorno con Python |
| **Cuenta Meta** | App de WhatsApp Business + Phone Number ID y Access Token |
| **Google AI** | API Key de Gemini (`GEMINI_API_KEY`) |
| **Opcional** | OpenAI (Whisper STT), Mercado Pago, SMTP para correo |

---

## Variables de entorno (`.env`)

Copiá `.env.example` a `.env` en la raíz del proyecto. **No subas `.env` a Git** — contiene secretos.

### Obligatorias para arrancar

| Variable | Descripción |
|----------|-------------|
| `AUTH_SECRET_KEY` | Clave secreta para sesiones del panel (se genera sola al instalar) |
| `GEMINI_API_KEY` | Clave de la API de Google Gemini |
| `DASHBOARD_BASE_URL` | URL pública del panel (ej. `http://127.0.0.1:8080` en local) |

### WhatsApp Cloud API (producción)

| Variable | Descripción |
|----------|-------------|
| `WHATSAPP_MODO` | `api` = mensajes reales · `consola` = simulación |
| `WHATSAPP_ACCESS_TOKEN` | Access Token de Meta Graph API |
| `WHATSAPP_PHONE_NUMBER_ID` | **Phone Number ID** de Meta (no es el número `549…`) |
| `WHATSAPP_VERIFY_TOKEN` | Token que definís vos; debe coincidir con el webhook en Meta |
| `AUTH_WHATSAPP_PHONE_NUMBER_ID` | Línea para códigos 2FA del panel (puede ser la misma) |

Alias aceptados: `WHATSAPP_TOKEN`, `PHONE_NUMBER_ID`, `VERIFY_TOKEN`.

### Opcionales

- **Recordatorios:** `RECORDATORIOS_ACTIVOS`, `RECORDATORIOS_INTERVALO_MIN`
- **Voz:** `TTS_VOZ`, `TTS_MAX_CARACTERES`, `OPENAI_API_KEY`, `STT_MOTOR`, `STT_IDIOMA`
- **Mercado Pago:** `MERCADOPAGO_ACCESS_TOKEN`, `MERCADOPAGO_USER_ID`, etc.
- **SMTP:** `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD` (si no hay SMTP, los enlaces de verificación se imprimen en consola)

Consultá `.env.example` para la lista completa y comentarios de cada variable.

---

## Instalación y ejecución

### Opción rápida (Windows)

```bat
setup.bat
Iniciar_APP.bat
```

`setup.bat` crea el entorno virtual, instala dependencias, inicializa la base de datos y el usuario administrador.  
`Iniciar_APP.bat` levanta el servidor en **http://127.0.0.1:8080**.

### Instalación manual

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
python scripts/instalar.py
uvicorn app:app --reload --port 8080
```

Tras la instalación, el script muestra las credenciales del administrador demo:

- **Email:** `admin@demo.local`
- **Contraseña:** `Demo1234` (cambiar en producción)

Panel: **http://127.0.0.1:8080/auth/login**

### Health check

```bash
curl http://127.0.0.1:8080/health
```

Respuesta esperada: `status: ok`, rutas de webhook y servicios activos.

---

## WhatsApp en desarrollo (ngrok)

1. Iniciá la app en el puerto **8080** (coincide con `Iniciar_APP.bat`).
2. Exponé el servidor con ngrok, por ejemplo: `ngrok http 8080`.
3. En Meta for Developers → WhatsApp → Configuration → Webhook:
   - **Callback URL:** `https://tu-subdominio.ngrok-free.app/webhook`
   - **Verify token:** el mismo valor que `WHATSAPP_VERIFY_TOKEN` en tu `.env`
4. En Configuración del panel, el campo de teléfono del vendedor debe ser el **Phone Number ID** de Meta, no el número de celular.

---

## Stack tecnológico

- **Backend:** FastAPI, SQLAlchemy, APScheduler
- **Frontend:** Jinja2 templates, assets estáticos
- **IA:** Google Gemini (`google-genai`)
- **Mensajería:** WhatsApp Cloud API (Meta Graph)
- **Voz:** edge-tts (TTS), OpenAI Whisper o faster-whisper (STT)
- **Pagos:** Mercado Pago (suscripciones)

---

## Estructura del proyecto

```
Bot Agencia/
├── app.py                 # Punto de entrada FastAPI
├── bot.py                 # Lógica conversacional + Gemini
├── api_whatsapp.py        # Webhook Meta y envío de mensajes
├── whatsapp_config.py     # Variables de entorno WhatsApp
├── dashboard/             # Rutas y lógica del panel
├── auth/                  # Login, registro, 2FA
├── models/                # Modelos SQLAlchemy
├── templates/             # Vistas HTML del dashboard
├── static/                # CSS, JS, uploads
├── scripts/instalar.py    # Instalación inicial
├── setup.bat              # Setup automático (Windows)
├── Iniciar_APP.bat        # Arranque del servidor
├── .env.example           # Plantilla de configuración
└── requirements.txt
```

---

## Licencia

Proyecto privado. Consultá al titular del repositorio para condiciones de uso y distribución.
