import json
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# --- CONFIGURAZIONE ---
TOKEN = os.environ.get("9269015022:AAE6SkbxlUbhPeQrpuZnFrJM42zrr6d6rs8")
DB_FILE = "dati_bot.json"
PUNTI_INIZIALI = 20  # Punti assegnati a ogni nuovo giocatore


# --- GESTIONE DATABASE JSON ---
def carica_dati():
    if not os.path.exists(DB_FILE):
        return {"utenti": {}, "sfida_attiva": None}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def salva_dati(dati):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(dati, f, indent=4, ensure_ascii=False)


def registra_utente_se_nuovo(dati, user):
    uid = str(user.id)
    nome = user.first_name or user.username or f"Utente_{uid[:4]}"
    if uid not in dati["utenti"]:
        dati["utenti"][uid] = {"nome": nome, "punti": PUNTI_INIZIALI}
    else:
        dati["utenti"][uid]["nome"] = nome
    return uid


# --- FUNZIONI DI SUPPORTO PER IL TEMPO ---
def tempo_in_secondi(testo_tempo: str):
    """Converte 'MM:SS' o 'HH:MM:SS' in secondi. Ritorna None se non valido."""
    parti = testo_tempo.strip().split(":")
    try:
        if len(parti) == 2:
            minuti, secondi = int(parti[0]), int(parti[1])
            return minuti * 60 + secondi
        elif len(parti) == 3:
            ore, minuti, secondi = int(parti[0]), int(parti[1]), int(parti[2])
            return ore * 3600 + minuti * 60 + secondi
    except ValueError:
        return None
    return None


def costruisci_tastiera():
    riga_si = [
        InlineKeyboardButton(f"Sì {i}pt", callback_data=f"puntata:si:{i}")
        for i in range(1, 6)
    ]
    riga_no = [
        InlineKeyboardButton(f"No {i}pt", callback_data=f"puntata:no:{i}")
        for i in range(1, 6)
    ]
    return InlineKeyboardMarkup([riga_si, riga_no])


def formatta_testo_sfida(sfida, dati):
    testo = f"🏆 **NUOVA SFIDA** 🏆\n\n📌 **{sfida['titolo']}**\n"
    if sfida["tempo_limite_str"]:
        testo += f"⏱ Obiettivo tempo: **sotto {sfida['tempo_limite_str']}**\n"

    stato = "🟢 APERTA (clicca per puntare)" if sfida["aperta"] else "🔒 CHIUSA (in attesa di esito)"
    testo += f"Stato: {stato}\n\n"

    puntate = sfida["puntate"]
    if not puntate:
        testo += "_Nessuna puntata ancora registrata._"
    else:
        testo += "**Puntate attuali:**\n"
        for uid, info in puntate.items():
            nome = dati["utenti"].get(uid, {}).get("nome", "Giocatore")
            scelta = "SÌ" if info["scelta"] == "si" else "NO"
            testo += f"• {nome}: **{scelta}** ({info['punti']} pt)\n"

    return testo


