import asyncio
from datetime import datetime
import json
import os
import threading
from zoneinfo import ZoneInfo
import streamlit as st
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# --- CONFIGURAZIONE ---
TOKEN = "9269015022:AAE6SkbxlUbhPeQrpuZnFrJM42zrr6d6rs8"
DB_FILE = "dati_bot.json"
PUNTI_INIZIALI = 20
FUSO_ORARIO = ZoneInfo("Europe/Rome")
file_lock = threading.Lock()

# Stati della conversazione per /sfida (in chat privata)
CHIEDI_TITOLO, CHIEDI_DATA_ORA = range(2)


# --- GESTIONE DATABASE JSON (THREAD-SAFE) ---
def carica_dati():
    with file_lock:
        if not os.path.exists(DB_FILE):
            return {
                "admin_id": None,
                "gruppo_id": None,
                "utenti": {},
                "sfida_attiva": None,
            }
        with open(DB_FILE, "r", encoding="utf-8") as f:
            dati = json.load(f)
            dati.setdefault("admin_id", None)
            dati.setdefault("gruppo_id", None)
            dati.setdefault("utenti", {})
            dati.setdefault("sfida_attiva", None)
            return dati


def salva_dati(dati):
    with file_lock:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(dati, f, indent=4, ensure_ascii=False)


def registra_utente_se_nuovo(dati, user):
    uid = str(user.id)
    nome = user.first_name or user.username or f"Utente_{uid[:4]}"
    username = (user.username or "").lower()
    if uid not in dati["utenti"]:
        dati["utenti"][uid] = {
            "nome": nome,
            "username": username,
            "punti": PUNTI_INIZIALI,
        }
    else:
        dati["utenti"][uid]["nome"] = nome
        dati["utenti"][uid]["username"] = username
    return uid


def is_admin(dati, user_id: int) -> bool:
    if dati["admin_id"] is None:
        return True
    return str(user_id) == str(dati["admin_id"])


def parse_data_ora(testo: str):
    pulito = testo.strip().lower().replace("alle ", "").replace("ore ", "").replace("-", " ")
    pulito = " ".join(pulito.split())
    ora_italiana = datetime.now(FUSO_ORARIO)

    for fmt in ("%d/%m/%Y %H:%M", "%d/%m %H:%M", "%d/%m/%y %H:%M"):
        try:
            dt = datetime.strptime(pulito, fmt)
            if fmt == "%d/%m %H:%M":
                dt = dt.replace(year=ora_italiana.year)
            return dt.replace(tzinfo=FUSO_ORARIO)
        except ValueError:
            continue
    return None


def sfida_ancora_aperta(sfida: dict) -> bool:
    if not sfida or not sfida.get("aperta", False):
        return False
    scadenza_iso = sfida.get("scadenza_iso")
    if scadenza_iso:
        scadenza_dt = datetime.fromisoformat(scadenza_iso)
        if datetime.now(FUSO_ORARIO) >= scadenza_dt:
            sfida["aperta"] = False
            return False
    return True


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
    aperta = sfida_ancora_aperta(sfida)
    stato = "🟢 APERTA (clicca per puntare)" if aperta else "🔒 CHIUSA (tempo scaduto per puntare)"

    testo = (
        f"🏆 NUOVA SFIDA 🏆\n\n"
        f"📌 {sfida['titolo']}\n"
        f"⏳ Termine puntate: {sfida['scadenza_str']}\n"
        f"Stato: {stato}\n\n"
    )

    puntate = sfida["puntate"]
    if not puntate:
        testo += "Nessuna puntata ancora registrata."
    else:
        for uid in puntate.keys():
            nome = dati["utenti"].get(uid, {}).get("nome", "Giocatore")
            testo += f"• {nome} ha scommesso\n"

    return testo


def testo_classifica(dati):
    ordinati = sorted(dati["utenti"].values(), key=lambda x: x["punti"], reverse=True)
    if not ordinati:
        return "📊 CLASSIFICA PUNTI 📊\n\nNessun giocatore ancora registrato."
    testo = "📊 CLASSIFICA AGGIORNATA 📊\n\n"
    for pos, u in enumerate(ordinati, start=1):
        medaglia = "🥇" if pos == 1 else "🥈" if pos == 2 else "🥉" if pos == 3 else f"{pos}."
        testo += f"{medaglia} {u['nome']}: {u['punti']} pt\n"
    return testo


