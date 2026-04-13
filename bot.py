import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from telegram.constants import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import pytz

from database import Database

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
TOKEN = "8733641525:AAF8r3kTy3HM2UoR0bietO0wJb81345dJdY"
ADMIN_ID = 2111583140  # Ваш ID
TIMEZONE = pytz.timezone('Europe/Moscow')  # Измените на свой часовой пояс

# Состояния для ConversationHandler
TITLE, DESCRIPTION, DATE, TIME = range(4)

# Инициализация базы данных
db = Database()

class ConcertBot:
    def __init__(self):
        self.application = Application.builder().token(TOKEN).build()
        self.scheduler = AsyncIOScheduler(timezone=TIMEZONE)
        self.setup_handlers()
        self.setup_scheduler()
    
    def setup_handlers(self):
        # Команды
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("events", self.events_command))
        self.application.add_handler(CommandHandler("myevents", self.my_events_command))
        
        # Админские команды
        self.application.add_handler(CommandHandler("new_event", self.new_event_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CommandHandler("cancel", self.cancel_command))
        
        # ConversationHandler для создания мероприятия
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("new_event", self.new_event_command)],
            states={
                TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_title)],
                DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_description)],
                DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_date)],
                TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_time)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_command)],
        )
        self.application.add_handler(conv_handler)
        
        # Обработчик callback-запросов
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
    
    def setup_scheduler(self):
        """Настройка планировщика для отправки напоминаний"""
        self.scheduler.add_job(
            self.send_reminders_3days,
            IntervalTrigger(minutes=30),
            args=[],
            name='reminders_3days'
        )
        
        self.scheduler.add_job(
            self.send_reminders_12hours,
            IntervalTrigger(minutes=15),
            args=[],
            name='reminders_12hours'
        )
        
        self.scheduler.start()
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user = update.effective_user
        welcome_text = (
            f"🎸 Привет, {user.first_name}!\n\n"
            f"Я бот концертного клуба. Здесь ты можешь:\n"
            f"• Посмотреть афишу мероприятий - /events\n"
            f"• Отметить, что придёшь на концерт\n"
            f"• Получить напоминание за 3 дня и за 12 часов до начала\n\n"
            f"Если хочешь создать мероприятие, используй /new_event (только для админов)"
        )
        await update.message.reply_text(welcome_text)
    
    async def events_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать все активные мероприятия"""
        events = db.get_active_events()
        
        if not events:
            await update.message.reply_text("😔 Пока нет запланированных мероприятий. Загляни позже!")
            return
        
        for event in events:
            await self.send_event_message(update.effective_chat.id, event)
    
    async def send_event_message(self, chat_id: int, event: Dict[str, Any]):
        """Отправить сообщение с информацией о мероприятии"""
        event_date = datetime.strptime(event['event_date'], '%Y-%m-%d %H:%M:%S')
        formatted_date = event_date.strftime('%d.%m.%Y в %H:%M')
        
        attendees = db.get_event_attendees(event['id'])
        attendees_count = len(attendees)
        
        message = (
            f"🎵 *{event['title']}*\n\n"
            f"{event['description']}\n\n"
            f"📅 *Когда:* {formatted_date}\n"
            f"👥 *Идут:* {attendees_count} чел.\n\n"
            f"Нажми кнопку ниже, если планируешь прийти!"
        )
        
        keyboard = [[InlineKeyboardButton("✅ Я пойду!", callback_data=f"attend_{event['id']}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await self.application.bot.send_message(
            chat_id=chat_id,
            text=message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def my_events_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать мероприятия, на которые пользователь записался"""
        user_id = update.effective_user.id
        
        # Получаем все активные мероприятия и проверяем, записан ли пользователь
        events = db.get_active_events()
        my_events = []
        
        for event in events:
            attendees = db.get_event_attendees(event['id'])
            if any(a['user_id'] == user_id for a in attendees):
                my_events.append(event)
        
        if not my_events:
            await update.message.reply_text(
                "📋 Вы пока не записаны ни на одно мероприятие.\n"
                "Используйте /events чтобы посмотреть афишу!"
            )
            return
        
        await update.message.reply_text("🎯 *Мероприятия, на которые вы идёте:*", parse_mode=ParseMode.MARKDOWN)
        
        for event in my_events:
            event_date = datetime.strptime(event['event_date'], '%Y-%m-%d %H:%M:%S')
            formatted_date = event_date.strftime('%d.%m.%Y в %H:%M')
            
            message = f"🎵 *{event['title']}*\n📅 {formatted_date}"
            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик inline-кнопок"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user = query.from_user
        
        if data.startswith('attend_'):
            event_id = int(data.split('_')[1])
            await self.handle_attend(query, event_id, user)
        
        elif data.startswith('reminder_'):
            parts = data.split('_')
            event_id = int(parts[1])
            need_reminder = parts[2] == 'yes'
            await self.handle_reminder_choice(query, event_id, user, need_reminder)
    
    async def handle_attend(self, query, event_id: int, user):
        """Обработка нажатия кнопки "Я пойду!" """
        event = db.get_event(event_id)
        if not event:
            await query.edit_message_text("😕 Это мероприятие уже недоступно.")
            return
        
        # Добавляем пользователя в список участников
        db.add_attendee(
            event_id=event_id,
            user_id=user.id,
            username=user.username or "",
            first_name=user.first_name or "",
            last_name=user.last_name or "",
            need_reminder=False
        )
        
        # Спрашиваем о напоминании
        keyboard = [
            [
                InlineKeyboardButton("✅ Да", callback_data=f"reminder_{event_id}_yes"),
                InlineKeyboardButton("❌ Нет", callback_data=f"reminder_{event_id}_no")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🎉 Отлично! Ждём вас на концерте!\n\n"
            "🔔 *Напомнить о мероприятии за 3 дня и за 12 часов?*",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def handle_reminder_choice(self, query, event_id: int, user, need_reminder: bool):
        """Обработка выбора о напоминании"""
        db.update_reminder_status(event_id, user.id, need_reminder)
        
        if need_reminder:
            await query.edit_message_text(
                "✅ Отлично! Я напомню вам о мероприятии:\n"
                "• За 3 дня\n"
                "• За 12 часов\n\n"
                "До встречи на концерте! 🎸"
            )
        else:
            await query.edit_message_text(
                "👌 Хорошо, напоминать не буду.\n"
                "До встречи на концерте! 🎸"
            )
    
    async def new_event_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало создания нового мероприятия (только для админа)"""
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text("⛔ Эта команда доступна только администратору.")
            return ConversationHandler.END
        
        await update.message.reply_text(
            "🎵 *Создание нового мероприятия*\n\n"
            "Введите название мероприятия:",
            parse_mode=ParseMode.MARKDOWN
        )
        return TITLE
    
    async def get_title(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получение названия мероприятия"""
        context.user_data['event_title'] = update.message.text
        await update.message.reply_text(
            "📝 Отлично! Теперь введите описание мероприятия:"
        )
        return DESCRIPTION
    
    async def get_description(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получение описания мероприятия"""
        context.user_data['event_description'] = update.message.text
        await update.message.reply_text(
            "📅 Введите дату мероприятия в формате ДД.ММ.ГГГГ (например, 25.12.2024):"
        )
        return DATE
    
    async def get_date(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получение даты мероприятия"""
        try:
            date_str = update.message.text
            date_obj = datetime.strptime(date_str, '%d.%m.%Y')
            context.user_data['event_date'] = date_obj
            await update.message.reply_text(
                "⏰ Введите время мероприятия в формате ЧЧ:ММ (например, 19:00):"
            )
            return TIME
        except ValueError:
            await update.message.reply_text(
                "❌ Неверный формат даты. Пожалуйста, используйте формат ДД.ММ.ГГГГ"
            )
            return DATE
    
    async def get_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получение времени мероприятия и сохранение"""
        try:
            time_str = update.message.text
            time_obj = datetime.strptime(time_str, '%H:%M')
            
            date_obj = context.user_data['event_date']
            event_datetime = datetime.combine(date_obj.date(), time_obj.time())
            event_datetime = TIMEZONE.localize(event_datetime)
            
            # Сохраняем мероприятие
            event_id = db.add_event(
                title=context.user_data['event_title'],
                description=context.user_data['event_description'],
                event_date=event_datetime.strftime('%Y-%m-%d %H:%M:%S'),
                created_by=update.effective_user.id
            )
            
            # Отправляем подтверждение
            await update.message.reply_text(
                f"✅ *Мероприятие успешно создано!*\n\n"
                f"🎵 {context.user_data['event_title']}\n"
                f"📅 {event_datetime.strftime('%d.%m.%Y в %H:%M')}\n\n"
                f"ID мероприятия: `{event_id}`",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Отправляем анонс мероприятия
            event = db.get_event(event_id)
            await self.send_event_message(update.effective_chat.id, event)
            
            return ConversationHandler.END
            
        except ValueError:
            await update.message.reply_text(
                "❌ Неверный формат времени. Пожалуйста, используйте формат ЧЧ:ММ"
            )
            return TIME
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Статистика по мероприятиям (для админа)"""
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text("⛔ Эта команда доступна только администратору.")
            return
        
        events = db.get_active_events()
        
        if not events:
            await update.message.reply_text("📊 Нет активных мероприятий.")
            return
        
        message = "📊 *Статистика по мероприятиям:*\n\n"
        
        for event in events:
            attendees = db.get_event_attendees(event['id'])
            total = len(attendees)
            with_reminders = sum(1 for a in attendees if a['need_reminder'])
            
            event_date = datetime.strptime(event['event_date'], '%Y-%m-%d %H:%M:%S')
            formatted_date = event_date.strftime('%d.%m.%Y в %H:%M')
            
            message += (
                f"🎵 *{event['title']}*\n"
                f"📅 {formatted_date}\n"
                f"👥 Идут: {total} чел.\n"
                f"🔔 С напоминаниями: {with_reminders}\n"
                f"🆔 ID: `{event['id']}`\n\n"
            )
        
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена создания мероприятия"""
        await update.message.reply_text("❌ Создание мероприятия отменено.")
        return ConversationHandler.END
    
    async def send_reminders_3days(self):
        """Отправка напоминаний за 3 дня"""
        reminders = db.get_reminders_to_send(72)
        await self.send_reminders(reminders, 72)
    
    async def send_reminders_12hours(self):
        """Отправка напоминаний за 12 часов"""
        reminders = db.get_reminders_to_send(12)
        await self.send_reminders(reminders, 12)
    
    async def send_reminders(self, reminders: list, hours_before: int):
        """Отправка напоминаний пользователям"""
        time_text = "3 дня" if hours_before == 72 else "12 часов"
        
        for reminder in reminders:
            try:
                event_date = datetime.strptime(reminder['event_date'], '%Y-%m-%d %H:%M:%S')
                formatted_date = event_date.strftime('%d.%m.%Y в %H:%M')
                
                message = (
                    f"🔔 *Напоминание о мероприятии!*\n\n"
                    f"Через *{time_text}* состоится:\n"
                    f"🎵 *{reminder['title']}*\n"
                    f"📅 {formatted_date}\n\n"
                    f"{reminder['description']}\n\n"
                    f"Ждём вас! 🎸"
                )
                
                await self.application.bot.send_message(
                    chat_id=reminder['user_id'],
                    text=message,
                    parse_mode=ParseMode.MARKDOWN
                )
                
                # Отмечаем, что напоминание отправлено
                db.mark_reminder_sent(reminder['user_id'], reminder['event_id'], hours_before)
                
                logger.info(f"Reminder sent to user {reminder['user_id']} for event {reminder['event_id']}")
                
            except Exception as e:
                logger.error(f"Failed to send reminder to user {reminder['user_id']}: {e}")
    
    def run(self):
        """Запуск бота"""
        logger.info("Starting bot...")
        self.application.run_polling()

# Простой HTTP сервер для пингования
async def health_check():
    from aiohttp import web
    
    async def handle(request):
        return web.Response(text="Bot is running!")
    
    app = web.Application()
    app.router.add_get('/', handle)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    
    logger.info("Health check server started on port 8080")

if __name__ == '__main__':
    # Запускаем HTTP сервер для health check
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Создаем задачу для health check
    health_task = loop.create_task(health_check())
    
    # Запускаем бота
    bot = ConcertBot()
    bot.run()