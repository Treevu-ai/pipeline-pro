"""
messages.py — Fuente única de verdad para los textos del bot WhatsApp.

Por qué centralizar:
  - Un solo lugar para editar copy sin tocar lógica de wa_bot.py
  - Preparación para i18n: si el día de mañana hay versión en inglés,
    solo hay que agregar MSG_EN y un selector de idioma.
  - Evita strings hardcodeados dispersos en 3+ archivos.

Uso:
    from messages import MSG
    MSG["search_start"].format(target="Ferreterías en Trujillo")
"""
from __future__ import annotations

MSG: dict[str, str] = {
    # ── Flujo de búsqueda ─────────────────────────────────────────────────────
    "search_start": (
        "🔍 Buscando *{target}*...\n\n"
        "Esto suele tomar unos *2 minutos* ⏱️\n"
        "Mientras tanto, la mayoría de usuarios que usan este servicio "
        "consiguen contactar varios prospectos el mismo día o al siguiente.\n\n"
        "¿Te incluyo *mensajes sugeridos* listos para copiar y enviar por WhatsApp? (Sí / No)"
    ),
    "qualify_progress": (
        "🔎 *{name}*, ya estoy revisando las fuentes actualizadas...\n"
        "Estoy seleccionando solo negocios reales y verificados para ti."
    ),
    "pipeline_running": (
        "⏳ *{name}*, ya estoy revisando las fuentes actualizadas...\n"
        "Estoy seleccionando solo negocios reales y verificados para ti."
    ),
    "pdf_attaching": (
        "\n📎 Adjuntando tu reporte en PDF..."
    ),
    "report_download_ready": (
        "📄 Tu reporte está listo para descargar:\n"
        "{url}\n\n"
        "Código de descarga: {code} (vence en {expires})."
    ),

    # ── Validación de target ──────────────────────────────────────────────────
    "target_too_short": (
        "Necesito más detalle 😊\nEj: *\"Ferreterías en Trujillo\"*"
    ),
    "target_no_location": (
        "¿En qué zona o ciudad? 📍\n\n"
        "Ejemplo: *\"Ferreterías en Miraflores\"* o *\"Clínicas Lima\"*\n\n"
        "Con la ciudad los resultados son más precisos."
    ),
    "ask_target": (
        "¿Qué tipo de empresas quieres prospectar?\n\n"
        "Escribe industria + ciudad:\n"
        "_\"Ferreterías en Trujillo\"_ · _\"Clínicas en Lima\"_"
    ),

    # ── Errores ───────────────────────────────────────────────────────────────
    "error_no_results": (
        "⚠️ No pudimos obtener resultados para esa búsqueda.\n"
        "Intenta con un rubro y ciudad más específicos, por ejemplo:\n"
        "_Ferretería Lima_ o _Restaurante Miraflores_"
    ),
    "error_pipeline": (
        "❌ Hubo un error procesando tu búsqueda.\n"
        "Escribe de nuevo el rubro y ciudad para reintentar."
    ),
    "error_pdf": (
        "⚠️ Tuve un problema generando el PDF.\n\n"
        "Pero puedo enviártelo por Telegram 👇\n\n"
        "1. Abre: t.me/Pipeline_X_Bot\n"
        "2. Escribe /start\n"
        "3. Envía tu búsqueda ahí\n\n"
        "🚀 Y recibirás el reporte instantáneo."
    ),

    # ── Upgrade / planes ─────────────────────────────────────────────────────
    "upgrade_intro": (
        "¡Perfecto! 🙌\n\n"
        "Un agente de *Pipeline_X* se pondra en contacto contigo "
        "en los proximos minutos.\n\n"
        "Si prefieres activar ahora mismo, puedes pagar por:\n\n"
        "{bank_info}\n\n"
        "📸 Envia tu comprobante aqui y activamos tu acceso al instante."
    ),
    "upgrade_no_bank": (
        "¡Perfecto! 🙌\n\n"
        "Un agente de *Pipeline_X* se pondrá en contacto contigo "
        "en los próximos minutos para ayudarte con la activación.\n\n"
        "También puedes escribirnos directamente a:\n"
        "📧 contacto@pipelinex.app"
    ),
    "upgrade_ceo_alert": (
        "🔔 *Usuario quiere hacer upgrade*\n\n"
        "📱 Tel: `{phone}`\n"
        "💰 Plan solicitado: Starter (S/129/mes)\n"
        "🕐 Hora: {time}\n\n"
        "Contáctalo en los próximos minutos."
    ),

    # ── Trial ────────────────────────────────────────────────────────────────
    "trial_started": (
        "🎁 *¡Trial activado! 3 días de acceso completo.*\n\n"
        "✅ Reportes ilimitados · datos sin censura\n"
        "✅ Hasta 30 leads por búsqueda\n"
        "✅ Validación SUNAT incluida\n\n"
        "Empieza ahora — dime rubro y ciudad 👇"
    ),
    "trial_ceo_alert": (
        "🧪 *Trial activado*\n\n"
        "📱 `{phone}`\n"
        "⏳ Expira en 3 días\n"
        "🕐 {time}"
    ),

    # ── Suscriptores ─────────────────────────────────────────────────────────
    "subscriber_welcome": (
        "🎉 ¡Tu acceso *Plan {plan}* está activo!\n\n"
        "✅ Reportes ilimitados · todos los datos sin censura\n"
        "✅ Validación SUNAT incluida\n"
        "✅ Acceso por *{days}*\n\n"
        "Escríbeme el rubro y ciudad que quieres prospectar y empezamos ahora mismo 🚀"
    ),

    # ── Feedback ─────────────────────────────────────────────────────────────
    "feedback_ask": (
        "¿Qué tan útil fue el reporte? 🌟"
    ),
    "feedback_thanks_good": (
        "¡Qué bueno! 🙌 Me alegra que haya sido útil.\n"
        "Cuando quieras otro reporte, solo dime rubro y ciudad."
    ),
    "feedback_thanks_ok": (
        "Gracias por el feedback 👍 Seguimos mejorando.\n\n"
        "Cuando quieras otro reporte, solo dime rubro y ciudad."
    ),
    "feedback_thanks_bad": (
        "Gracias por ser honesto 🙏 Tomamos nota.\n\n"
        "Cuando quieras otro reporte, dime rubro y ciudad y lo mejoramos."
    ),

    # ── Check 2h post-PDF ────────────────────────────────────────────────────
    "report_check_2h": (
        "👋 {name}, ¿ya revisaste tu reporte?\n\n"
        "Si tienes alguna duda sobre los negocios que encontramos, o quieres "
        "ajustar el rubro o la zona, aquí estoy 👇"
    ),

    # ── Followup 24h ─────────────────────────────────────────────────────────
    "followup_24h": (
        "👋 Hola {name}, soy Pipeline_X de nuevo.\n\n"
        "¿Pudiste contactar a los leads de *{target}* que te mandé ayer?\n\n"
        "Si quieres más prospectos o probar con otro rubro, "
        "con el plan *Starter (S/129/mes)* tienes reportes ilimitados 🚀\n\n"
        "Responde *demo* para una nueva búsqueda gratis "
        "o *upgrade* para activar tu plan."
    ),

    # ── Followup día 3 ─────────────────────────────────────────────────────────
    "followup_3d": (
        "Hola {name}, quería saber si el reporte de *{target}* te fue útil.\n\n"
        "Muchos dueños de negocios como tú empiezan a ver resultados concretos en la primera semana.\n\n"
        "Si quieres, puedo generarte otra lista gratuita en una zona o rubro diferente, "
        "o contarte los beneficios del Plan Starter para que tengas acceso ilimitado.\n\n"
        "¿En qué te puedo apoyar hoy?"
    ),

    # ── Trial expirado ───────────────────────────────────────────────────────
    "trial_expired": (
        "⏳ Tu trial de 3 días terminó. Esperamos que hayas comprobado el potencial.\n\n"
        "Hoy tienes *1 búsqueda gratis* disponible 👇\n\n"
        "Para seguir sin límites:\n"
        "• *Starter S/129/mes* — reportes ilimitados ⭐\n"
        "• *Pro S/299/mes* — 50 leads + API\n\n"
        "Responde *upgrade* para activar o escribe rubro + ciudad para tu búsqueda gratis."
    ),

    # ── Rate limiting ────────────────────────────────────────────────────────
    "daily_limit_reached": (
        "⏳ Ya usaste tu búsqueda gratuita de hoy.\n\n"
        "Con *Starter (S/129/mes)* tienes reportes ilimitados 🚀\n\n"
        "¿Quieres activar tu acceso?"
    ),
    "monthly_limit_reached": (
        "📊 Llegaste al límite mensual.\n\n"
        "Con *Starter (S/129/mes)* tienes reportes ilimitados 🚀\n\n"
        "¿Quieres hacer el upgrade?"
    ),

    # ── Captura de nombre ─────────────────────────────────────────────────────
    "ask_name": (
        "👋 Hola, soy *Pipeline_X*.\n"
        "¿Cómo te llamas?"
    ),
    "name_saved": (
        "Perfecto, {name} 👋\n\n"
        "Te ayudo a conseguir más clientes sin contratar a nadie.\n"
        "Dime a qué tipo de negocio le quieres vender y en qué ciudad — "
        "en minutos recibes aquí mismo una lista de prospectos listos para contactar."
    ),

    # ── Audio / imagen ────────────────────────────────────────────────────────
    "audio_not_supported": (
        "🎤 No puedo escuchar audios aún.\n"
        "Escríbeme el rubro y ciudad que buscas y te armo el reporte 👇"
    ),
    "image_received_upgrade": (
        "📸 ¡Comprobante recibido! ✅\n\n"
        "Estoy verificando tu pago ahora mismo. "
        "En menos de *30 minutos* te confirmo y activo tu acceso al Plan Starter.\n\n"
        "Mientras tanto puedes hacer una búsqueda de prueba — escríbeme rubro y ciudad 👇"
    ),
    "image_unknown": (
        "Recibí tu imagen, pero no sé qué hacer con ella 🤔\n"
        "¿Necesitas algo? Escríbeme."
    ),

    # ── Historial de búsquedas ────────────────────────────────────────────────
    "search_history_empty": (
        "Aún no tienes búsquedas registradas.\n\n"
        "Escríbeme rubro + ciudad para tu primera búsqueda 👇"
    ),
    "search_history": (
        "🕐 *Tus últimas búsquedas:*\n\n"
        "{items}\n\n"
        "Escribe cualquiera de nuevo o un rubro distinto 👇"
    ),

    # ── Unsubscribe ───────────────────────────────────────────────────────────
    "unsubscribed": (
        "✅ Listo, no te enviaré más mensajes proactivos.\n\n"
        "Si algún día quieres volver, solo escríbeme *hola* 👋"
    ),

    # ── Cancelación de plan ───────────────────────────────────────────────────
    "cancelar_plan_confirm": (
        "Entendido, {name}. Antes de confirmar la baja, ¿estás seguro?\n\n"
        "Tu plan *{plan}* estará activo hasta el *{expires}*.\n"
        "Después de esa fecha no se renovará automáticamente.\n\n"
        "Escribe *sí, cancelar* para confirmar, o cualquier otra cosa para mantener tu plan."
    ),
    "cancelar_plan_done": (
        "✅ Tu plan ha sido cancelado, {name}.\n\n"
        "Seguirás teniendo acceso hasta el *{expires}*.\n"
        "Cuando quieras volver, escríbeme y te reactivamos en minutos 👋"
    ),
    "cancelar_plan_no_activo": (
        "No tienes un plan activo en este momento, {name}.\n\n"
        "Si quieres probar Pipeline_X, escribe *upgrade* para ver los planes."
    ),

    # ── Error recovery de pipeline ────────────────────────────────────────────
    "pipeline_error_retry": (
        "⚠️ Hubo un problema con esa búsqueda.\n"
        "Escríbeme de nuevo el rubro y ciudad para reintentar."
    ),
    "pipeline_error_final": (
        "❌ No pudimos procesar esa búsqueda.\n"
        "Escríbenos a *contacto@pipelinex.app*"
    ),

    # ── Ciudad por defecto ────────────────────────────────────────────────────
    "confirm_default_city": (
        "¿Buscamos en *{city}* otra vez, o prefieres otra ciudad?\n\n"
        "Responde *sí* para {city} o escribe otra ciudad."
    ),

    # ── Opciones post-PDF ───────────────────────────────────────────────────
    "post_pdf_options": (
        "¿En qué te puedo ayudar en este momento, {name}?\n\n"
        "A. Cómo usar la lista de manera efectiva\n"
        "B. Buscar otra ciudad o rubro\n"
        "C. Ver los planes y precios\n"
        "D. Nada por ahora, gracias"
    ),
    "post_pdf_option_a": (
        "📋 *Cómo usar la lista:*\n\n"
        "1. Abre el PDF que te/envié\n"
        "2. Copia el mensaje sugerido de cada empresa\n"
        "3. Envíalo por WhatsApp directo al negocio\n"
        "4. Repite con los que te interesen\n\n"
        "💡 *Tip:* Los primeros 5 contactos suelen ser los más importantes. "
        "Dedica tiempo a personalizar el mensaje si puedes.\n\n"
        "¿Quieres hacer algo más? (nueva búsqueda / precios / nada)"
    ),
    "post_pdf_option_b": (
        "Entendido. Solo dime el nuevo rubro y ciudad que buscas 👇\n\n"
        "Ejemplos:\n"
        "• Restaurantes en Miraflores\n"
        "• Talleres mecánicos en Arequipa\n"
        "• Clínicas dentales en Lima"
    ),
    "post_pdf_option_c": (
        "💰 *Planes Pipeline_X*\n\n"
        "• Free — S/0 · 10 leads demo\n"
        "• *Starter — S/129/mes* · ilimitado ⭐\n"
        "• Pro — S/299/mes · 50 leads + API\n\n"
        "Tienes 7 días de prueba sin tarjeta. ¿Quieres activar el plan Starter?"
    ),
    "post_pdf_option_d": (
        "Perfecto, {name} 👋\n\n"
        "Gracias por probar Pipeline_X. Cuando quieras más prospectos, "
        "solo escríbeme.\n\n"
        "Que te vaya muy bien con tus ventas! 🚀"
    ),

    # ── Upsell post-gusto ───────────────────────────────────────────────────
    "me_gusto_upfront": (
        "¡Qué bueno saberlo, {name}! Me alegra mucho que la lista te haya sido útil. 👍\n\n"
        "Eso es exactamente lo que buscamos: ahorrarte tiempo y darte contactos reales "
        "para que puedas enfocarte en vender.\n\n"
        "Si te gustaría seguir recibiendo listas de forma ilimitada y con más volumen, "
        "el *Plan Starter a S/129/mes* es la opción que más recomiendo para la mayoría "
        "de micro y pequeñas empresas.\n\n"
        "¿Quieres que te active el plan o prefieres probar primero con una búsqueda adicional?"
    ),

    # ── Objeciones ───────────────────────────────────────────────────────────
    "objecion_es_caro": (
        "Entiendo perfectamente tu preocupación, {name}.\n\n"
        "La realidad es que el tiempo que ahorras buscando manualmente vale mucho más. "
        "Con Pipeline_X obtienes contactos listos para usar en minutos, no horas.\n\n"
        "Además, puedes probar con *7 días sin tarjeta* y ver si te funciona antes de pagar.\n\n"
        "¿Qué te parece si activamos el trial y lo pruebas?"
    ),
    "objecion_ya_tengo": (
        "¡Excelente! Entonces ya sabes lo importante que es tener buenos prospectos. 👍\n\n"
        "La diferencia con Pipeline_X es que *te ahorras todo el trabajo manual* de buscar, "
        "validar y organizar los datos. En minutos tienes una lista limpia y lista para usar.\n\n"
        "¿Usas algún método en particular hoy? Quizás te puedo mostrar cómo sería con nosotros."
    ),
    "objecion_no_me_sirve": (
        "Lamento mucho que no cumpla con lo que necesitas, {name}. 🙁\n\n"
        "¿Me podrías contar qué esperabas o qué te faltó? Tu feedback nos ayuda a mejorar.\n\n"
        "Mientras tanto, si hay algo específico que pueda hacer por ti ahora, "
        "dime y con gusto te ayudo."
    ),
}
