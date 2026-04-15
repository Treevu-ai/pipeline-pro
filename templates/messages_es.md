# Plantillas de mensajes — Español LatAm

> **Variables disponibles:**
> - `{PRODUCT}` — nombre del producto (p. ej. `Pipeline_X`)
> - `{company}` — nombre de la empresa del lead
> - `{contact_name}` — nombre del contacto (usar "Equipo de [empresa]" si no se conoce)
> - `{tu_nombre}` — nombre del remitente
> - `{cargo}` — cargo del remitente
> - `{tel}` — teléfono / WhatsApp del remitente
>
> **Firma por defecto:** `Equipo Pipeline_X`

---

## 1. Email formal

**Canal:** `email` | **Tono:** Formal (usted) | **Uso:** Primer contacto B2B profesional

**Asunto:**
```
{PRODUCT}: automatice la prospección de {company} hoy
```

**Cuerpo:**
```
Estimado equipo de {company},

Mi nombre es {tu_nombre}, {cargo} en {PRODUCT}.

Nos comunicamos porque empresas del sector de {company} están usando {PRODUCT} para automatizar la búsqueda y calificación de clientes potenciales — ahorrando hasta 80 % del tiempo en prospección manual.

{PRODUCT} encuentra negocios reales en Google Maps, los califica con IA y redacta mensajes de primer contacto personalizados por industria. Todo en minutos, sin necesidad de contratar más personal.

¿Podemos agendar 20 minutos esta semana para mostrarle cómo funciona?

Quedo a su disposición.

{tu_nombre}
{cargo} | {PRODUCT}
{tel}
```

---

## 2. Email informal

**Canal:** `email` | **Tono:** Informal (tú) | **Uso:** Primer contacto en sectores tech, startups o cuando el lead usa tono relajado

**Asunto:**
```
¿{company} ya automatizó su prospección?
```

**Cuerpo:**
```
Hola, equipo de {company},

Soy {tu_nombre} de {PRODUCT}.

Vi que {company} tiene una buena presencia en Google Maps y quería contarte cómo otras empresas de tu sector están usando {PRODUCT} para encontrar y calificar clientes nuevos en piloto automático.

En lugar de buscar leads manualmente, {PRODUCT} lo hace por ti: encuentra negocios en Google Maps, los filtra por industria y redacta el primer mensaje. Tú solo revisas y envías.

¿Te animas a una llamada de 20 minutos esta semana?

Saludos,
{tu_nombre}
{cargo} | {PRODUCT}
{tel}
```

---

## 3. WhatsApp corto

**Canal:** `whatsapp` | **Tono:** Directo, informal | **Límite:** ~80 palabras | **Uso:** Primer contacto por WhatsApp (frío o semi-cálido)

```
Hola 👋 Soy {tu_nombre} de *{PRODUCT}*.

Vi que {company} tiene una gran presencia en Maps. ¿Ya están prospectando clientes nuevos de forma automática?

{PRODUCT} encuentra negocios en Google Maps, los califica con IA y redacta el primer mensaje por ustedes. En minutos, no horas.

¿Les parece si coordinamos 20 min esta semana para mostrarles? 🚀

— Equipo Pipeline_X
```

---

## 4. WhatsApp detallado

**Canal:** `whatsapp` | **Tono:** Semi-formal | **Límite:** ~150 palabras | **Uso:** Seguimiento o lead que ya mostró interés inicial

```
Hola {contact_name} 👋

Te escribo de *{PRODUCT}*. Anteriormente te habíamos contactado sobre cómo automatizar la prospección de {company}.

Quería compartirte cómo funciona en la práctica:

✅ Encuentra empresas cliente en Google Maps por sector y zona
✅ Las califica automáticamente con IA (score 0–100)
✅ Redacta el mensaje de primer contacto por ti
✅ Genera un pipeline limpio con etapas CRM listo para usar

Todo esto en minutos, sin contratar más personal de ventas.

¿Tienen 20 minutos esta semana para verlo en vivo? Puedo compartirte un demo con datos reales de tu sector.

Saludos,
*{tu_nombre}*
{cargo} | {PRODUCT}
📞 {tel}

— Equipo Pipeline_X
```

---

## Notas de uso

- **Perú:** Usar **usted** en email formal; se puede tutear en WhatsApp si el lead es informal.
- **Colombia:** Preferir **usted** en todos los canales B2B formales.
- **México:** **Tú** es aceptable en tecnología y startups; **usted** en construcción, salud y gobierno.
- Para personalizar el CTA, reemplazar la frase final con el CTA definido en `config.PRODUCT["cta"]`.
- La firma por defecto es `Equipo Pipeline_X`; reemplazar `{tu_nombre}` y `{cargo}` con datos reales antes de enviar.