# --- COMANDO /start (SOLO IN PRIVATO) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    dati = carica_dati()
    uid = registra_utente_se_nuovo(dati, update.effective_user)

    if dati["admin_id"] is None:
        dati["admin_id"] = uid
    salva_dati(dati)

    if not is_admin(dati, update.effective_user.id):
        await update.message.reply_text(
            f"Ciao {dati['utenti'][uid]['nome']}! Hai {dati['utenti'][uid]['punti']} punti.\n"
            "Le sfide vengono pubblicate nel gruppo: clicca sui pulsanti sotto la sfida per puntare!"
        )
        return

    stato_gruppo = "✅ Collegato" if dati["gruppo_id"] else "⚠️ Non ancora collegato (scrivi /collega nel gruppo)"
    msg = (
        f"Ciao {dati['utenti'][uid]['nome']} (Admin)! Hai {dati['utenti'][uid]['punti']} punti.\n"
        f"Gruppo: {stato_gruppo}\n\n"
        "Comandi Admin (funzionano solo qui in privato):\n"
        "• /sfida → Crea una nuova sfida e la pubblica nel gruppo\n"
        "• /esito si (oppure no) → Chiude la sfida, pubblica l'esito e aggiorna la classifica nel gruppo\n"
        "• /cancella → Annulla la sfida attiva, rimborsa i punti e avvisa il gruppo\n"
        "• /ricarica Nome 10 → Aggiunge punti a un membro (es. /ricarica Mirko 10)\n"
        "• /classifica → Controlla la classifica qui in privato\n"
        "• /backup → Scarica il file dei salvataggi\n"
        "• /ripristina → Rispondi a un file backup per ricaricarlo"
    )
    await update.message.reply_text(msg)


# --- COMANDO /collega (DA USARE UNA VOLTA NEL GRUPPO SOLO DALL'ADMIN) ---
async def collega_gruppo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("Scrivi /collega direttamente dentro il gruppo da collegare!")
        return

    dati = carica_dati()
    if not is_admin(dati, update.effective_user.id):
        return

    dati["gruppo_id"] = update.effective_chat.id
    salva_dati(dati)
    await update.message.reply_text("✅ Gruppo collegato! Da ora in poi tutto si gestisce dalla chat privata.")


