
import asyncio
import logging
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
    ChatMemberHandler,
    CallbackQueryHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import nest_asyncio
import os
import pytz
from dotenv import load_dotenv
import random

# Configuração do logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Aplicar patch para suportar loop reentrante
nest_asyncio.apply()

# === CONFIG ===
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

if not BOT_TOKEN or not ADMIN_ID:
    logger.error("BOT_TOKEN e/ou ADMIN_ID não definidos nas variáveis de ambiente!")
    exit(1)

# Definir o fuso horário de Brasília (GMT-3)
brasilia_tz = pytz.timezone('America/Sao_Paulo')

# Banco de dados SQLite para persistência
def get_db_connection():
    conn = sqlite3.connect('bot_data.db')
    conn.row_factory = sqlite3.Row  # Facilita o acesso aos dados como dicionários
    return conn

def close_db_connection(conn):
    conn.close()

# Função para criar a tabela canais caso não exista
def create_tables():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS canais (
            chat_id INTEGER PRIMARY KEY,
            last_interaction_date TEXT
        )
    """)
    conn.commit()
    close_db_connection(conn)

# Funções de persistência
def get_last_interaction_date(canal_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT last_interaction_date FROM canais WHERE chat_id = ?", (canal_id,))
    result = cursor.fetchone()
    close_db_connection(conn)
    return result[0] if result else None

def update_last_interaction_date(canal_id, date):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE canais SET last_interaction_date = ? WHERE chat_id = ?", (date, canal_id))
    conn.commit()
    close_db_connection(conn)

def add_canal(chat_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO canais (chat_id) VALUES (?)", (chat_id,))
    conn.commit()
    close_db_connection(conn)

def get_canais():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM canais")
    canais = cursor.fetchall()
    close_db_connection(conn)
    return canais

# Função que será chamada sempre que o bot for adicionado a um novo canal
async def on_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_member = update.chat_member

    # Verificar se o bot foi adicionado como administrador
    if new_member.new_chat_member.user.id == context.bot.id:
        if new_member.new_chat_member.status in ["administrator", "creator"]:
            # O bot foi adicionado como administrador
            chat_id = update.chat.id
            await send_welcome_message(update, context, chat_id)

# Função que envia a mensagem de boas-vindas para o novo canal
async def send_welcome_message(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    # Mensagem de boas-vindas
    welcome_text = (
        "🎉 Olá! Eu sou o bot responsável por ajudar a gerenciar e promover seu canal!

"
        "Agora que você me adicionou como administrador, eu posso enviar mensagens programadas para o seu canal.
"
        "Fique atento às instruções e aproveite todos os benefícios!"
    )
    try:
        # Enviar a mensagem de boas-vindas para o canal
        await context.bot.send_message(chat_id, welcome_text)
        # Registrar o canal no banco de dados
        add_canal(chat_id)
        logger.info(f"Canal {chat_id} registrado com sucesso!")
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem de boas-vindas para o canal {chat_id}: {e}")

# Função para enviar a mensagem programada com limitação de requisições
async def enviar_mensagem_programada(bot):
    canais = get_canais()
    for canal in canais:
        canal_id = canal[0]

        # Verificar a última interação e garantir que não houve envio no mesmo dia
        last_interaction = get_last_interaction_date(canal_id)
        today = datetime.now().strftime("%Y-%m-%d")
        if last_interaction == today:
            logger.info(f"Canal {canal_id} já foi atualizado hoje.")
            continue  # Se já foi interagido hoje, pula para o próximo canal

        # Pausar entre os envios para evitar múltiplos pedidos em sequência
        await asyncio.sleep(5)  # Adiciona uma pausa de 5 segundos entre os envios

        # Enviar a mensagem com a lista de canais
        try:
            await bot.send_message(
                chat_id=canal_id,
                text="Aqui estão os canais disponíveis...",
            )
            update_last_interaction_date(canal_id, today)
        except Exception as e:
            logger.error(f"Erro ao enviar para {canal_id}: {e}")
            # Espera antes de tentar novamente
            await asyncio.sleep(10)

# Função para iniciar o bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("Cadastrar meu canal", callback_data='cadastrar_canal'),
            InlineKeyboardButton("Como funciona o bot?", callback_data='como_funciona'),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Bem-vindo! Como posso te ajudar hoje?", reply_markup=reply_markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'cadastrar_canal':
        await query.edit_message_text("Vamos começar o cadastro do seu canal! Adicione o bot como administrador e aguarde a mensagem de boas-vindas.")
    elif query.data == 'como_funciona':
        await query.edit_message_text("Eu ajudo a gerenciar canais, enviar mensagens programadas, e muito mais!")

# Inicializando o agendador corretamente
scheduler = AsyncIOScheduler()  # Agora o scheduler é inicializado corretamente

# Main
async def main():
    logger.info("Iniciando o bot...")  # Log para verificar o início da execução

    # Configuração do bot com pool e timeout ajustados
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Chama a função para criar a tabela 'canais' se não existir
    create_tables()

    # Ajustando o pool de conexões e o timeout com a API pública
    app.bot._request_kwargs = {
        'timeout': 30,  # Timeout de 30 segundos
        'pool_size': 20  # Pool de conexões de 20
    }

    # Adicionando os handlers
    app.add_handler(ChatMemberHandler(on_chat_member_update))  # Verificar quando o bot é adicionado como administrador
    app.add_handler(CommandHandler("start", start))  # Comando start agora registrado
    app.add_handler(CallbackQueryHandler(button))  # Handler de botões

    # Agendando as mensagens para horários específicos em horário de Brasília
    try:
        scheduler.add_job(enviar_mensagem_programada, "cron", hour=21, minute=30, args=[app.bot], timezone=brasilia_tz)  # 21:10
        scheduler.add_job(enviar_mensagem_programada, "cron", hour=4, minute=0, args=[app.bot], timezone=brasilia_tz)   # 4h
        scheduler.add_job(enviar_mensagem_programada, "cron", hour=11, minute=0, args=[app.bot], timezone=brasilia_tz)  # 11h
        scheduler.add_job(enviar_mensagem_programada, "cron", hour=18, minute=20, args=[app.bot], timezone=brasilia_tz)  # 17h
        scheduler.start()  # Iniciando o scheduler
    except Exception as e:
        logger.error(f"Erro ao agendar tarefa: {e}")

    logger.info("✅ Bot rodando com polling e agendamento diário!")
    await app.run_polling(drop_pending_updates=True, timeout=30)  # Polling com timeout configurado

if __name__ == "__main__":
    try:
        asyncio.run(main())  # Usando asyncio.run diretamente
    except Exception as e:
        logger.error(f"Erro ao iniciar o bot: {e}")
