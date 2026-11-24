import asyncio
import json
import os
import threading
import streamlit as st
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# --- CONFIGURAZIONE ---
TOKEN = st.secrets.get("9269015022:AAE6SkbxlUbhPeQrpuZnFrJM42zrr6d6rs8") or os.environ.get("9269015022:AAE6SkbxlUbhPeQrpuZnFrJM42zrr6d6rs8")
DB_FILE = "dati_bot.json"
PUNTI_INIZIALI = 20
file_lock = threading.Lock()


# --- GESTIONE DATABASE JSON (THREAD-SAFE) ---
def carica_dati():
    with file_lock:
        if not os.path.exists(DB_FILE):
            return {"utenti": {}, "sfida_attiva": None}
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)


def salva_dati(dati):
    with file_lock:
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
    parti = testo_tempo.strip().split(":")
    try:
        if len(parti) == 2:
            return int(parti[0]) * 60 + int(parti[1])
        elif len(parti) == 3:
            return int(parti[0]) * 3600 + int(parti[1]) * 60 + int(parti[2])
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
        "**Comandi disponibili nel gruppo:**\n"
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

    ordinati = sorted(dati["utenti"].values(), key=lambda x: x["punti"], reverse=True)
    testo = "📊 **CLASSIFICA PUNTI** 📊\n\n"
    for pos, u in enumerate(ordinati, start=1):
        medaglia = "🥇" if pos == 1 else "🥈" if pos == 2 else "🥉" if pos == 3 else f"{pos}."
        testo += f"{medaglia} **{u['nome']}**: {u['punti']} pt\n"

    await update.message.reply_text(testo, parse_mode="Markdown")


async def ricarica(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dati = carica_dati()
    importo = int(context.args[0]) if (context.args and context.args[0].isdigit()) else 10

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
    with file_lock:
        with open(DB_FILE, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename="dati_bot.json",
                caption="💾 Ecco il backup. Rispondi a questo file scrivendo `/ripristina` per ricaricarlo.",
                parse_mode="Markdown",
            )


async def ripristina(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text(
            "⚠️ Rispondi al file `dati_bot.json` scrivendo `/ripristina`.",
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
        await update.message.reply_text("✅ Backup ripristinato! Controlla con `/classifica`.")
    except Exception:
        await update.message.reply_text("❌ File non valido.")


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
            "Esempio: `/sfida 30:00 Bigba fa 10 giri del parco?`",
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
        await query.answer("⛔ Le puntate sono chiuse!", show_alert=True)
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
            f"❌ Punti insufficienti! Saldo disponibile: {saldo_disponibile} pt.",
            show_alert=True,
        )
        return

    dati["utenti"][uid]["punti"] = saldo_disponibile - importo
    sfida["puntate"][uid] = {"scelta": scelta, "punti": importo}
    salva_dati(dati)

    etichetta = "SÌ" if scelta == "si" else "NO"
    await query.answer(
        f"✅ Puntati {importo} pt su {etichetta}! (Rimasti: {dati['utenti'][uid]['punti']} pt)"
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
    await update.message.reply_text("🔒 **Puntate chiuse!**", parse_mode="Markdown")


async def esito(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dati = carica_dati()
    sfida = dati["sfida_attiva"]

    if not sfida:
        await update.message.reply_text("Non c'è nessuna sfida attiva.")
        return

    if not context.args:
        await update.message.reply_text(
            "Es: `/esito 28:40` oppure `/esito si` o `/esito no`.",
            parse_mode="Markdown",
        )
        return

    valore = context.args[0].lower().strip()
    risultato_finale = None
    dettaglio_tempo = ""

    sec_effettivi = tempo_in_secondi(valore)
    if sec_effettivi is not None:
        if sfida["tempo_limite_sec"] is None:
            await update.message.reply_text("⚠️ Sfida senza tempo limite. Usa `/esito si` o `/esito no`.")
            return
        if sec_effettivi < sfida["tempo_limite_sec"]:
            risultato_finale = "si"
            dettaglio_tempo = f"⏱ Tempo: **{valore}** (limite {sfida['tempo_limite_str']} → **RIUSCITO!**)\n"
        else:
            risultato_finale = "no"
            dettaglio_tempo = f"⏱ Tempo: **{valore}** (limite {sfida['tempo_limite_str']} → **NON RIUSCITO!**)\n"
    elif valore in ["si", "sì", "yes"]:
        risultato_finale = "si"
    elif valore in ["no"]:
        risultato_finale = "no"
    else:
        await update.message.reply_text("❌ Scrivi un tempo (`28:40`) oppure `si` / `no`.")
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
        f"Risultato: **{esito_testo}**\n\n"
    )

    if vincitori:
        riepilogo += "🎉 **Hanno indovinato:**\n" + "\n".join(vincitori) + "\n\n"
    else:
        riepilogo += "😅 Nessuno ha indovinato!\n\n"

    if perdenti:
        riepilogo += "💸 **Hanno sbagliato:**\n" + "\n".join(perdenti)

    dati["sfida_attiva"] = None
    salva_dati(dati)
    await update.message.reply_text(riepilogo, parse_mode="Markdown")


# --- AVVIO BOT IN BACKGROUND PER STREAMLIT ---
def avvia_bot_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

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

    app.run_polling(stop_signals=None)


@st.cache_resource
def inizializza_bot():
    if TOKEN:
        t = threading.Thread(target=avvia_bot_thread, daemon=True)
        t.start()
        return True
    return False


# --- INTERFACCIA WEB STREAMLIT ---
st.set_page_config(page_title="Bot Sfide Telegram", page_icon="🏆")
st.title("🏆 Bot Sfide — Stato & Classifica")

attivo = inizializza_bot()
if attivo:
    st.success("🟢 Bot Telegram attivo e in ascolto nel gruppo!")
else:
    st.error("⚠️ BOT_TOKEN non trovato! Inseriscilo nei Secrets di Streamlit.")

dati = carica_dati()
if dati["sfida_attiva"]:
    st.info(f"📌 **Sfida in corso:** {dati['sfida_attiva']['titolo']}")

st.subheader("📊 Classifica Live")
if dati["utenti"]:
    ordinati = sorted(dati["utenti"].values(), key=lambda x: x["punti"], reverse=True)
    for pos, u in enumerate(ordinati, start=1):
        st.write(f"**{pos}. {u['nome']}** — {u['punti']} pt")
else:
    st.write("Nessun giocatore ancora registrato.")

if st.button("🔄 Aggiorna classifica"):
    st.rerun()