# --- COMANDI TELEGRAM ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dati = carica_dati()
    uid = registra_utente_se_nuovo(dati, update.effective_user)
    salva_dati(dati)

    msg = (
        f"Ciao {dati['utenti'][uid]['nome']}! Hai **{dati['utenti'][uid]['punti']} punti**.\n\n"
        "**Comandi disponibili:**\n"
        "• `/sfida 30:00 Bigba fa 10 giri del parco?` → Sfida con tempo limite\n"
        "• `/sfida Bigba arriva primo?` → Sfida senza tempo\n"
        "• `/chiudi` → Blocca le puntate prima dell'inizio\n"
        "• `/esito 28:40` → Inserisce il tempo (calcola Sì/No in automatico)\n"
        "• `/esito si` (oppure `no`) → Chiude manualmente e assegna i punti\n"
        "• `/classifica` → Mostra i punti di tutti\n"
        "• `/punti` → Controlla il tuo saldo\n"
        "• `/ricarica 10` → Aggiunge 10 punti a chi è rimasto a zero\n"
        "• `/backup` → Scarica il file dei salvataggi\n"
        "• `/ripristina` → Rispondi a un file backup per ricaricare i punti"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def punti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dati = carica_dati()
    uid = registra_utente_se_nuovo(dati, update.effective_user)
    salva_dati(dati)
    saldo = dati["utenti"][uid]["punti"]
    await update.message.reply_text(
        f"💰 {dati['utenti'][uid]['nome']}, hai **{saldo} punti**.",
        parse_mode="Markdown",
    )


async def classifica(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dati = carica_dati()
    if not dati["utenti"]:
        await update.message.reply_text("Nessun giocatore registrato! Scrivete /punti per entrare.")
        return

    ordinati = sorted(
        dati["utenti"].values(), key=lambda x: x["punti"], reverse=True
    )
    testo = "📊 **CLASSIFICA PUNTI** 📊\n\n"
    for pos, u in enumerate(ordinati, start=1):
        medaglia = "🥇" if pos == 1 else "🥈" if pos == 2 else "🥉" if pos == 3 else f"{pos}."
        testo += f"{medaglia} **{u['nome']}**: {u['punti']} pt\n"

    await update.message.reply_text(testo, parse_mode="Markdown")


async def ricarica(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dati = carica_dati()
    importo = 10
    if context.args and context.args[0].isdigit():
        importo = int(context.args[0])

    ricaricati = []
    for uid, u in dati["utenti"].items():
        if u["punti"] == 0:
            u["punti"] = importo
            ricaricati.append(u["nome"])

    salva_dati(dati)
    if ricaricati:
        await update.message.reply_text(
            f"🔋 Ricaricati **{importo} punti** a: {', '.join(ricaricati)}.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("Nessun giocatore è a 0 punti al momento!")


async def backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dati = carica_dati()
    salva_dati(dati)
    with open(DB_FILE, "rb") as f:
        await update.message.reply_document(
            document=f,
            filename="dati_bot.json",
            caption="💾 Ecco il backup aggiornato. Per ripristinarlo in futuro, rispondi a questo file scrivendo `/ripristina`.",
            parse_mode="Markdown",
        )


async def ripristina(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text(
            "⚠️ Per ripristinare i punti, **rispondi (Reply)** al messaggio con il file `dati_bot.json` scrivendo `/ripristina`.",
            parse_mode="Markdown",
        )
        return

    doc = update.message.reply_to_message.document
    file = await doc.get_file()
    contenuto_bytes = await file.download_as_bytearray()

    try:
        nuovi_dati = json.loads(contenuto_bytes.decode("utf-8"))
        if "utenti" not in nuovi_dati:
            raise ValueError("Formato non valido")
        salva_dati(nuovi_dati)
        await update.message.reply_text("✅ Backup ripristinato con successo! Controlla con `/classifica`.")
    except Exception:
        await update.message.reply_text("❌ Il file allegato non è un backup valido del bot.")


async def nuova_sfida(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dati = carica_dati()
    if dati["sfida_attiva"] is not None:
        await update.message.reply_text(
            "⚠️ C'è già una sfida attiva! Chiudila prima con `/esito`.",
            parse_mode="Markdown",
        )
        return

    if not context.args:
        await update.message.reply_text(
            "Scrivi il testo della sfida! Esempio:\n"
            "`/sfida 30:00 Bigba fa 10 giri del parco?`",
            parse_mode="Markdown",
        )
        return

    primo_arg = context.args[0]
    secondi_limite = tempo_in_secondi(primo_arg)

    if secondi_limite is not None and len(context.args) > 1:
        tempo_str = primo_arg
        titolo = " ".join(context.args[1:])
    else:
        tempo_str = None
        secondi_limite = None
        titolo = " ".join(context.args)

    sfida = {
        "titolo": titolo,
        "tempo_limite_str": tempo_str,
        "tempo_limite_sec": secondi_limite,
        "aperta": True,
        "puntate": {},
    }
    dati["sfida_attiva"] = sfida
    salva_dati(dati)

    await update.message.reply_text(
        formatta_testo_sfida(sfida, dati),
        reply_markup=costruisci_tastiera(),
        parse_mode="Markdown",
    )


async def gestisci_puntata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    dati = carica_dati()
    sfida = dati["sfida_attiva"]

    if not sfida or not sfida["aperta"]:
        await query.answer("⛔ Le puntate per questa sfida sono chiuse!", show_alert=True)
        return

    uid = registra_utente_se_nuovo(dati, query.from_user)
    _, scelta, importo_str = query.data.split(":")
    importo = int(importo_str)

    vecchia_puntata = sfida["puntate"].get(uid)
    saldo_disponibile = dati["utenti"][uid]["punti"] + (
        vecchia_puntata["punti"] if vecchia_puntata else 0
    )

    if saldo_disponibile < importo:
        await query.answer(
            f"❌ Non hai abbastanza punti! Saldo disponibile: {saldo_disponibile} pt.",
            show_alert=True,
        )
        return

    dati["utenti"][uid]["punti"] = saldo_disponibile - importo
    sfida["puntate"][uid] = {"scelta": scelta, "punti": importo}
    salva_dati(dati)

    etichetta = "SÌ" if scelta == "si" else "NO"
    await query.answer(
        f"✅ Puntati {importo} pt su {etichetta}! (Saldo rimasto: {dati['utenti'][uid]['punti']} pt)"
    )

    await query.edit_message_text(
        text=formatta_testo_sfida(sfida, dati),
        reply_markup=costruisci_tastiera(),
        parse_mode="Markdown",
    )


async def chiudi_puntate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dati = carica_dati()
    sfida = dati["sfida_attiva"]

    if not sfida:
        await update.message.reply_text("Non c'è nessuna sfida attiva.")
        return

    sfida["aperta"] = False
    salva_dati(dati)
    await update.message.reply_text(
        "🔒 **Puntate chiuse!** Nessuno può più modificare la propria scelta. Aspettiamo l'esito!",
        parse_mode="Markdown",
    )


async def esito(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dati = carica_dati()
    sfida = dati["sfida_attiva"]

    if not sfida:
        await update.message.reply_text("Non c'è nessuna sfida attiva da chiudere.")
        return

    if not context.args:
        await update.message.reply_text(
            "Specifica l'esito! Es: `/esito 28:40` oppure `/esito si` o `/esito no`.",
            parse_mode="Markdown",
        )
        return

    valore = context.args[0].lower().strip()
    risultato_finale = None
    dettaglio_tempo = ""

    sec_effettivi = tempo_in_secondi(valore)
    if sec_effettivi is not None:
        if sfida["tempo_limite_sec"] is None:
            await update.message.reply_text(
                "⚠️ Questa sfida non aveva un tempo limite impostato. Usa `/esito si` o `/esito no`.",
                parse_mode="Markdown",
            )
            return
        if sec_effettivi < sfida["tempo_limite_sec"]:
            risultato_finale = "si"
            dettaglio_tempo = f"⏱ Tempo registrato: **{valore}** (obiettivo {sfida['tempo_limite_str']} → **RIUSCITO!**)\n"
        else:
            risultato_finale = "no"
            dettaglio_tempo = f"⏱ Tempo registrato: **{valore}** (obiettivo {sfida['tempo_limite_str']} → **NON RIUSCITO!**)\n"

    elif valore in ["si", "sì", "yes"]:
        risultato_finale = "si"
    elif valore in ["no"]:
        risultato_finale = "no"
    else:
        await update.message.reply_text(
            "❌ Formato non valido. Scrivi un tempo (es. `28:40`) oppure `si` / `no`.",
            parse_mode="Markdown",
        )
        return

    vincitori = []
    perdenti = []

    for uid, info in sfida["puntate"].items():
        nome = dati["utenti"][uid]["nome"]
        puntati = info["punti"]
        if info["scelta"] == risultato_finale:
            vincita = puntati * 2
            dati["utenti"][uid]["punti"] += vincita
            vincitori.append(f"• **{nome}**: +{vincita} pt (puntati {puntati})")
        else:
            perdenti.append(f"• {nome}: -{puntati} pt")

    esito_testo = "SÌ ✅" if risultato_finale == "si" else "NO ❌"
    riepilogo = (
        f"🏁 **ESITO SFIDA: {sfida['titolo']}**\n"
        f"{dettaglio_tempo}"
        f"Risultato ufficiale: **{esito_testo}**\n\n"
    )

    if vincitori:
        riepilogo += "🎉 **Hanno indovinato (punti raddoppiati):**\n" + "\n".join(vincitori) + "\n\n"
    else:
        riepilogo += "😅 Nessuno ha indovinato stavolta!\n\n"

    if perdenti:
        riepilogo += "💸 **Hanno sbagliato:**\n" + "\n".join(perdenti)

    dati["sfida_attiva"] = None
    salva_dati(dati)

    await update.message.reply_text(riepilogo, parse_mode="Markdown")


# --- AVVIO DEL BOT ---
def main():
    if not TOKEN:
        raise ValueError("Errore: variabile d'ambiente BOT_TOKEN non impostata!")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("punti", punti))
    app.add_handler(CommandHandler("classifica", classifica))
    app.add_handler(CommandHandler("ricarica", ricarica))
    app.add_handler(CommandHandler("backup", backup))
    app.add_handler(CommandHandler("ripristina", ripristina))
    app.add_handler(CommandHandler("sfida", nuova_sfida))
    app.add_handler(CommandHandler("chiudi", chiudi_puntate))
    app.add_handler(CommandHandler("esito", esito))
    app.add_handler(CallbackQueryHandler(gestisci_puntata, pattern="^puntata:"))

    print("🤖 Bot avviato e in ascolto...")
    app.run_polling()


if __name__ == "__main__":
    main()
