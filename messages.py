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
        "🔍 Buscando *{target}*...\n"
        "Esto toma ~2 minutos, no cierres el chat."
    ),
    "qualify_progress": (
        "🤖 Calificando leads con IA... ya casi termina."
    ),
    "pipeline_running": (
        "⏳ Tu reporte está en proceso, ya casi está listo..."
    ),
    "pdf_attaching": (
        "\n📎 Adjuntando tu reporte en PDF..."
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
    "ask_target_new": (
        "¿Qué tipo de empresas buscas ahora? 🔍\n\n"
        "Escribe industria + ciudad:\n"
        "_\"Restaurantes en San Isidro\"_ · _\"Clínicas en Trujillo\"_"
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
        "⚠️ Hubo un problema generando el PDF. "
        "Escríbenos a contacto@pipelinex.app"
    ),

    # ── Upgrade / planes ─────────────────────────────────────────────────────
    "upgrade_intro": (
        "¡Perfecto! 🙌\n\n"
        "Un agente de *Pipeline_X* se pondrá en contacto contigo "
        "en los próximos minutos.\n\n"
        "Si prefieres activar ahora mismo, puedes pagar por:\n\n"
        "{bank_info}\n\n"
        "📸 Envía tu comprobante aquí y activamos tu acceso al instante."
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
        "💰 Plan solicitado: Starter (S/149/mes)\n"
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
    "subscriber_next_search": (
        "¿Qué buscamos ahora? 🔍\n\n"
        "Escribe rubro + ciudad:\n"
        "_\"Restaurantes en San Isidro\"_ · _\"Clínicas en Trujillo\"_"
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
        "Gracias por el feedback 👍\n"
        "Seguimos mejorando. ¿Qué podría haber sido mejor?"
    ),
    "feedback_thanks_bad": (
        "Gracias por ser honesto 🙏\n"
        "¿Qué le faltó al reporte? Tu feedback nos ayuda a mejorar."
    ),

    # ── Followup 24h ─────────────────────────────────────────────────────────
    "followup_24h": (
        "👋 Hola, soy Pipeline_X de nuevo.\n\n"
        "¿Pudiste contactar a los leads del reporte de ayer?\n\n"
        "Si quieres más prospectos o probar con otro rubro, "
        "con el plan *Starter (S/149/mes)* tienes reportes ilimitados 🚀\n\n"
        "Responde *demo* para una nueva búsqueda gratis "
        "o *upgrade* para activar tu plan."
    ),

    # ── Trial expirado ───────────────────────────────────────────────────────
    "trial_expired": (
        "⏳ Tu trial de 3 días terminó. Esperamos que hayas comprobado el potencial.\n\n"
        "Hoy tienes *1 búsqueda gratis* disponible 👇\n\n"
        "Para seguir sin límites:\n"
        "• *Básico S/59/mes* — 10 reportes/mes, 20 leads full\n"
        "• *Starter S/149/mes* — reportes ilimitados ⭐\n\n"
        "Responde *upgrade* para activar o escribe rubro + ciudad para tu búsqueda gratis."
    ),

    # ── Rate limiting ────────────────────────────────────────────────────────
    "daily_limit_reached": (
        "⏳ Ya usaste tu búsqueda gratuita de hoy.\n\n"
        "Opciones para seguir:\n"
        "• *Básico S/59/mes* — 10 reportes/mes, 20 leads full\n"
        "• *Starter S/149/mes* — reportes ilimitados ⭐\n\n"
        "¿Quieres activar tu acceso?"
    ),
    "monthly_limit_reached": (
        "📊 Llegaste al límite de 10 búsquedas del plan Básico este mes.\n\n"
        "Con *Starter (S/149/mes)* tienes reportes ilimitados 🚀\n\n"
        "¿Quieres hacer el upgrade?"
    ),

    # ── Genérico ──────────────────────────────────────────────────────────────
    "not_understood": "No entendí eso 🤔 ¿En qué puedo ayudarte?",
    "already_running": "⏳ Tu reporte está en proceso, ya casi está listo...",

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
        "📸 Recibido ✅\n\n"
        "Estamos verificando tu pago. En minutos te confirmamos y activamos tu acceso.\n\n"
        "Si tienes dudas escríbenos a *contacto@pipelinex.app*"
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
}