# --- CREAZIONE GUIDATA /sfida (SOLO ADMIN IN PRIVATO) ---
async def avvia_sfida(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return ConversationHandler.END

    dati = carica_dati()
    if not is_admin(dati, update.effective_user.id):
        return ConversationHandler.END

    if not dati["gruppo_id"]:
        await update.message.reply_text(
            "⚠️ Prima devi collegare il gruppo! Vai nel gruppo Telegram e scrivi /collega."
        )
        return ConversationHandler.END

    if dati["sfida_attiva"] is not None:
        await update.message.reply_text(
            "⚠️ C'è già una sfida attiva! Chiudila con /esito oppure annullala con /cancella."
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "1️⃣ Che sfida vuoi fare?\n"
        "(Es. Bigba fa 10 giri del parco sotto i 30 minuti)\n\n"
        "Scrivi /annulla per interrompere."
    )
    return CHIEDI_TITOLO


async def ricevi_titolo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["nuova_sfida_titolo"] = update.message.text.strip()
    await update.message.reply_text(
        "2️⃣ Entro che data e ora si può puntare?\n"
        "Scrivi nel formato GG/MM HH:MM (es. 29/11 15:30):"
    )
    return CHIEDI_DATA_ORA


async def ricevi_data_ora(update: Update, context: ContextTypes.DEFAULT_TYPE):
    testo_data = update.message.text.strip()
    dt_scadenza = parse_data_ora(testo_data)

    if dt_scadenza is None:
        await update.message.reply_text(
            "❌ Non ho capito data e ora. Scrivile così: GG/MM HH:MM (esempio: 29/11 15:30):"
        )
        return CHIEDI_DATA_ORA

    if dt_scadenza <= datetime.now(FUSO_ORARIO):
        await update.message.reply_text(
            "⚠️ Questa data/ora è già passata! Inserisci un orario futuro (es. 29/11 15:30):"
        )
        return CHIEDI_DATA_ORA

    dati = carica_dati()
    sfida = {
        "titolo": context.user_data["nuova_sfida_titolo"],
        "scadenza_str": dt_scadenza.strftime("%d/%m/%Y alle %H:%M"),
        "scadenza_iso": dt_scadenza.isoformat(),
        "aperta": True,
        "puntate": {},
    }
    dati["sfida_attiva"] = sfida
    salva_dati(dati)

    await context.bot.send_message(
        chat_id=dati["gruppo_id"],
        text=formatta_testo_sfida(sfida, dati),
        reply_markup=costruisci_tastiera(),
    )

    await update.message.reply_text("✅ Sfida pubblicata nel gruppo!")
    return ConversationHandler.END


async def annulla_creazione(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Creazione sfida annullata.")
    return ConversationHandler.END


# --- GESTIONE PUNTATE ANONIME (PULSANTI NEL GRUPPO) ---
async def gestisci_puntata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    dati = carica_dati()
    sfida = dati["sfida_attiva"]

    if not sfida or not sfida_ancora_aperta(sfida):
        salva_dati(dati)
        await query.answer("⛔ Tempo scaduto! Le puntate per questa sfida sono chiuse.", show_alert=True)
        try:
            await query.edit_message_text(text=formatta_testo_sfida(sfida, dati))
        except Exception:
            pass
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
        f"✅ Puntata segreta registrata: {importo} pt su {etichetta}! (Rimasti: {dati['utenti'][uid]['punti']} pt)",
        show_alert=True,
    )

    try:
        await query.edit_message_text(
            text=formatta_testo_sfida(sfida, dati),
            reply_markup=costruisci_tastiera(),
        )
    except Exception:
        pass


# --- ESITO E CANCELLA SFIDA (SOLO ADMIN IN PRIVATO -> PUBBLICA SUL GRUPPO) ---
async def esito(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    dati = carica_dati()
    if not is_admin(dati, update.effective_user.id):
        return

    sfida = dati["sfida_attiva"]
    if not sfida:
        await update.message.reply_text("Non c'è nessuna sfida attiva.")
        return

    if not context.args or context.args[0].lower() not in ["si", "sì", "no"]:
        await update.message.reply_text("Scrivi /esito si oppure /esito no.")
        return

    risultato_finale = "si" if context.args[0].lower() in ["si", "sì"] else "no"
    vincitori = []
    perdenti = []

    for uid, info in sfida["puntate"].items():
        nome = dati["utenti"][uid]["nome"]
        puntati = info["punti"]
        scelta_str = "SÌ" if info["scelta"] == "si" else "NO"
        if info["scelta"] == risultato_finale:
            vincita = puntati * 2
            dati["utenti"][uid]["punti"] += vincita
            vincitori.append(f"• {nome}: +{vincita} pt (puntati {puntati} pt su {scelta_str})")
        else:
            perdenti.append(f"• {nome}: -{puntati} pt (puntati {puntati} pt su {scelta_str})")

    esito_testo = "SÌ ✅" if risultato_finale == "si" else "NO ❌"
    riepilogo = f"🏁 ESITO SFIDA: {sfida['titolo']}\nRisultato: {esito_testo}\n\n"

    if vincitori:
        riepilogo += "🎉 Hanno indovinato (punti raddoppiati):\n" + "\n".join(vincitori) + "\n\n"
    else:
        riepilogo += "😅 Nessuno ha indovinato!\n\n"

    if perdenti:
        riepilogo += "💸 Hanno sbagliato:\n" + "\n".join(perdenti) + "\n\n"

    riepilogo += testo_classifica(dati)

    dati["sfida_attiva"] = None
    salva_dati(dati)

    if dati["gruppo_id"]:
        await context.bot.send_message(chat_id=dati["gruppo_id"], text=riepilogo)

    await update.message.reply_text("✅ Esito e classifica aggiornata pubblicati nel gruppo!")


async def cancella_sfida(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    dati = carica_dati()
    if not is_admin(dati, update.effective_user.id):
        return

    sfida = dati["sfida_attiva"]
    if not sfida:
        await update.message.reply_text("Non c'è nessuna sfida attiva da cancellare.")
        return

    for uid, info in sfida["puntate"].items():
        if uid in dati["utenti"]:
            dati["utenti"][uid]["punti"] += info["punti"]

    titolo_vecchio = sfida["titolo"]
    dati["sfida_attiva"] = None
    salva_dati(dati)

    if dati["gruppo_id"]:
        await context.bot.send_message(
            chat_id=dati["gruppo_id"],
            text=f"🗑️ La sfida '{titolo_vecchio}' è stata annullata! Tutte le puntate sono state rimborsate.",
        )

    await update.message.reply_text("✅ Sfida cancellata, punti rimborsati e gruppo avvisato.")


# --- CLASSIFICA, RICARICA E BACKUP (SOLO ADMIN IN PRIVATO) ---
async def classifica(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    dati = carica_dati()
    if not is_admin(dati, update.effective_user.id):
        return

    await update.message.reply_text(testo_classifica(dati))


async def ricarica(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    dati = carica_dati()
    if not is_admin(dati, update.effective_user.id):
        return

    if len(context.args) < 2 or not context.args[-1].lstrip("-").isdigit():
        await update.message.reply_text(
            "Uso: /ricarica Nome 10 (es. /ricarica Mirko 10)"
        )
        return

    importo = int(context.args[-1])
    cercato = " ".join(context.args[:-1]).lstrip("@").lower()

    trovato_uid = None
    for uid, u in dati["utenti"].items():
        if u["nome"].lower() == cercato or u.get("username", "").lower() == cercato:
            trovato_uid = uid
            break

    if not trovato_uid:
        await update.message.reply_text(
            f"❌ Utente '{cercato}' non trovato. Deve aver fatto almeno una puntata nel gruppo."
        )
        return

    dati["utenti"][trovato_uid]["punti"] += importo
    salva_dati(dati)
    await update.message.reply_text(
        f"🔋 Aggiunti {importo} pt a {dati['utenti'][trovato_uid]['nome']} (nuovo saldo: {dati['utenti'][trovato_uid]['punti']} pt)."
    )


async def backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    dati = carica_dati()
    if not is_admin(dati, update.effective_user.id):
        return

    salva_dati(dati)
    with file_lock:
        with open(DB_FILE, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename="dati_bot.json",
                caption="💾 Backup salvato. Rispondi a questo file scrivendo /ripristina per ricaricarlo.",
            )


async def ripristina(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    dati = carica_dati()
    if not is_admin(dati, update.effective_user.id):
        return

    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text("⚠️ Rispondi al file dati_bot.json scrivendo /ripristina.")
        return

    doc = update.message.reply_to_message.document
    file = await doc.get_file()
    contenuto_bytes = await file.download_as_bytearray()

    try:
        nuovi_dati = json.loads(contenuto_bytes.decode("utf-8"))
        if "utenti" not in nuovi_dati:
            raise ValueError("Formato non valido")
        nuovi_dati.setdefault("admin_id", dati["admin_id"])
        nuovi_dati.setdefault("gruppo_id", dati["gruppo_id"])
        salva_dati(nuovi_dati)
        await update.message.reply_text("✅ Backup ripristinato! Controlla con /classifica.")
    except Exception:
        await update.message.reply_text("❌ File non valido.")


# --- AVVIO BOT IN BACKGROUND PER STREAMLIT ---
def avvia_bot_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = Application.builder().token(TOKEN).build()

    conv_sfida = ConversationHandler(
        entry_points=[CommandHandler("sfida", avvia_sfida)],
        states={
            CHIEDI_TITOLO: [MessageHandler(filters.TEXT & ~filters.COMMAND, ricevi_titolo)],
            CHIEDI_DATA_ORA: [MessageHandler(filters.TEXT & ~filters.COMMAND, ricevi_data_ora)],
        },
        fallbacks=[CommandHandler("annulla", annulla_creazione)],
        per_user=True,
        per_chat=True,
    )

    app.add_handler(conv_sfida)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("collega", collega_gruppo))
    app.add_handler(CommandHandler("esito", esito))
    app.add_handler(CommandHandler("cancella", cancella_sfida))
    app.add_handler(CommandHandler("classifica", classifica))
    app.add_handler(CommandHandler("ricarica", ricarica))
    app.add_handler(CommandHandler("backup", backup))
    app.add_handler(CommandHandler("ripristina", ripristina))
    app.add_handler(CallbackQueryHandler(gestisci_puntata, pattern="^puntata:"))

    app.run_polling(stop_signals=None, allowed_updates=Update.ALL_TYPES)


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
    st.success("🟢 Bot Telegram attivo!")
else:
    st.error("⚠️ BOT_TOKEN non trovato! Inseriscilo nel codice o nei Secrets di Streamlit.")

dati = carica_dati()
if dati["sfida_attiva"]:
    st.info(f"📌 Sfida in corso: {dati['sfida_attiva']['titolo']}")

st.subheader("📊 Classifica Live")
if dati["utenti"]:
    ordinati = sorted(dati["utenti"].values(), key=lambda x: x["punti"], reverse=True)
    for pos, u in enumerate(ordinati, start=1):
        st.write(f"**{pos}. {u['nome']}** — {u['punti']} pt")
else:
    st.write("Nessun giocatore ancora registrato.")

if st.button("🔄 Aggiorna classifica"):
    st.rerun()
